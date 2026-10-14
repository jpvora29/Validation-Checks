"""Turn a raw sheet into records: find the sheet and its header row, then apply exclusions.

Exclusion scope (agreed table):

| Marked cell                   | Effect                        |
|-------------------------------|-------------------------------|
| Header cell                   | whole column excluded         |
| Identity cell (Peers / LOB)   | whole row excluded            |
| Peer or practice cell         | only that value excluded      |
| Any cell (User Panel)         | whole employee row excluded   |
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from validation_checks.config import (
    HEADER_SEARCH_ROWS,
    LEGEND_EXCLUDE_TEXT,
    NAME_FIELDS,
    PEER_COLUMN_PATTERN,
    Settings,
)
from validation_checks.exclusions import (
    ConditionalFormats,
    evaluate_conditional_formats,
    is_marking_style,
    is_partially_marked,
    mark_of,
)
from validation_checks.models import (
    CellPos,
    CheckId,
    Column,
    Entry,
    Exclusion,
    ExclusionScope,
    Field,
    Issue,
    Mark,
    ParsedSheet,
    RawSheet,
    Record,
    Severity,
    SheetKind,
    SheetLayoutError,
    SheetSpec,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SheetResult:
    sheet: ParsedSheet
    exclusions: tuple[Exclusion, ...]
    warnings: tuple[Issue, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class Layout:
    """Where things are. `entries` are peer / practice columns, excluded cell by cell;
    every other named column identifies the record, so marking it drops the whole row."""

    header_row: int
    fields: Mapping[Field, Column]
    entries: tuple[Column, ...]
    columns: tuple[Column, ...]  # every named column, left to right


# --------------------------------------------------------------------------- locate


def find_sheet(sheets: Sequence[RawSheet], spec: SheetSpec) -> RawSheet:
    matches = [sheet for sheet in sheets if re.search(spec.name_pattern, sheet.name, re.I)]
    if not matches:
        raise SheetLayoutError(f"No sheet found for {spec.kind}")
    if len(matches) > 1:
        names = ", ".join(f"'{sheet.name}'" for sheet in matches)
        raise SheetLayoutError(f"Several sheets could be {spec.kind}: {names}")
    return matches[0]


def detect_layout(sheet: RawSheet, spec: SheetSpec) -> Layout:
    """The header row is the first row holding every required header."""
    for row in range(1, min(sheet.max_row, HEADER_SEARCH_ROWS) + 1):
        named = [
            Column(index=index, header=" ".join(sheet.text(row, index).split()))
            for index in range(1, sheet.max_column + 1)
        ]
        named = [column for column in named if column.header]
        fields = _match_fields(named, spec)
        if spec.required <= fields.keys():
            return Layout(
                header_row=row,
                fields=fields,
                entries=_entry_columns(spec.kind, named, fields),
                columns=tuple(named),
            )
    required = ", ".join(sorted(spec.required))
    raise SheetLayoutError(f"Header row not found in '{sheet.name}' (looking for: {required})")


def _match_fields(named: Sequence[Column], spec: SheetSpec) -> dict[Field, Column]:
    fields: dict[Field, Column] = {}
    for field, pattern in spec.columns.items():
        taken = {column.index for column in fields.values()}
        found = next(
            (c for c in named if c.index not in taken and re.search(pattern, c.header, re.I)),
            None,
        )
        if found is not None:
            fields[field] = found
    return fields


def _entry_columns(
    kind: SheetKind, named: Sequence[Column], fields: Mapping[Field, Column]
) -> tuple[Column, ...]:
    unassigned = [column for column in named if column not in fields.values()]
    match kind:
        case SheetKind.PEERS:  # any "Peer N" column
            return tuple(c for c in unassigned if PEER_COLUMN_PATTERN.match(c.header))
        case SheetKind.LOB:  # every column right of "ICA carrier" (or "Carrier")
            anchor = fields.get(Field.ICA_CARRIER, fields[Field.CARRIER])
            practices = tuple(c for c in unassigned if c.index > anchor.index)
            if not practices:
                raise SheetLayoutError(f"No practice columns found right of '{anchor.header}'")
            return practices
        case SheetKind.PANEL:
            if not any(name in fields for name in NAME_FIELDS):
                raise SheetLayoutError("User Panel has no Name / First Name / Last Name column")
            return ()


# --------------------------------------------------------------------------- parse


def parse_sheet(sheet: RawSheet, spec: SheetSpec, settings: Settings) -> SheetResult:
    """Build the records of one sheet, dropping everything that is marked for exclusion."""
    layout = detect_layout(sheet, spec)
    parser = _Parser(sheet, evaluate_conditional_formats(sheet), settings)
    excluded = parser.excluded_columns(layout)
    active = [column for column in layout.columns if column.index not in excluded]
    entry_columns = [column for column in active if column in layout.entries]
    # In the User Panel any marked cell drops the employee; elsewhere only identity cells do.
    key_columns = (
        active if spec.kind is SheetKind.PANEL else [c for c in active if c not in entry_columns]
    )

    records: list[Record] = []
    for row in range(layout.header_row + 1, sheet.max_row + 1):
        if not any(sheet.text(row, column.index) for column in active):
            continue  # blank row
        if parser.excludes_row(row, key_columns):
            continue
        parser.warn_about_row(row, active)
        entries = parser.kept_entries(row, entry_columns)
        values = {
            field: sheet.text(row, column.index)
            for field, column in layout.fields.items()
            if column.index not in excluded
        }
        records.append(Record(row=row, values=values, entries=entries))

    parser.warn_about_sheet(layout, active)
    parsed = ParsedSheet(
        kind=spec.kind,
        title=sheet.name,
        fields=layout.fields,
        records=tuple(records),
        active_fields=frozenset(f for f, c in layout.fields.items() if c.index not in excluded),
    )
    return SheetResult(
        sheet=parsed, exclusions=tuple(parser.exclusions), warnings=tuple(parser.warnings)
    )


class _Parser:
    """Collects exclusions and warnings while one sheet is parsed."""

    def __init__(self, sheet: RawSheet, formats: ConditionalFormats, settings: Settings) -> None:
        self.sheet = sheet
        self.formats = formats
        self.settings = settings
        self.exclusions: list[Exclusion] = []
        self.warnings: list[Issue] = []

    def mark(self, row: int, column: int) -> Mark | None:
        pos = CellPos(row, column)
        return mark_of(self.sheet.cell(pos), self.formats.at(pos), self.settings)

    def excluded_columns(self, layout: Layout) -> set[int]:
        marks = {c.index: m for c in layout.columns if (m := self.mark(layout.header_row, c.index))}
        if marks and len(marks) == len(layout.columns):
            # A fully red header row is template styling, not "exclude the whole sheet".
            self._warn(
                layout.header_row,
                "",
                CheckId.HEADER_ROW_MARKED,
                "Every header cell is red/struck; treated as styling, no column excluded",
            )
            return set()
        for column in layout.columns:
            if column.index in marks:
                self._exclude(layout.header_row, column, ExclusionScope.COLUMN, marks[column.index])
        return set(marks)

    def excludes_row(self, row: int, key_columns: Sequence[Column]) -> bool:
        for column in key_columns:
            if (mark := self.mark(row, column.index)) is not None:
                self._exclude(row, column, ExclusionScope.ROW, mark)
                return True
        return False

    def kept_entries(self, row: int, entry_columns: Sequence[Column]) -> tuple[Entry, ...]:
        entries: list[Entry] = []
        for column in entry_columns:
            if not (value := self.sheet.text(row, column.index)):
                continue
            if (mark := self.mark(row, column.index)) is not None:
                self._exclude(row, column, ExclusionScope.CELL, mark)
            else:
                entries.append(Entry(row=row, column=column, value=value))
        return tuple(entries)

    def warn_about_row(self, row: int, active: Sequence[Column]) -> None:
        if row in self.sheet.hidden_rows:
            self._warn(
                row, "", CheckId.HIDDEN_ROW, "Row is hidden but not marked; it was validated"
            )
        for column in active:
            pos = CellPos(row, column.index)
            if is_partially_marked(self.sheet.cell(pos), self.formats.at(pos), self.settings):
                self._warn(
                    row,
                    column.header,
                    CheckId.PARTIAL_FORMAT,
                    "Only part of the text is red/struck; cell kept, please review",
                    self.sheet.text(row, column.index),
                )

    def warn_about_sheet(self, layout: Layout, active: Sequence[Column]) -> None:
        for column in active:
            if column.index in self.sheet.hidden_columns:
                self._warn(
                    None,
                    column.header,
                    CheckId.HIDDEN_COLUMN,
                    "Column is hidden but not marked; it was validated",
                )
        for rule in self.formats.unevaluated:
            if is_marking_style(rule.style, self.settings):
                self._warn(
                    None,
                    "",
                    CheckId.CONDITIONAL_FORMAT_NOT_EVALUATED,
                    f"'{rule.kind}' rule applies red/strikethrough but cannot be evaluated;"
                    " its cells were NOT excluded, please review",
                    rule.reference,
                )
        for row in range(1, layout.header_row):
            for index in range(1, self.sheet.max_column + 1):
                legend = self.sheet.text(row, index).casefold() == LEGEND_EXCLUDE_TEXT
                if legend and self.mark(row, index) is None:
                    self._warn(
                        row,
                        "",
                        CheckId.LEGEND_NOT_RED,
                        "The EXCLUDE legend is not red; has the template changed?",
                        CellPos(row, index).coordinate,
                    )

    def _exclude(self, row: int, column: Column, scope: ExclusionScope, mark: Mark) -> None:
        self.exclusions.append(
            Exclusion(
                sheet=self.sheet.name,
                row=row,
                column=column.header,
                value=self.sheet.text(row, column.index),
                scope=scope,
                reason=mark.reason,
                colour=mark.colour.hex if mark.colour else "",
            )
        )

    def _warn(
        self, row: int | None, column: str, check: CheckId, message: str, value: str = ""
    ) -> None:
        self.warnings.append(
            Issue(
                sheet=self.sheet.name,
                row=row,
                column=column,
                severity=Severity.WARNING,
                check=check,
                message=message,
                value=value,
            )
        )
