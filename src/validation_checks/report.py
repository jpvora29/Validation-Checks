"""Write the results: one workbook for the latest run, one that keeps every earlier run.

    output/validation_results.xlsx   the latest run only (overwritten each run)
    output/validation_history.xlsx   every earlier run; the previous results move here first

Every sheet is always written (headers only when empty), so "no issues" is never confused with
"check did not run". Sheet names and columns come from `REPORT_COLUMNS` in config.py.
"""

import logging
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Self, TypeAlias

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from validation_checks.config import HISTORY_FILE, MAX_COLUMN_WIDTH, REPORT_COLUMNS, RESULTS_FILE
from validation_checks.models import ConfigError, FileReport, Severity

logger = logging.getLogger(__name__)

Value: TypeAlias = str | int | float | datetime | None
Row: TypeAlias = Sequence[Value]


class ReportBuilder:
    """Fluent builder: add rows sheet by sheet (to a new or an existing workbook), then save."""

    def __init__(self, workbook: Workbook | None = None) -> None:
        if workbook is None:
            workbook = Workbook()
            workbook.remove(workbook.worksheets[0])
        self._workbook = workbook

    def add_sheet(self, title: str, rows: Iterable[Row]) -> Self:
        headers = REPORT_COLUMNS[title]
        if title in self._workbook.sheetnames:
            sheet = self._workbook[title]
        else:
            sheet = self._workbook.create_sheet(title)
            sheet.append(list(headers))
        widths = [len(header) for header in headers]
        for row in rows:
            sheet.append([str(v) if isinstance(v, str) else v for v in row])  # StrEnum -> str
            widths = [max(w, len(str(v or ""))) for w, v in zip(widths, row, strict=True)]
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{sheet.max_row}"
        for index, width in enumerate(widths, start=1):
            column = sheet.column_dimensions[get_column_letter(index)]
            column.width = min(max(width + 2, column.width or 0), MAX_COLUMN_WIDTH)
        for cell in sheet["A"][1:]:
            cell.number_format = "yyyy-mm-dd hh:mm:ss"  # the Run At column
        return self

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._workbook.save(path)
        return path


def write_report(reports: Sequence[FileReport], output_dir: Path, started: datetime) -> Path:
    """Move the previous results into the history workbook, then write this run's results."""
    latest, history = output_dir / RESULTS_FILE, output_dir / HISTORY_FILE
    ensure_writable(output_dir)  # before touching anything, so history never duplicates
    if latest.exists():
        _archive(latest, history)
    return (
        ReportBuilder()
        .add_sheet("Summary", _summary(reports, started))
        .add_sheet("Issues", _issues(reports, started))
        .add_sheet("LOB Matching", _matches(reports, started))
        .add_sheet("Exclusions", _exclusions(reports, started))
        .save(latest)
    )


def _archive(latest: Path, history: Path) -> None:
    """Append every row of the previous results to the history, matching columns by header."""
    previous = load_workbook(latest, read_only=True)
    builder = ReportBuilder(load_workbook(history) if history.exists() else None)
    for title, headers in REPORT_COLUMNS.items():
        if title not in previous.sheetnames:
            continue
        rows = list(previous[title].iter_rows(values_only=True))
        if not rows:
            continue
        old_headers = [str(header) for header in rows[0]]
        builder.add_sheet(
            title,
            (
                [_plain(dict(zip(old_headers, row, strict=False)).get(h)) for h in headers]
                for row in rows[1:]
            ),
        )
    previous.close()
    builder.save(history)
    logger.info("Previous results moved to %s", history.resolve())


def _plain(value: object) -> Value:
    """Cell values read back from the old workbook, narrowed to what we write."""
    if value is None or isinstance(value, str | int | float | datetime):
        return value
    return str(value)


def ensure_writable(output_dir: Path) -> None:
    """Fail early with a clear message if a results file is open in Excel (Windows locks it)."""
    for path in (output_dir / RESULTS_FILE, output_dir / HISTORY_FILE):
        if not path.exists():
            continue
        try:
            with path.open("r+b"):
                pass
        except PermissionError as error:
            message = (
                f"{path.resolve()} is open in another program (Excel?). Close it and run again."
            )
            raise ConfigError(message) from error


def _summary(reports: Sequence[FileReport], run_at: datetime) -> Iterable[Row]:
    for r in reports:
        yield (run_at, r.file, r.country, r.status, r.count(Severity.ERROR),
               r.count(Severity.WARNING), len(r.exclusions), r.review_count)  # fmt: skip


def _issues(reports: Sequence[FileReport], run_at: datetime) -> Iterable[Row]:
    for r in reports:
        for i in r.issues:
            yield (run_at, r.file, r.country, i.sheet, i.row, i.column, i.severity, i.check,
                   i.message, i.value)  # fmt: skip


def _matches(reports: Sequence[FileReport], run_at: datetime) -> Iterable[Row]:
    for r in reports:
        for m in r.matches:
            candidate = m.hit.candidate.display if m.hit.candidate else ""
            cells = ", ".join(cell.coordinate for cell in m.name.sources)
            yield (run_at, r.file, r.country, m.direction, m.name.display, candidate,
                   m.hit.method, m.hit.score, m.hit.status, cells)  # fmt: skip


def _exclusions(reports: Sequence[FileReport], run_at: datetime) -> Iterable[Row]:
    for r in reports:
        for e in r.exclusions:
            yield (run_at, r.file, e.sheet, e.row, e.column, e.value, e.scope, e.reason, e.colour)
