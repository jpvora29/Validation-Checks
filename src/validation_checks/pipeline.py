"""The validation pipeline: a list of steps, each taking and returning a `FileContext`.

Assemble it with the builder:

    pipeline = (
        PipelineBuilder()
        .add_step(read_file(read_workbook))
        .add_step(parse_sheets(settings))
        .add_step(run_all_checks(settings))
        .add_step(match_lob_carriers(settings, tiers))
        .build()
    )
    reports = pipeline.run_all(paths)
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Self, TypeAlias

from validation_checks.checks import country_mismatch, run_checks
from validation_checks.config import (
    EXCEL_SUFFIXES,
    FILE_NAME_HINT,
    FILE_NAME_PATTERN,
    SHEET_SPECS,
    Settings,
)
from validation_checks.matching import Tier, carrier_names, match_carriers, match_issue
from validation_checks.models import (
    CheckId,
    ConfigError,
    DataLoadError,
    Exclusion,
    FileReport,
    Issue,
    MatchResult,
    ParsedSheet,
    RawSheet,
    Severity,
    SheetKind,
    SheetLayoutError,
)
from validation_checks.sheets import find_sheet, parse_sheet

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class FileContext:
    """Everything known about one file so far; each step returns an updated copy."""

    path: Path
    country: str = ""
    raw_sheets: tuple[RawSheet, ...] = ()
    sheets: Mapping[SheetKind, ParsedSheet] = field(default_factory=dict)
    issues: tuple[Issue, ...] = ()
    exclusions: tuple[Exclusion, ...] = ()
    matches: tuple[MatchResult, ...] = ()

    def report(self) -> FileReport:
        return FileReport(
            file=self.path.name,
            country=self.country,
            issues=self.issues,
            exclusions=self.exclusions,
            matches=self.matches,
            sheets_validated=len(self.sheets),
        )


Step: TypeAlias = Callable[[FileContext], FileContext]
ReadWorkbook: TypeAlias = Callable[[Path], Sequence[RawSheet]]


# --------------------------------------------------------------------------- steps


def read_file(read_workbook: ReadWorkbook) -> Step:
    """Check the file type and name, then read every sheet. Raises DataLoadError."""

    def step(context: FileContext) -> FileContext:
        path = context.path
        if path.suffix.lower() not in EXCEL_SUFFIXES:
            raise DataLoadError("Not an Excel workbook (.xlsx / .xlsm)")
        if (name := FILE_NAME_PATTERN.match(path.stem)) is None:
            raise DataLoadError(FILE_NAME_HINT)
        country = name["country"].replace("_", " ").strip()
        try:
            raw_sheets = tuple(read_workbook(path))
        except DataLoadError as error:
            raise DataLoadError(str(error), country=country) from error
        return replace(context, country=country, raw_sheets=raw_sheets)

    return step


def parse_sheets(settings: Settings) -> Step:
    """Find the Peers, LOB and Panel sheets and turn them into records, applying exclusions."""

    def step(context: FileContext) -> FileContext:
        sheets: dict[SheetKind, ParsedSheet] = {}
        exclusions: list[Exclusion] = []
        issues: list[Issue] = []
        used: set[str] = set()
        for spec in SHEET_SPECS:
            try:
                raw = find_sheet(context.raw_sheets, spec)
                used.add(raw.name)
                result = parse_sheet(raw, spec, settings)
            except SheetLayoutError as error:
                issues.append(_sheet_problem(spec.kind, str(error), Severity.ERROR))
                continue
            sheets[spec.kind] = result.sheet
            exclusions.extend(result.exclusions)
            issues.extend(result.warnings)
        issues.extend(
            _sheet_problem(raw.name, "Unrecognised sheet; it was not validated", Severity.WARNING)
            for raw in context.raw_sheets
            if raw.name not in used
        )
        return replace(
            context,
            sheets=sheets,
            exclusions=(*context.exclusions, *exclusions),
            issues=(*context.issues, *issues),
        )

    return step


def run_all_checks(settings: Settings) -> Step:
    """Every registered check on every sheet, plus the cross-sheet country check."""

    def step(context: FileContext) -> FileContext:
        issues = [
            issue for sheet in context.sheets.values() for issue in run_checks(sheet, settings)
        ]
        issues += country_mismatch(list(context.sheets.values()), context.country)
        return replace(context, issues=(*context.issues, *issues))

    return step


def match_lob_carriers(settings: Settings, tiers: Sequence[Tier]) -> Step:
    """Match Peers carriers against LOB carriers (needs both sheets)."""

    def step(context: FileContext) -> FileContext:
        peers, lob = context.sheets.get(SheetKind.PEERS), context.sheets.get(SheetKind.LOB)
        if peers is None or lob is None:
            return context
        matches = match_carriers(
            carrier_names(peers, settings.stopwords), carrier_names(lob, settings.stopwords), tiers
        )
        issues = [
            issue
            for result in matches
            if (issue := match_issue(result, peers_sheet=peers.title, lob_sheet=lob.title))
        ]
        return replace(context, matches=tuple(matches), issues=(*context.issues, *issues))

    return step


def _sheet_problem(sheet: str, message: str, severity: Severity) -> Issue:
    return Issue(
        sheet=sheet,
        row=None,
        column="",
        severity=severity,
        check=CheckId.FILE_ERROR,
        message=message,
    )


# --------------------------------------------------------------------------- pipeline


@dataclass(frozen=True, slots=True)
class Pipeline:
    steps: tuple[Step, ...]

    def run(self, path: Path) -> FileReport:
        context = FileContext(path=path)
        try:
            for step in self.steps:
                context = step(context)
        except DataLoadError as error:
            logger.error("%s: %s", path.name, error)
            return FileReport.failed(path.name, str(error), country=error.country)
        report = context.report()
        logger.info(
            "%s: %s (%d errors, %d warnings, %d exclusions, %d LOB to review)",
            report.file,
            report.status,
            report.count(Severity.ERROR),
            report.count(Severity.WARNING),
            len(report.exclusions),
            report.review_count,
        )
        return report

    def run_all(self, paths: Sequence[Path]) -> list[FileReport]:
        """Run every file; an unexpected error in one file never stops the others."""
        reports: list[FileReport] = []
        for number, path in enumerate(paths, start=1):
            logger.info("[%d/%d] Validating %s", number, len(paths), path.name)
            try:
                reports.append(self.run(path))
            except Exception as error:
                logger.exception("%s: unexpected error", path.name)
                reports.append(FileReport.failed(path.name, f"Unexpected error: {error!r}"))
        return reports


class PipelineBuilder:
    """Fluent assembly of the pipeline's steps, in order."""

    def __init__(self) -> None:
        self._steps: list[Step] = []

    def add_step(self, step: Step) -> Self:
        self._steps.append(step)
        return self

    def build(self) -> Pipeline:
        if not self._steps:
            raise ConfigError("A pipeline needs at least one step")
        return Pipeline(tuple(self._steps))
