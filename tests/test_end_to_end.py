"""Whole runs through the real Excel reader, the shipped sample, and the CLI."""

from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from tests.factories import (
    SETTINGS,
    lob_row,
    panel_row,
    peers_row,
    red_font,
    save,
    solid,
    survey_workbook,
)
from validation_checks.config import Settings
from validation_checks.main import build_pipeline, main
from validation_checks.models import CheckId, ConfigError, ExclusionScope, FileReport
from validation_checks.pipeline import Pipeline
from validation_checks.report import write_report

SAMPLE = Path(__file__).parent.parent / "inputs" / "Argentina_Carrier_Survey_2027_Validation.xlsx"
PEERS = ["Carrier A", "Carrier B", "Carrier C", "Carrier D", "Carrier E", "Carrier F"]


@pytest.fixture
def pipeline(tmp_path: Path) -> Pipeline:
    return build_pipeline(SETTINGS.model_copy(update={"model_path": tmp_path / "no-model"}))


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample workbook not present")
def test_argentina_sample(pipeline: Pipeline) -> None:
    report = pipeline.run(SAMPLE)

    assert {(e.sheet, e.column, e.scope) for e in report.exclusions} == {
        ("1.Country Peers", "Peer 4", ExclusionScope.CELL),
        ("2. Country LOB MAPPING.", "Property", ExclusionScope.CELL),
        ("2. Country LOB MAPPING.", "Surety", ExclusionScope.CELL),
    }
    # Issues lists everything: the country spelling AND every peer missing from LOB.
    assert Counter(issue.check for issue in report.issues) == {
        CheckId.COUNTRY_MISMATCH: 1,
        CheckId.CARRIER_NOT_IN_LOB: 6,
    }
    missing = {i.value for i in report.issues if i.check is CheckId.CARRIER_NOT_IN_LOB}
    assert missing == {f"Carrier {letter}" for letter in "ABCEFG"}


def test_red_marks_flow_through_to_checks_and_matching(tmp_path: Path, pipeline: Pipeline) -> None:
    workbook = survey_workbook(
        peers=[peers_row("CHUBB", PEERS), peers_row("Excluded Co", ["Only one"])],
        lob=[lob_row("CHUBB", ["X", None, None, None]), *(lob_row(p, ["X"]) for p in PEERS)],
        panel=[panel_row(1, "a@x.com"), panel_row(2, "")],
    )
    workbook["1.Country Peers"]["D9"].fill = solid("FFC00000")  # dark red: row excluded
    workbook["1.Country Peers"]["G8"].font = red_font()  # Carrier A dropped, 5 peers remain
    workbook["3. User Panel"]["B9"].font = red_font()  # employee with blank email excluded

    report = pipeline.run(save(workbook, tmp_path / "Argentina_Carrier_Survey_2027.xlsx"))

    assert len(report.exclusions) == 3
    # Carrier A is now only in LOB, so the only issue is "LOB carrier not used in Peers".
    assert [(i.check, i.value) for i in report.issues] == [
        (CheckId.LOB_CARRIER_UNUSED, "Carrier A")
    ]


def run_rows(path: Path, sheet: str) -> list[datetime]:
    rows = load_workbook(path)[sheet].iter_rows(min_row=2, values_only=True)
    return [row[0] for row in rows if isinstance(row[0], datetime)]


def test_latest_results_and_history(tmp_path: Path) -> None:
    runs = [datetime(2026, 10, day, 9, 30) for day in (1, 2, 3)]
    for run in runs:
        write_report([FileReport.failed("bad.txt", "Not an Excel workbook")], tmp_path, run)

    latest, history = tmp_path / "validation_results.xlsx", tmp_path / "validation_history.xlsx"
    assert sorted(p.name for p in tmp_path.iterdir()) == [history.name, latest.name]
    assert load_workbook(latest).sheetnames == ["Summary", "Issues", "LOB Matching", "Exclusions"]
    assert run_rows(latest, "Issues") == runs[2:]  # latest run only
    assert run_rows(history, "Issues") == runs[:2]  # every earlier run, in order


