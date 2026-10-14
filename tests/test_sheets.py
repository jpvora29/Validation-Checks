"""Finding sheets, header rows and columns, and the exclusion scope table."""

from collections.abc import Mapping, Sequence

import pytest

from tests.factories import (
    LEGEND_ROWS,
    LEGEND_STYLES,
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
from validation_checks.config import SHEET_SPECS
from validation_checks.models import (
    CellValue,
    CheckId,
    ExclusionScope,
    Field,
    SheetKind,
    SheetLayoutError,
    Style,
)
from validation_checks.sheets import SheetResult, detect_layout, find_sheet, parse_sheet

SPECS = {spec.kind: spec for spec in SHEET_SPECS}
HEADERS = {SheetKind.PEERS: PEERS_HEADER, SheetKind.LOB: LOB_HEADER, SheetKind.PANEL: PANEL_HEADER}
PEERS = ["Carrier A", "Carrier B", "Carrier C", "Carrier D", "Carrier E", "Carrier F"]


def headers_of(kind: SheetKind, header: Sequence[CellValue]) -> list[str]:
    layout = detect_layout(make_sheet([*LEGEND_ROWS, tuple(header)]), SPECS[kind])
    return [column.header for column in layout.entries]


def parse(
    kind: SheetKind,
    data: Sequence[Sequence[CellValue]],
    *,
    styles: Mapping[str, Style] | None = None,
    legend: Mapping[str, Style] = LEGEND_STYLES,
    hidden_rows: frozenset[int] = frozenset(),
) -> SheetResult:
    sheet = make_sheet(
        [*LEGEND_ROWS, HEADERS[kind], *data],
        styles={**legend, **(styles or {})},
        hidden_rows=hidden_rows,
    )
    return parse_sheet(sheet, SPECS[kind], SETTINGS)


# --------------------------------------------------------------------------- layout


def test_peer_columns_found_by_name() -> None:
    assert headers_of(SheetKind.PEERS, PEERS_HEADER) == [f"Peer {n}" for n in range(1, 7)]


def test_lob_practices_include_ce_cm() -> None:
    assert headers_of(SheetKind.LOB, LOB_HEADER) == ["CE/CM", "Claims", "Property", "Surety"]


def test_lob_practices_vary_by_file() -> None:
    header = ("Region", "Country", "Carrier", "ICA carrier", "Marine", "Aviation", "Cyber")

    assert headers_of(SheetKind.LOB, header) == ["Marine", "Aviation", "Cyber"]


def test_lob_without_ica_column_uses_columns_right_of_carrier() -> None:
    assert headers_of(SheetKind.LOB, ("Region", "Country", "Carrier", "Claims")) == ["Claims"]


@pytest.mark.parametrize(
    ("kind", "header", "message"),
    [
        (SheetKind.LOB, LOB_HEADER[:4], "No practice columns"),
        (SheetKind.PANEL, ("Email", "Country"), "Name"),
        (SheetKind.PEERS, ("Region", "Country"), "Header row not found"),
    ],
)
def test_layout_errors(kind: SheetKind, header: tuple[str, ...], message: str) -> None:
    with pytest.raises(SheetLayoutError, match=message):
        headers_of(kind, header)


def test_sheets_found_by_keyword_and_ambiguity_rejected() -> None:
    sheets = [make_sheet([], name=n) for n in ("1.Country Peers", "2. Country LOB MAPPING.")]
    assert find_sheet(sheets, SPECS[SheetKind.LOB]).name == "2. Country LOB MAPPING."

    with pytest.raises(SheetLayoutError, match="Several sheets"):
        find_sheet(
            [make_sheet([], name="Peers"), make_sheet([], name="Peers old")], SPECS[SheetKind.PEERS]
        )


# --------------------------------------------------------------------------- exclusion scope


def test_unmarked_sheet_keeps_everything() -> None:
    result = parse(SheetKind.PEERS, [peers_row("CHUBB", PEERS)])

    assert (result.exclusions, result.warnings) == ((), ())
    assert [entry.value for entry in result.sheet.records[0].entries] == PEERS


def test_red_identity_cell_excludes_whole_row() -> None:
    result = parse(
        SheetKind.PEERS,
        [peers_row("CHUBB", PEERS), peers_row("AIG", PEERS)],
        styles={"D9": Style(fill=RED)},
    )

    assert [record.row for record in result.sheet.records] == [8]
    assert [(e.row, e.scope, e.value) for e in result.exclusions] == [
        (9, ExclusionScope.ROW, "AIG")
    ]


def test_red_peer_cell_drops_only_that_peer() -> None:
    result = parse(SheetKind.PEERS, [peers_row("CHUBB", PEERS)], styles={"J8": Style(font=RED)})

    assert [entry.value for entry in result.sheet.records[0].entries] == [
        p for p in PEERS if p != "Carrier D"
    ]
    assert result.exclusions[0].scope is ExclusionScope.CELL


def test_struck_through_peer_is_dropped() -> None:
    result = parse(SheetKind.PEERS, [peers_row("CHUBB", PEERS)], styles={"G8": Style(strike=True)})

    assert result.exclusions[0].reason == "strikethrough"


def test_red_blank_identity_cell_still_excludes_row() -> None:
    result = parse(
        SheetKind.PEERS, [peers_row("CHUBB", PEERS, group="")], styles={"C8": Style(fill=RED)}
    )

    assert result.sheet.records == ()


def test_red_practice_is_not_counted() -> None:
    result = parse(
        SheetKind.LOB, [lob_row("CHUBB", ["X", "X", "X", "X"])], styles={"H8": Style(font=RED)}
    )

    assert [e.column.header for e in result.sheet.records[0].entries] == [
        "CE/CM",
        "Claims",
        "Property",
    ]


def test_any_red_cell_excludes_panel_employee() -> None:
    result = parse(
        SheetKind.PANEL, [panel_row(1, "a@x.com"), panel_row(2, "")], styles={"F9": Style(fill=RED)}
    )

    assert [record.row for record in result.sheet.records] == [8]


def test_red_header_excludes_column_and_its_field() -> None:
    result = parse(
        SheetKind.PEERS, [peers_row("CHUBB", PEERS, group="")], styles={"C7": Style(fill=RED)}
    )

    assert Field.CARRIER_GROUP not in result.sheet.active_fields
    assert result.exclusions[0].scope is ExclusionScope.COLUMN


def test_all_red_headers_are_treated_as_styling() -> None:
    styles = {f"{letter}7": Style(fill=RED) for letter in "ABCDEFGHIJKL"}

    result = parse(SheetKind.PEERS, [peers_row("CHUBB", PEERS)], styles=styles)

    assert result.exclusions == ()
    assert [w.check for w in result.warnings] == [CheckId.HEADER_ROW_MARKED]


def test_blank_rows_are_skipped() -> None:
    assert len(parse(SheetKind.PEERS, [peers_row("CHUBB", PEERS), (), ()]).sheet.records) == 1


def test_hidden_row_is_validated_with_warning() -> None:
    result = parse(SheetKind.PEERS, [peers_row("CHUBB", PEERS)], hidden_rows=frozenset({8}))

    assert len(result.sheet.records) == 1
    assert [w.check for w in result.warnings] == [CheckId.HIDDEN_ROW]


def test_legend_that_is_not_red_is_flagged() -> None:
    result = parse(SheetKind.PEERS, [peers_row("CHUBB", PEERS)], legend={})

    assert [w.check for w in result.warnings] == [CheckId.LEGEND_NOT_RED]
