"""Pipeline steps with an in-memory fake reader: no Excel files involved."""

from collections.abc import Sequence
from pathlib import Path

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
from validation_checks.matching import build_tiers
from validation_checks.models import (
    CheckId,
    ConfigError,
    DataLoadError,
    FileStatus,
    RawSheet,
    Severity,
    SheetKind,
    Style,
)
from validation_checks.pipeline import (
    Pipeline,
    PipelineBuilder,
    match_lob_carriers,
    parse_sheets,
    read_file,
    run_all_checks,
)

GOOD = Path("Argentina_Carrier_Survey_2027_Validation.xlsx")
PEERS = ["Carrier A", "Carrier B", "Carrier C", "Carrier D", "Carrier E", "Carrier F"]


def three_sheets() -> list[RawSheet]:
    return [
        make_sheet(
            [*LEGEND_ROWS, PEERS_HEADER, peers_row("CHUBB", PEERS)],
            name="1.Country Peers",
            styles={**LEGEND_STYLES, "G8": Style(fill=RED)},
        ),
        make_sheet(  # every non-excluded carrier from Peers is in LOB, so nothing to report
            [*LEGEND_ROWS, LOB_HEADER, *(lob_row(name, ["X"]) for name in ["CHUBB", *PEERS[1:]])],
            name="2. LOB",
            styles=LEGEND_STYLES,
        ),
        make_sheet(
            [*LEGEND_ROWS, PANEL_HEADER, panel_row(1, "a@x.com")],
            name="3. User Panel",
            styles=LEGEND_STYLES,
        ),
    ]


def pipeline_reading(sheets: Sequence[RawSheet]) -> Pipeline:
    return (
        PipelineBuilder()
        .add_step(read_file(lambda _path: sheets))
        .add_step(parse_sheets(SETTINGS))
        .add_step(run_all_checks(SETTINGS))
        .add_step(match_lob_carriers(SETTINGS, build_tiers(SETTINGS, aliases={}, scorer=None)))
        .build()
    )


def test_full_pipeline_on_clean_file() -> None:
    report = pipeline_reading(three_sheets()).run(GOOD)

    assert report.country == "Argentina"
    assert report.sheets_validated == 3
    assert [e.value for e in report.exclusions] == ["Carrier A"]
    assert report.issues == ()


def test_country_with_underscores() -> None:
    report = pipeline_reading(three_sheets()).run(Path("United_Kingdom_Carrier_Survey_2027.xlsx"))

    assert report.country == "United Kingdom"


def test_missing_and_unknown_sheets_are_reported_as_issues() -> None:
    sheets = [*three_sheets()[:2], make_sheet([], name="Notes")]

    report = pipeline_reading(sheets).run(GOOD)

    problems = {(i.sheet, i.severity) for i in report.issues if i.check is CheckId.FILE_ERROR}
    assert problems == {(SheetKind.PANEL, Severity.ERROR), ("Notes", Severity.WARNING)}
    assert report.sheets_validated == 2


def test_carrier_missing_from_lob_is_an_issue() -> None:
    sheets = three_sheets()
    sheets[1] = make_sheet(
        [*LEGEND_ROWS, LOB_HEADER, lob_row("CHUBB", ["X"])], name="2. LOB", styles=LEGEND_STYLES
    )

    report = pipeline_reading(sheets).run(GOOD)

    missing = [i for i in report.issues if i.check is CheckId.CARRIER_NOT_IN_LOB]
    assert [(i.value, i.row, i.column, i.severity) for i in missing][:1] == [
        ("Carrier B", 8, "H8", Severity.ERROR)
    ]
    assert len(missing) == 5


@pytest.mark.parametrize(
    ("path", "message"), [("notes.txt", "Not an Excel"), ("random.xlsx", "Carrier_Survey")]
)
def test_unusable_files_fail_cleanly(path: str, message: str) -> None:
    report = pipeline_reading(three_sheets()).run(Path(path))

    assert report.status is FileStatus.FAILED
    assert message in report.issues[0].message


def test_read_failure_keeps_country() -> None:
    def broken(_path: Path) -> Sequence[RawSheet]:
        raise DataLoadError("corrupt")

    report = PipelineBuilder().add_step(read_file(broken)).build().run(GOOD)

    assert (report.status, report.country) == (FileStatus.FAILED, "Argentina")


def test_unexpected_error_in_one_file_does_not_stop_the_batch() -> None:
    def flaky(path: Path) -> Sequence[RawSheet]:
        if path.name.startswith("Chile"):
            raise RuntimeError("bug")
        return three_sheets()

    pipeline = PipelineBuilder().add_step(read_file(flaky)).add_step(parse_sheets(SETTINGS)).build()

    reports = pipeline.run_all([Path("Chile_Carrier_Survey_2027.xlsx"), GOOD])

    assert [r.status for r in reports] == [FileStatus.FAILED, FileStatus.OK]


def test_builder_needs_a_step() -> None:
    with pytest.raises(ConfigError):
        PipelineBuilder().build()
