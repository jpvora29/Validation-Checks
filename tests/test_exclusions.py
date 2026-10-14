"""Red rule, cell marks and conditional-format evaluation."""

import pytest

from tests.factories import GREEN, RED, SETTINGS, make_sheet, pos
from validation_checks.exclusions import (
    evaluate_conditional_formats,
    is_partially_marked,
    is_red,
    mark_of,
)
from validation_checks.models import (
    Cell,
    CellRange,
    CellValue,
    CfRule,
    MarkReason,
    Rgb,
    Style,
    TextRun,
)

NO_STYLE = Style()

# --------------------------------------------------------------------------- red rule

RED_SHADES = ["FF0000", "C00000", "800000", "FFC7CE", "FF7C80", "FF66CC", "FF1493", "C0504D"]
NOT_RED = ["FFA500", "FF00FF", "00B050", "000000", "FFFFFF", "808080", "FFFF00", "4F81BD"]


@pytest.mark.parametrize("hex_colour", RED_SHADES)
def test_shades_of_red_and_pink_are_red(hex_colour: str) -> None:
    assert is_red(Rgb.from_hex(hex_colour), SETTINGS)


@pytest.mark.parametrize("hex_colour", NOT_RED)
def test_other_colours_are_not_red(hex_colour: str) -> None:
    assert not is_red(Rgb.from_hex(hex_colour), SETTINGS)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("FFFF0000", Rgb(255, 0, 0)), ("00ff0000", Rgb(255, 0, 0)), ("#C00000", Rgb(192, 0, 0))],
)
def test_hex_parsing(text: str, expected: Rgb) -> None:
    assert Rgb.from_hex(text) == expected


@pytest.mark.parametrize("text", ["", "red", "FF00", "GGGGGG", "Values must be of type str"])
def test_hex_parsing_rejects_garbage(text: str) -> None:
    assert Rgb.from_hex(text) is None


# --------------------------------------------------------------------------- cell marks


@pytest.mark.parametrize(
    ("style", "reason"),
    [
        (Style(fill=RED), MarkReason.RED_FILL),
        (Style(font=RED), MarkReason.RED_FONT),
        (Style(strike=True), MarkReason.STRIKETHROUGH),
    ],
)
def test_static_marks(style: Style, reason: MarkReason) -> None:
    mark = mark_of(Cell(value="x", style=style), NO_STYLE, SETTINGS)

    assert mark is not None
    assert mark.reason is reason


def test_green_cell_is_not_marked() -> None:
    assert mark_of(Cell(value="x", style=Style(fill=GREEN, font=GREEN)), NO_STYLE, SETTINGS) is None


def test_conditional_fill_overrides_static_red_fill() -> None:
    assert mark_of(Cell(value="x", style=Style(fill=RED)), Style(fill=GREEN), SETTINGS) is None


def test_conditional_red_font_is_reported_as_conditional() -> None:
    mark = mark_of(Cell(value="x"), Style(font=RED), SETTINGS)

    assert mark is not None
    assert mark.reason is MarkReason.CONDITIONAL_RED_FONT


def test_conditional_strike_off_hides_static_strike() -> None:
    assert mark_of(Cell(value="x", style=Style(strike=True)), Style(strike=False), SETTINGS) is None


def test_rich_text_fully_red_or_struck_is_marked() -> None:
    runs = (
        TextRun(text="Carrier ", font=RED, strike=False),
        TextRun(text="A", font=None, strike=True),
    )
    cell = Cell(value="Carrier A", runs=runs)

    assert mark_of(cell, NO_STYLE, SETTINGS) is not None
    assert not is_partially_marked(cell, NO_STYLE, SETTINGS)


def test_rich_text_partly_red_is_kept_but_flagged() -> None:
    runs = (
        TextRun(text="Carrier ", font=RED, strike=False),
        TextRun(text="A", font=None, strike=False),
    )
    cell = Cell(value="Carrier A", runs=runs)

    assert mark_of(cell, NO_STYLE, SETTINGS) is None
    assert is_partially_marked(cell, NO_STYLE, SETTINGS)