def test_exclusions_sheet_shows_the_country(tmp_path: Path, pipeline: Pipeline) -> None:
    workbook = survey_workbook(peers=[peers_row("CHUBB", PEERS)], lob=[], panel=[])
    workbook["1.Country Peers"]["G8"].font = red_font()
    report = pipeline.run(save(workbook, tmp_path / "Chile_Carrier_Survey_2027.xlsx"))

    path = write_report([report], tmp_path / "out", datetime(2026, 10, 1))

    rows = list(load_workbook(path)["Exclusions"].iter_rows(values_only=True))
    assert rows[0][1:4] == ("File", "Country", "Sheet")
    assert rows[1][1:4] == ("Chile_Carrier_Survey_2027.xlsx", "Chile", "1.Country Peers")


def test_history_with_older_columns_is_realigned(tmp_path: Path) -> None:
    history = Workbook()
    old = history.worksheets[0]
    old.title = "Exclusions"
    old.append(
        ["Run At", "File", "Sheet", "Excel Row", "Column", "Value", "Scope", "Reason", "Colour"]
    )
    old.append([datetime(2026, 9, 1), "Old.xlsx", "1.Country Peers", 8, "Peer 1", "Carrier A",
                "Cell", "red fill", "FF0000"])  # fmt: skip
    history.save(tmp_path / "validation_history.xlsx")
    write_report(
        [FileReport.failed("a.xlsx", "x", country="Peru")], tmp_path, datetime(2026, 10, 1)
    )
    write_report([FileReport.failed("b.xlsx", "x")], tmp_path, datetime(2026, 10, 2))

    rows = list(
        load_workbook(tmp_path / "validation_history.xlsx")["Exclusions"].iter_rows(
            values_only=True
        )
    )

    assert rows[0][1:4] == ("File", "Country", "Sheet")
    assert rows[1][1:5] == ("Old.xlsx", None, "1.Country Peers", 8)  # old row, Country blank


def test_open_results_file_stops_before_anything_is_archived(tmp_path: Path) -> None:
    write_report([FileReport.failed("bad.txt", "x")], tmp_path, datetime(2026, 10, 1))
    latest = tmp_path / "validation_results.xlsx"
    latest.chmod(0o444)  # read-only: what Windows reports while Excel has the file open
    try:
        with pytest.raises(ConfigError, match="Close it and run again"):
            write_report([FileReport.failed("bad.txt", "x")], tmp_path, datetime(2026, 10, 2))
        assert not (tmp_path / "validation_history.xlsx").exists()
    finally:
        latest.chmod(0o644)


def test_cli_runs_every_input_file_and_logs(tmp_path: Path) -> None:
    inputs, output = tmp_path / "in", tmp_path / "out"
    inputs.mkdir()
    for country in ("Peru", "Chile", "Mexico"):
        workbook = survey_workbook(peers=[peers_row("CHUBB", PEERS)], lob=[], panel=[])
        save(workbook, inputs / f"{country}_Carrier_Survey_2027.xlsx")
    (inputs / "~$Peru_Carrier_Survey_2027.xlsx").write_bytes(b"lock file")
    (inputs / "notes.txt").write_text("not a survey", encoding="utf-8")
    args = ["--input", str(inputs), "--output", str(output), "--model-path", str(tmp_path / "m")]

    assert main(args) == 0
    assert main(args) == 0  # second run: one results file, one history file, one log

    assert sorted(p.name for p in output.iterdir()) == [
        "validation.log",
        "validation_history.xlsx",
        "validation_results.xlsx",
    ]
    summary = load_workbook(output / "validation_results.xlsx")["Summary"]
    assert sorted(str(row[1]) for row in summary.iter_rows(min_row=2, values_only=True)) == [
        "Chile_Carrier_Survey_2027.xlsx",
        "Mexico_Carrier_Survey_2027.xlsx",
        "Peru_Carrier_Survey_2027.xlsx",
        "notes.txt",
    ]
    log = (output / "validation.log").read_text(encoding="utf-8")
    assert log.count("===== Run started") == 2
    assert "notes.txt: Not an Excel workbook" in log


def test_cli_without_input_files_exits_with_2(tmp_path: Path) -> None:
    assert main(["--input", str(tmp_path / "nope"), "--output", str(tmp_path)]) == 2


def test_settings_defaults_point_at_project_folders() -> None:
    defaults = Settings()

    assert (defaults.input_dir, defaults.output_dir, defaults.model_path) == (
        Path("inputs"),
        Path("output"),
        Path("sentence-transformers"),
    )
