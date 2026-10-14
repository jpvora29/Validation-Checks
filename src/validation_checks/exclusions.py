"""Is a cell marked for exclusion? Red fill, red font or strikethrough, including when it comes
from conditional formatting.

Conditional-format rule types are evaluated through a small registry (`_CF_EVALUATORS`); a rule
type that is not registered is reported back as "not evaluated" instead of being guessed.
"""

import colorsys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from validation_checks.config import Settings
from validation_checks.models import Cell as SheetCell
from validation_checks.models import (
    CellPos,
    CellValue,
    CfRule,
    Mark,
    MarkReason,
    RawSheet,
    Rgb,
    Style,
    TextRun,
    column_index,
)

# --------------------------------------------------------------------------- red rule


def is_red(colour: Rgb | None, settings: Settings) -> bool:
    """A shade of red (pink to dark red) according to the hue/saturation/lightness settings."""
    if colour is None:
        return False
    hue, lightness, saturation = colorsys.rgb_to_hls(
        colour.red / 255, colour.green / 255, colour.blue / 255
    )
    hue_degrees = hue * 360
    return (
        (hue_degrees >= settings.red_hue_from or hue_degrees <= settings.red_hue_to)
        and saturation >= settings.red_min_saturation
        and settings.red_min_lightness <= lightness <= settings.red_max_lightness
    )


def is_marking_style(style: Style, settings: Settings) -> bool:
    return bool(style.strike) or is_red(style.fill, settings) or is_red(style.font, settings)


# --------------------------------------------------------------------------- cell marks


def mark_of(cell: SheetCell, conditional: Style, settings: Settings) -> Mark | None:
    """Why `cell` is excluded, or None. Conditional styles override static ones.

    Rich text counts only when every non-blank run is red or struck through.
    """
    fill = conditional.fill if conditional.fill is not None else cell.style.fill
    if is_red(fill, settings):
        reason = MarkReason.CONDITIONAL_RED_FILL if conditional.fill else MarkReason.RED_FILL
        return Mark(reason=reason, colour=fill)
    marks = [_text_mark(piece, conditional, settings) for piece in _text_pieces(cell)]
    return marks[0] if marks and all(marks) else None


def is_partially_marked(cell: SheetCell, conditional: Style, settings: Settings) -> bool:
    """Only some rich-text runs are red/struck, so the user's intent is unclear."""
    marks = [_text_mark(piece, conditional, settings) for piece in _text_pieces(cell)]
    return any(marks) and not all(marks) and mark_of(cell, conditional, settings) is None


def _text_pieces(cell: SheetCell) -> list[TextRun]:
    if cell.runs:
        return [run for run in cell.runs if run.text.strip()]
    return [TextRun(text=cell.text, font=cell.style.font, strike=bool(cell.style.strike))]


def _text_mark(piece: TextRun, conditional: Style, settings: Settings) -> Mark | None:
    if conditional.strike:
        return Mark(reason=MarkReason.CONDITIONAL_STRIKETHROUGH)
    if conditional.strike is None and piece.strike:
        return Mark(reason=MarkReason.STRIKETHROUGH)
    font = conditional.font if conditional.font is not None else piece.font
    if is_red(font, settings):
        reason = MarkReason.CONDITIONAL_RED_FONT if conditional.font else MarkReason.RED_FONT
        return Mark(reason=reason, colour=font)
    return None


# --------------------------------------------------------------------------- conditional formats


@dataclass(frozen=True, slots=True, kw_only=True)
class ConditionalFormats:
    """Styles that conditional formats apply, per cell, plus the rules we could not evaluate."""

    styles: Mapping[CellPos, Style]
    unevaluated: tuple[CfRule, ...]

    def at(self, pos: CellPos) -> Style:
        return self.styles.get(pos, Style())


class _NotEvaluableError(Exception):
    """A rule (or operand) needs Excel's formula engine."""


Evaluator = Callable[[CfRule, RawSheet, Sequence[CellPos]], set[CellPos]]
_CF_EVALUATORS: dict[str, Evaluator] = {}


def _evaluates(*kinds: str) -> Callable[[Evaluator], Evaluator]:
    def register(evaluator: Evaluator) -> Evaluator:
        _CF_EVALUATORS.update(dict.fromkeys(kinds, evaluator))
        return evaluator

    return register