# --------------------------------------------------------------------------- conditional formats

COLUMN_A = (CellRange(min_row=1, min_column=1, max_row=4, max_column=1),)
ROWS: list[list[CellValue]] = [["X"], ["x"], ["Y"], [None]]
RED_FILL = Style(fill=RED)


def rule(
    kind: str,
    *,
    operator: str | None = None,
    operands: tuple[str, ...] = (),
    text: str | None = None,
    style: Style = RED_FILL,
    priority: int = 1,
    stop_if_true: bool = False,
) -> CfRule:
    return CfRule(
        kind=kind,
        operator=operator,
        operands=operands,
        text=text,
        style=style,
        priority=priority,
        stop_if_true=stop_if_true,
        ranges=COLUMN_A,
    )


def fired(*rules: CfRule, rows: list[list[CellValue]] = ROWS) -> set[str]:
    formats = evaluate_conditional_formats(make_sheet(rows, cf_rules=rules))
    return {p.coordinate for p in formats.styles}


def test_cell_is_equal_text_ignores_case() -> None:
    assert fired(rule("cellIs", operator="equal", operands=('"X"',))) == {"A1", "A2"}


def test_cell_is_between_numbers() -> None:
    rows: list[list[CellValue]] = [[5], [50], [500], ["text"]]

    assert fired(rule("cellIs", operator="between", operands=("10", "100")), rows=rows) == {"A2"}


def test_cell_is_absolute_reference() -> None:
    rows: list[list[CellValue]] = [["Y"], ["Y"], ["Z"], [None]]

    assert fired(rule("cellIs", operator="equal", operands=("$A$1",)), rows=rows) == {"A1", "A2"}


@pytest.mark.parametrize(
    ("kind", "text", "expected"),
    [
        ("containsText", "x", {"A1", "A2"}),
        ("notContainsText", "x", {"A3", "A4"}),
        ("beginsWith", "y", {"A3"}),
        ("endsWith", "X", {"A1", "A2"}),
        ("containsBlanks", None, {"A4"}),
        ("notContainsBlanks", None, {"A1", "A2", "A3"}),
        ("duplicateValues", None, {"A1", "A2"}),
        ("uniqueValues", None, {"A3"}),
    ],
)
def test_supported_rule_types(kind: str, text: str | None, expected: set[str]) -> None:
    assert fired(rule(kind, text=text)) == expected


@pytest.mark.parametrize(
    "unsupported",
    [
        rule("expression", operands=("$A1=1",)),
        rule("cellIs", operator="equal", operands=("A1",)),  # relative reference
        rule("cellIs", operator="equal", operands=("LEN(A1)>2",)),  # formula
    ],
)
def test_unsupported_rules_are_reported_not_guessed(unsupported: CfRule) -> None:
    formats = evaluate_conditional_formats(make_sheet(ROWS, cf_rules=(unsupported,)))

    assert formats.styles == {}
    assert formats.unevaluated == (unsupported,)


def test_higher_priority_rule_wins() -> None:
    green_first = rule("containsText", text="x", style=Style(fill=GREEN), priority=1)
    red_second = rule("containsText", text="x", style=RED_FILL, priority=2)

    formats = evaluate_conditional_formats(make_sheet(ROWS, cf_rules=(red_second, green_first)))

    assert formats.at(pos("A1")).fill == GREEN


def test_stop_if_true_blocks_lower_priority_rules() -> None:
    stopper = rule("containsText", text="x", style=Style(font=GREEN), stop_if_true=True)
    strike = rule("containsText", text="x", style=Style(strike=True), priority=2)

    formats = evaluate_conditional_formats(make_sheet(ROWS, cf_rules=(stopper, strike)))

    assert formats.at(pos("A1")).strike is None
