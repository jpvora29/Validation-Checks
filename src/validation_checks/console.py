"""Run output: rich logging in the terminal, a plain-text log file, and a summary table."""

import logging
from collections.abc import Sequence
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from validation_checks.config import LOG_FILE_FORMAT, STATUS_COLOURS
from validation_checks.models import FileReport, Severity


def configure_logging(console: Console, *, log_file: Path, verbose: bool) -> None:
    """Project logs go to the terminal (rich) and to `log_file`; other libraries stay quiet."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(LOG_FILE_FORMAT))
    terminal = RichHandler(console=console, rich_tracebacks=True, show_path=verbose, markup=False)
    terminal.setFormatter(logging.Formatter("%(message)s"))  # rich adds time and level itself
    logging.basicConfig(level=logging.WARNING, handlers=[terminal, file_handler], force=True)
    logging.getLogger("validation_checks").setLevel(logging.DEBUG if verbose else logging.INFO)


def close_logging() -> None:
    """Release the log file (Windows keeps open files locked)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)


def print_summary(console: Console, reports: Sequence[FileReport]) -> None:
    table = Table(title=f"Validation summary ({len(reports)} file(s))", header_style="bold")
    table.add_column("File", overflow="fold")  # wrap long file names, never cut them
    table.add_column("Country")
    table.add_column("Status")
    for name in ("Errors", "Warnings", "Exclusions", "LOB to review", "File errors"):
        table.add_column(name, justify="right")
    for report in reports:
        table.add_row(
            report.file,
            report.country,
            f"[{STATUS_COLOURS[report.status]}]{report.status}[/]",
            str(report.count(Severity.ERROR)),
            str(report.count(Severity.WARNING)),
            str(len(report.exclusions)),
            str(report.review_count),
            str(len(report.file_errors)),
        )
    console.print(table)
