"""All data types in one place: enums, errors, Excel cells, parsed records and results."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Self, TypeAlias

# --------------------------------------------------------------------------- enums


class SheetKind(StrEnum):
    PEERS = "Country Peers"
    LOB = "LOB Mapping"
    PANEL = "User Panel"


class Field(StrEnum):
    REGION = "Region"
    COUNTRY = "Country"
    CARRIER_GROUP = "Carrier Group"
    CARRIER_NAME = "Carrier Name"
    CARRIER_ENTITY = "Carrier Entity"
    ICA_CARRIER = "ICA carrier"
    CARRIER = "Carrier"
    EMPLOYEE_ID = "Employee ID"
    LEGAL_NAME = "Name"
    FIRST_NAME = "First Name"
    LAST_NAME = "Last Name"
    EMAIL = "Email"


class Severity(StrEnum):
    ERROR = "Error"
    WARNING = "Warning"


class CheckId(StrEnum):
    CARRIER_GROUP_EMPTY = "Carrier Group empty"
    CARRIER_NAME_EMPTY = "Carrier Name empty"
    TOO_FEW_PEERS = "Too few peers"
    DUPLICATE_PEER = "Duplicate peer"
    SELF_PEER = "Carrier is its own peer"
    DUPLICATE_CARRIER = "Duplicate carrier"
    NO_PRACTICE = "No practice"
    INVALID_PRACTICE_VALUE = "Unexpected practice value"
    EMAIL_EMPTY = "Email empty"
    EMAIL_INVALID = "Email invalid"
    COUNTRY_EMPTY = "Country empty"
    NAME_EMPTY = "Name empty"
    DUPLICATE_EMPLOYEE_ID = "Duplicate Employee ID"
    DUPLICATE_EMAIL = "Duplicate Email"
    COUNTRY_MISMATCH = "Country mismatch"
    HIDDEN_ROW = "Hidden row"
    HIDDEN_COLUMN = "Hidden column"
    PARTIAL_FORMAT = "Partially formatted cell"
    CONDITIONAL_FORMAT_NOT_EVALUATED = "Conditional format not evaluated"
    LEGEND_NOT_RED = "Exclude legend not red"
    HEADER_ROW_MARKED = "Header row styled red"
    FILE_ERROR = "File / sheet problem"
    CARRIER_NOT_IN_LOB = "Carrier missing from LOB"
    LOB_CARRIER_UNUSED = "LOB carrier not in Peers"
    POSSIBLE_CARRIER_MATCH = "Possible carrier match"


class MarkReason(StrEnum):
    RED_FILL = "red fill"
    RED_FONT = "red font"
    STRIKETHROUGH = "strikethrough"
    CONDITIONAL_RED_FILL = "conditional format: red fill"
    CONDITIONAL_RED_FONT = "conditional format: red font"
    CONDITIONAL_STRIKETHROUGH = "conditional format: strikethrough"


class ExclusionScope(StrEnum):
    ROW = "Row"
    CELL = "Cell"
    COLUMN = "Column"


class Direction(StrEnum):
    PEER_TO_LOB = "Peers -> LOB"
    LOB_TO_PEER = "LOB -> Peers"


class MatchMethod(StrEnum):
    EXACT = "exact"
    ALIAS = "alias"
    FUZZY = "fuzzy"
    SEMANTIC = "semantic"
    NONE = "none"


class MatchStatus(StrEnum):
    MATCHED = "Matched"
    MATCHED_ALIAS = "Matched (alias)"
    MATCHED_FUZZY = "Matched (fuzzy)"
    SUGGESTED = "Suggested - needs review"
    NOT_FOUND = "Not found"


class FileStatus(StrEnum):
    OK = "OK"
    ISSUES = "Issues found"
    FAILED = "Failed"


# --------------------------------------------------------------------------- errors


class ValidationChecksError(Exception):
    """Base class for every expected failure in this project."""


class DataLoadError(ValidationChecksError):
    """A file cannot be used at all (wrong type or name, unreadable)."""

    def __init__(self, message: str, *, country: str = "") -> None:
        super().__init__(message)
        self.country = country


class SheetLayoutError(ValidationChecksError):
    """A sheet is missing, ambiguous, or lacks the headers needed to validate it."""


class ConfigError(ValidationChecksError):
    """A setting or supporting file (alias CSV, model folder) is invalid."""


# --------------------------------------------------------------------------- Excel cells

CellValue: TypeAlias = str | int | float | None


def column_letter(index: int) -> str:
    """1 -> A, 27 -> AA."""
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def column_index(letters: str) -> int:
    """A -> 1, AA -> 27."""
    index = 0
    for letter in letters.upper():
        index = index * 26 + ord(letter) - ord("A") + 1
    return index


def cell_text(value: CellValue) -> str:
    """The trimmed text a user sees in Excel (10007481.0 shows as 10007481)."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