def evaluate_conditional_formats(sheet: RawSheet) -> ConditionalFormats:
    """Apply rules in priority order: the first true rule to set an attribute wins it, and
    `stopIfTrue` stops lower-priority rules for that cell (Excel's behaviour)."""
    styles: dict[CellPos, Style] = {}
    stopped: set[CellPos] = set()
    unevaluated: list[CfRule] = []
    for rule in sorted(sheet.cf_rules, key=lambda cf_rule: cf_rule.priority):
        evaluator = _CF_EVALUATORS.get(rule.kind)
        cells = [
            pos
            for cell_range in rule.ranges
            for pos in cell_range.positions(sheet.max_row, sheet.max_column)
        ]
        try:
            if evaluator is None:
                raise _NotEvaluableError
            firing = evaluator(rule, sheet, cells)
        except _NotEvaluableError:
            unevaluated.append(rule)
            continue
        for pos in firing - stopped:
            styles[pos] = rule.style.overlay(styles.get(pos, Style()))
        if rule.stop_if_true:
            stopped |= firing
    return ConditionalFormats(styles=styles, unevaluated=tuple(unevaluated))


_TEXT_TESTS: Mapping[str, Callable[[str, str], bool]] = {
    "containsText": lambda text, needle: needle in text,
    "notContainsText": lambda text, needle: needle not in text,
    "beginsWith": lambda text, needle: text.startswith(needle),
    "endsWith": lambda text, needle: text.endswith(needle),
}


@_evaluates(*_TEXT_TESTS)
def _text_rule(rule: CfRule, sheet: RawSheet, cells: Sequence[CellPos]) -> set[CellPos]:
    if rule.text is None:
        raise _NotEvaluableError
    test, needle = _TEXT_TESTS[rule.kind], rule.text.casefold()
    return {pos for pos in cells if test(sheet.cell(pos).text.casefold(), needle)}


@_evaluates("containsBlanks", "notContainsBlanks")
def _blank_rule(rule: CfRule, sheet: RawSheet, cells: Sequence[CellPos]) -> set[CellPos]:
    want_blank = rule.kind == "containsBlanks"
    return {pos for pos in cells if (not sheet.cell(pos).text) == want_blank}


@_evaluates("duplicateValues", "uniqueValues")
def _duplicate_rule(rule: CfRule, sheet: RawSheet, cells: Sequence[CellPos]) -> set[CellPos]:
    keys = {pos: sheet.cell(pos).text.casefold() for pos in cells}
    counts = Counter(key for key in keys.values() if key)
    want_duplicates = rule.kind == "duplicateValues"
    return {pos for pos, key in keys.items() if key and (counts[key] > 1) == want_duplicates}


_COMPARISONS: Mapping[str, Callable[[int], bool]] = {
    "equal": lambda order: order == 0,
    "notEqual": lambda order: order != 0,
    "greaterThan": lambda order: order > 0,
    "lessThan": lambda order: order < 0,
    "greaterThanOrEqual": lambda order: order >= 0,
    "lessThanOrEqual": lambda order: order <= 0,
}


@_evaluates("cellIs")
def _cell_is_rule(rule: CfRule, sheet: RawSheet, cells: Sequence[CellPos]) -> set[CellPos]:
    operands = [_operand(operand, sheet) for operand in rule.operands]
    test = _COMPARISONS.get(rule.operator or "")
    match rule.operator, operands:
        case _, [target] if test is not None:
            return {pos for pos in cells if test(_compare(sheet.cell(pos).value, target))}
        case (("between" | "notBetween"), [first, second]):
            low, high = sorted((first, second), key=_sort_key)
            inside = {
                pos
                for pos in cells
                if _compare(sheet.cell(pos).value, low) >= 0
                and _compare(sheet.cell(pos).value, high) <= 0
            }
            return inside if rule.operator == "between" else set(cells) - inside
        case _:
            raise _NotEvaluableError


def _operand(operand: str, sheet: RawSheet) -> CellValue:
    """A quoted string, a number, or an absolute reference like $A$1; formulas are not evaluated."""
    token = operand.strip()
    if len(token) >= 2 and token[0] == token[-1] == '"':
        return token[1:-1].replace('""', '"')
    try:
        return float(token)
    except ValueError:
        pass
    parts = token.upper().split("$")
    if len(parts) == 3 and parts[0] == "" and parts[1].isalpha() and parts[2].isdigit():
        return sheet.cell(CellPos(int(parts[2]), column_index(parts[1]))).value
    raise _NotEvaluableError


def _sort_key(value: CellValue) -> tuple[int, float, str]:
    """Excel ordering: blanks/numbers before text; text compares case-insensitively."""
    if value is None:
        return (0, 0.0, "")
    if isinstance(value, int | float):
        return (0, float(value), "")
    return (1, 0.0, value.casefold())


def _compare(left: CellValue, right: CellValue) -> int:
    if left is None and isinstance(right, str):
        left = ""  # a blank cell compares as empty text against text, as 0 against numbers
    left_key, right_key = _sort_key(left), _sort_key(right)
    return (left_key > right_key) - (left_key < right_key)
