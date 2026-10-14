from collections.abc import Mapping, Sequence

import pytest

from tests.factories import (
    LEGEND_ROWS,
    LOB_HEADER,
    PANEL_HEADER,
    PEERS_HEADER,
    RED,
    SETTINGS,
    lob_row,
    make_sheet,
    panel_row,
    peers_row,
)
from validation_checks.checks import CHECKS, country_mismatch, run_checks
from validation_checks.config import SHEET_SPECS
from validation_checks.models import CellValue, CheckId, ParsedSheet, Severity, SheetKind, Style
from validation_checks.sheets import parse_sheet

SPECS = {spec.kind: spec for spec in SHEET_SPECS}
HEADERS = {SheetKind.PEERS: PEERS_HEADER, SheetKind.LOB: LOB_HEADER, SheetKind.PANEL: PANEL_HEADER}
FIVE = ["Carrier A", "Carrier B", "Carrier C", "Carrier D", "Carrier E"]


def sheet(
    kind: SheetKind, data: Sequence[Sequence[CellValue]], styles: Mapping[str, Style] | None = None
) -> ParsedSheet:
    raw = make_sheet([*LEGEND_ROWS, HEADERS[kind], *data], styles=styles)
    return parse_sheet(raw, SPECS[kind], SETTINGS).sheet


def found(parsed: ParsedSheet) -> list[CheckId]:
    return [issue.check for issue in run_checks(parsed, SETTINGS)]


def test_every_sheet_has_registered_checks() -> None:
    assert all(CHECKS[kind] for kind in SheetKind)


def test_clean_peers_row_passes() -> None:
    assert found(sheet(SheetKind.PEERS, [peers_row("CHUBB", FIVE)])) == []


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (peers_row("", FIVE), CheckId.CARRIER_NAME_EMPTY),
        (peers_row("CHUBB", FIVE, group=""), CheckId.CARRIER_GROUP_EMPTY),
        (peers_row("CHUBB", FIVE[:4]), CheckId.TOO_FEW_PEERS),
    ],
)
def test_peers_errors(row: tuple[CellValue, ...], expected: CheckId) -> None:
    assert expected in found(sheet(SheetKind.PEERS, [row]))


def test_duplicate_peer_after_normalisation() -> None:
    assert found(sheet(SheetKind.PEERS, [peers_row("CHUBB", [*FIVE, "CARRIER A S.A."])])) == [
        CheckId.DUPLICATE_PEER
    ]


def test_self_peer_flagged_and_not_counted() -> None:
    parsed = sheet(SheetKind.PEERS, [peers_row("CHUBB", [*FIVE[:4], "Chubb Seguros"])])

    assert set(found(parsed)) == {CheckId.SELF_PEER, CheckId.TOO_FEW_PEERS}


def test_excluded_peer_does_not_count() -> None:
    parsed = sheet(SheetKind.PEERS, [peers_row("CHUBB", FIVE)], styles={"G8": Style(fill=RED)})

    assert found(parsed) == [CheckId.TOO_FEW_PEERS]


def test_duplicate_carrier_across_rows() -> None:
    issues = run_checks(
        sheet(SheetKind.PEERS, [peers_row("CHUBB", FIVE), peers_row("Chubb Limited", FIVE)]),
        SETTINGS,
    )

    assert [(issue.check, issue.row) for issue in issues] == [(CheckId.DUPLICATE_CARRIER, 9)]


def test_lob_with_every_practice_excluded_has_no_practice() -> None:
    styles = {f"{letter}8": Style(font=RED) for letter in "EFGH"}

    assert found(sheet(SheetKind.LOB, [lob_row("CHUBB", ["X", "X", "X", "X"])], styles)) == [
        CheckId.NO_PRACTICE
    ]


def test_ce_cm_alone_counts_as_a_practice() -> None:
    assert found(sheet(SheetKind.LOB, [lob_row("CHUBB", ["X", None, None, None])])) == []


def test_unexpected_practice_value_is_a_warning() -> None:
    issues = run_checks(sheet(SheetKind.LOB, [lob_row("CHUBB", ["Yes"])]), SETTINGS)

    assert [(i.check, i.severity) for i in issues] == [
        (CheckId.INVALID_PRACTICE_VALUE, Severity.WARNING)
    ]


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([panel_row(1, "")], [CheckId.EMAIL_EMPTY]),
        ([panel_row(1, "not-an-email")], [CheckId.EMAIL_INVALID]),
        ([panel_row(1, "a@x.com", last="")], [CheckId.NAME_EMPTY]),
        ([panel_row(1, "a@x.com"), panel_row(1, "b@x.com")], [CheckId.DUPLICATE_EMPLOYEE_ID]),
        ([panel_row(1, "a@x.com"), panel_row(2, "A@X.com")], [CheckId.DUPLICATE_EMAIL]),
    ],
)
def test_panel_checks(rows: list[tuple[CellValue, ...]], expected: list[CheckId]) -> None:
    assert found(sheet(SheetKind.PANEL, rows)) == expected


def test_country_mismatch_warns_once_per_distinct_value() -> None:
    lob = sheet(
        SheetKind.LOB,
        [
            ("LAC", "Argentine", "CHUBB", "X", "X"),
            ("LAC", "Argentine", "AIG", "X", "X"),
            ("LAC", "Argentina", "AXA", "X", "X"),
        ],
    )

    assert [(i.row, i.value) for i in country_mismatch([lob], "Argentina")] == [(8, "Argentine")]