@dataclass(frozen=True, slots=True)
class Rgb:
    red: int
    green: int
    blue: int

    @classmethod
    def from_hex(cls, value: str) -> Self | None:
        """Parse RRGGBB or AARRGGBB (alpha ignored); None for anything else."""
        digits = value.strip().lstrip("#")
        if len(digits) == 8:
            digits = digits[2:]
        if len(digits) != 6:
            return None
        try:
            return cls(int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))
        except ValueError:
            return None

    @property
    def hex(self) -> str:
        return f"{self.red:02X}{self.green:02X}{self.blue:02X}"


@dataclass(frozen=True, slots=True, kw_only=True)
class Style:
    """Fill colour, font colour and strikethrough. None means "not set"."""

    fill: Rgb | None = None
    font: Rgb | None = None
    strike: bool | None = None

    def overlay(self, other: "Style") -> "Style":
        """Attributes set in `other` replace ours (how conditional formats apply)."""
        return Style(
            fill=other.fill if other.fill is not None else self.fill,
            font=other.font if other.font is not None else self.font,
            strike=other.strike if other.strike is not None else self.strike,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TextRun:
    """One rich-text run, font already resolved against the cell's own font."""

    text: str
    font: Rgb | None
    strike: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class Cell:
    value: CellValue = None
    style: Style = field(default_factory=Style)
    runs: tuple[TextRun, ...] = ()

    @property
    def text(self) -> str:
        return cell_text(self.value)


@dataclass(frozen=True, slots=True, order=True)
class CellPos:
    row: int
    column: int

    @property
    def coordinate(self) -> str:
        return f"{column_letter(self.column)}{self.row}"


@dataclass(frozen=True, slots=True, kw_only=True)
class CellRange:
    min_row: int
    min_column: int
    max_row: int
    max_column: int

    def positions(self, max_row: int, max_column: int) -> Iterator[CellPos]:
        """Cells in the range, clipped to the used area (CF ranges can be whole columns)."""
        for row in range(self.min_row, min(self.max_row, max_row) + 1):
            for column in range(self.min_column, min(self.max_column, max_column) + 1):
                yield CellPos(row, column)

    @property
    def reference(self) -> str:
        start = CellPos(self.min_row, self.min_column).coordinate
        end = CellPos(self.max_row, self.max_column).coordinate
        return start if start == end else f"{start}:{end}"


@dataclass(frozen=True, slots=True, kw_only=True)
class CfRule:
    """A conditional-format rule as read from Excel (`kind` is Excel's rule type name)."""

    kind: str
    operator: str | None
    operands: tuple[str, ...]
    text: str | None
    style: Style
    priority: int
    stop_if_true: bool
    ranges: tuple[CellRange, ...]

    @property
    def reference(self) -> str:
        return " ".join(cell_range.reference for cell_range in self.ranges)


@dataclass(frozen=True, slots=True, kw_only=True)
class RawSheet:
    """A worksheet exactly as read from the file, before any business rule is applied."""

    name: str
    cells: Mapping[CellPos, Cell]
    max_row: int
    max_column: int
    cf_rules: tuple[CfRule, ...] = ()
    hidden_rows: frozenset[int] = frozenset()
    hidden_columns: frozenset[int] = frozenset()

    def cell(self, pos: CellPos) -> Cell:
        return self.cells.get(pos, _EMPTY_CELL)

    def text(self, row: int, column: int) -> str:
        return self.cell(CellPos(row, column)).text


_EMPTY_CELL = Cell()


@dataclass(frozen=True, slots=True, kw_only=True)
class Mark:
    """Why a cell is excluded."""

    reason: MarkReason
    colour: Rgb | None = None


# --------------------------------------------------------------------------- parsed sheets


@dataclass(frozen=True, slots=True, kw_only=True)
class SheetSpec:
    """How to recognise a sheet and its columns (instances live in config.py)."""

    kind: SheetKind
    name_pattern: str
    columns: Mapping[Field, str]
    required: frozenset[Field]


@dataclass(frozen=True, slots=True, kw_only=True)
class Column:
    index: int
    header: str

    @property
    def letter(self) -> str:
        return column_letter(self.index)


@dataclass(frozen=True, slots=True, kw_only=True)
class Entry:
    """One peer name or practice mark that survived exclusion."""

    row: int
    column: Column
    value: str

    @property
    def coordinate(self) -> str:
        return f"{self.column.letter}{self.row}"


@dataclass(frozen=True, slots=True, kw_only=True)
class Record:
    """One non-excluded data row: its identity values plus its peers / practices."""

    row: int
    values: Mapping[Field, str]
    entries: tuple[Entry, ...]

    def get(self, field: Field) -> str:
        return self.values.get(field, "")


@dataclass(frozen=True, slots=True, kw_only=True)
class Issue:
    sheet: str
    row: int | None
    column: str
    severity: Severity
    check: CheckId
    message: str
    value: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedSheet:
    """A sheet after header detection and exclusions: what the checks validate."""

    kind: SheetKind
    title: str
    fields: Mapping[Field, Column]
    records: tuple[Record, ...]
    active_fields: frozenset[Field]

    def header(self, field: Field) -> str:
        return self.fields[field].header

    def issue(
        self,
        row: int | None,
        column: str,
        check: CheckId,
        message: str,
        *,
        value: str = "",
        severity: Severity = Severity.ERROR,
    ) -> Issue:
        return Issue(
            sheet=self.title,
            row=row,
            column=column,
            severity=severity,
            check=check,
            message=message,
            value=value,
        )


# --------------------------------------------------------------------------- results


@dataclass(frozen=True, slots=True, kw_only=True)
class Exclusion:
    sheet: str
    row: int
    column: str
    value: str
    scope: ExclusionScope
    reason: str
    colour: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CarrierName:
    display: str
    key: str
    sources: tuple[CellPos, ...]  # every cell the name appears in


@dataclass(frozen=True, slots=True, kw_only=True)
class Hit:
    """What a matching tier found for one name."""

    candidate: CarrierName | None
    method: MatchMethod
    status: MatchStatus
    score: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class MatchResult:
    direction: Direction
    name: CarrierName
    hit: Hit

    @property
    def needs_review(self) -> bool:
        return self.hit.status in {MatchStatus.SUGGESTED, MatchStatus.NOT_FOUND}


@dataclass(frozen=True, slots=True, kw_only=True)
class FileReport:
    file: str
    country: str
    issues: tuple[Issue, ...] = ()
    exclusions: tuple[Exclusion, ...] = ()
    matches: tuple[MatchResult, ...] = ()
    sheets_validated: int = 0

    @classmethod
    def failed(cls, file: str, message: str, *, country: str = "") -> Self:
        """A file that could not be validated at all; the reason is reported as an Issue."""
        issue = Issue(
            sheet="(file)",
            row=None,
            column="",
            severity=Severity.ERROR,
            check=CheckId.FILE_ERROR,
            message=message,
        )
        return cls(file=file, country=country, issues=(issue,))

    def count(self, severity: Severity) -> int:
        return sum(1 for issue in self.issues if issue.severity is severity)

    @property
    def review_count(self) -> int:
        return sum(1 for match in self.matches if match.needs_review)

    @property
    def status(self) -> FileStatus:
        if self.sheets_validated == 0:
            return FileStatus.FAILED
        if self.issues:
            return FileStatus.ISSUES
        return FileStatus.OK
