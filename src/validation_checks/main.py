"""Entry point: build the pipeline from settings and run it over every file in the input folder.

uv run python -m validation_checks [--input DIR] [--output DIR] [--model-path DIR] [-v]
"""

import argparse
import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from rich.console import Console

from validation_checks.config import LOG_FILE, SKIPPED_FILE_PREFIXES, Settings
from validation_checks.console import close_logging, configure_logging, print_summary
from validation_checks.excel_reader import read_workbook
from validation_checks.matching import build_tiers, load_aliases
from validation_checks.models import ConfigError
from validation_checks.pipeline import (
    Pipeline,
    PipelineBuilder,
    match_lob_carriers,
    parse_sheets,
    read_file,
    run_all_checks,
)
from validation_checks.report import write_report
from validation_checks.semantic import load_scorer

logger = logging.getLogger("validation_checks")


def build_pipeline(settings: Settings) -> Pipeline:
    tiers = build_tiers(
        settings,
        aliases=load_aliases(settings.alias_path, settings.stopwords),
        scorer=load_scorer(settings.model_path),
    )
    return (
        PipelineBuilder()
        .add_step(read_file(read_workbook))  # Excel -> raw sheets (colours resolved)
        .add_step(parse_sheets(settings))  # raw sheets -> records, exclusions applied
        .add_step(run_all_checks(settings))  # registered checks -> issues
        .add_step(match_lob_carriers(settings, tiers))  # Peers <-> LOB carrier matching
        .build()
    )


def input_files(folder: Path) -> list[Path]:
    """Every file in the input folder except Excel lock files and hidden files."""
    return sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and not path.name.startswith(SKIPPED_FILE_PREFIXES)
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation_checks", description=__doc__)
    parser.add_argument("--input", dest="input_dir", type=Path, help="folder of survey files")
    parser.add_argument("--output", dest="output_dir", type=Path, help="folder for results")
    parser.add_argument("--model-path", type=Path, help="sentence-transformers model folder")
    parser.add_argument("--aliases", dest="alias_path", type=Path, help="alias CSV")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = vars(parser.parse_args(argv))
    verbose = bool(args.pop("verbose"))
    settings = Settings().model_copy(update={k: v for k, v in args.items() if v is not None})

    started = datetime.now()
    console = Console()
    log_file = settings.output_dir / LOG_FILE.format(started)
    configure_logging(console, log_file=log_file, verbose=verbose)
    try:
        if not settings.input_dir.is_dir() or not (paths := input_files(settings.input_dir)):
            logger.error("No input files found in %s", settings.input_dir.resolve())
            return 2
        pipeline = build_pipeline(settings)
        reports = pipeline.run_all(paths)
        output = write_report(reports, settings.output_dir, started)
        print_summary(console, reports)
        logger.info("Results written to %s", output.resolve())
        logger.info("Run log written to %s", log_file.resolve())
        return 0
    except ConfigError as error:
        logger.error("%s", error)
        return 2
    finally:
        close_logging()
