"""Every constant and setting of the project, in one file.

* `Settings`: values you may want to change per run. Override any of them with an environment
  variable `VALIDATION_<NAME>` (e.g. `VALIDATION_MIN_PEERS=6`) or a CLI flag.
* The UPPER_CASE constants below: fixed business rules and file layouts.
"""

import re
from pathlib import Path
from typing import Final

from pydantic import Field as SettingField
from pydantic import PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict

from validation_checks.models import CheckId, Field, FileStatus, SheetKind, SheetSpec

# =========================================================================== tunable settings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VALIDATION_", frozen=True)

    # Folders and files
    input_dir: Path = Path("inputs")
    output_dir: Path = Path("output")
    model_path: Path = Path("sentence-transformers")  # model files, or one model folder inside
    alias_path: Path = Path("carrier_aliases.csv")

    # Validation
    min_peers: PositiveInt = 5

    # Carrier matching (scores are 0..1)
    fuzzy_threshold: float = SettingField(default=0.92, ge=0, le=1)
    semantic_threshold: float = SettingField(default=0.80, ge=0, le=1)
    semantic_margin: float = SettingField(default=0.05, ge=0, le=1)
    extra_stopwords: tuple[str, ...] = ()

    # What counts as "red": hue wraps through 0 degrees, so pinks (~330) and dark reds match,
    # while orange (~39) and magenta (300) do not. Lightness bounds drop near-black/white.
    red_hue_from: float = SettingField(default=320.0, ge=0, le=360)
    red_hue_to: float = SettingField(default=20.0, ge=0, le=360)
    red_min_saturation: float = SettingField(default=0.35, ge=0, le=1)
    red_min_lightness: float = SettingField(default=0.15, ge=0, le=1)
    red_max_lightness: float = SettingField(default=0.92, ge=0, le=1)

    @property
    def stopwords(self) -> frozenset[str]:
        return CARRIER_STOPWORDS | {word.casefold() for word in self.extra_stopwords}


# =========================================================================== input files

FILE_NAME_PATTERN: Final = re.compile(r"^(?P<country>.+?)_Carrier_Survey", re.IGNORECASE)
FILE_NAME_HINT: Final = "File name must look like '<Country>_Carrier_Survey_<Year>_....xlsx'"
EXCEL_SUFFIXES: Final = frozenset({".xlsx", ".xlsm"})
SKIPPED_FILE_PREFIXES: Final = ("~$", ".")  # Excel lock files and hidden files

# =========================================================================== sheet layouts

HEADER_SEARCH_ROWS: Final = 40  # the header row is looked for in the first N rows
LEGEND_EXCLUDE_TEXT: Final = "exclude"  # the legend cell above the header that should be red
PEER_COLUMN_PATTERN: Final = re.compile(r"^peer\s*\d+$", re.IGNORECASE)
NAME_FIELDS: Final = (Field.LEGAL_NAME, Field.FIRST_NAME, Field.LAST_NAME)

SHEET_SPECS: Final = (
    SheetSpec(
        kind=SheetKind.PEERS,
        name_pattern=r"peer",
        columns={
            Field.REGION: r"^region$",
            Field.COUNTRY: r"^country$",
            Field.CARRIER_GROUP: r"^carrier\s*group\b",
            Field.CARRIER_NAME: r"^carrier\s*name\b",
            Field.CARRIER_ENTITY: r"^carrier\s*entity\b",
            Field.ICA_CARRIER: r"^ica\s*carrier\b",
        },
        required=frozenset({Field.CARRIER_GROUP, Field.CARRIER_NAME}),
    ),
    SheetSpec(
        kind=SheetKind.LOB,
        name_pattern=r"\blob\b",
        columns={
            Field.REGION: r"^region$",
            Field.COUNTRY: r"^country$",
            Field.CARRIER: r"^carrier\b(?!\s*(group|entity)\b)",
            Field.ICA_CARRIER: r"^ica\s*carrier\b",
        },
        required=frozenset({Field.CARRIER}),
    ),
    SheetSpec(
        kind=SheetKind.PANEL,
        name_pattern=r"panel",
        columns={
            Field.EMPLOYEE_ID: r"^employee\s*id\b",
            Field.LEGAL_NAME: r"^(legal\s*)?name$",
            Field.FIRST_NAME: r"^first\s*name$",
            Field.LAST_NAME: r"^last\s*name$",
            Field.EMAIL: r"^(work\s*)?e-?mail\b",
            Field.COUNTRY: r"^country$",
        },
        required=frozenset({Field.EMAIL, Field.COUNTRY}),
    ),
)

# =========================================================================== validation rules

PRACTICE_MARK: Final = "x"  # LOB practice cells should contain X
EMAIL_PATTERN: Final = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Columns that must not be blank, and columns whose values must be unique, per sheet.
REQUIRED_FIELDS: Final = (
    (SheetKind.PEERS, Field.CARRIER_GROUP, CheckId.CARRIER_GROUP_EMPTY),
    (SheetKind.PEERS, Field.CARRIER_NAME, CheckId.CARRIER_NAME_EMPTY),
    (SheetKind.LOB, Field.CARRIER, CheckId.CARRIER_NAME_EMPTY),
    (SheetKind.PANEL, Field.EMAIL, CheckId.EMAIL_EMPTY),
    (SheetKind.PANEL, Field.COUNTRY, CheckId.COUNTRY_EMPTY),
    (SheetKind.PANEL, Field.LEGAL_NAME, CheckId.NAME_EMPTY),
    (SheetKind.PANEL, Field.FIRST_NAME, CheckId.NAME_EMPTY),
    (SheetKind.PANEL, Field.LAST_NAME, CheckId.NAME_EMPTY),
)
UNIQUE_FIELDS: Final = (
    (SheetKind.PANEL, Field.EMPLOYEE_ID, CheckId.DUPLICATE_EMPLOYEE_ID),
    (SheetKind.PANEL, Field.EMAIL, CheckId.DUPLICATE_EMAIL),
)

# =========================================================================== carrier names

# Legal forms and generic industry words ignored when comparing carrier names,
# so "Chubb Seguros Argentina S.A." and "CHUBB ARGENTINA" compare equal.
CARRIER_STOPWORDS: Final = frozenset(
    {
        "ag", "and", "assurance", "assurances", "bv", "cia", "co", "companhia", "compania",
        "compagnie", "company", "corp", "corporation", "de", "del", "do", "gmbh", "group",
        "grupo", "holding", "holdings", "inc", "incorporated", "insurance", "limited", "llc",
        "lp", "ltd", "ltda", "nv", "plc", "reaseguros", "reinsurance", "sa", "saa", "sab",
        "sac", "sas", "se", "seguro", "seguros", "spa", "srl", "the", "y",
    }
)  # fmt: skip
ALIAS_CSV_COLUMNS: Final = frozenset({"alias", "canonical"})
# Files only found at a sentence-transformers model root (config.json also sits in sub-modules).
SENTENCE_MODEL_MARKERS: Final = ("modules.json", "config_sentence_transformers.json")

# =========================================================================== output

RESULTS_FILE: Final = "validation_results.xlsx"  # the latest run only
HISTORY_FILE: Final = "validation_history.xlsx"  # every earlier run, appended
LOG_FILE: Final = "validation.log"  # appended, one separator line per run
LOG_FILE_FORMAT: Final = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
STATUS_COLOURS: Final = {
    FileStatus.OK: "green",
    FileStatus.ISSUES: "yellow",
    FileStatus.FAILED: "red",
}
# Issues lists EVERYTHING to fix (checks, LOB mismatches, file/sheet problems);
# LOB Matching and Exclusions are supporting detail. "Run At" tells runs apart in the history.
REPORT_COLUMNS: Final = {
    "Summary": ("Run At", "File", "Country", "Status", "Errors", "Warnings", "Exclusions",
                "LOB To Review"),
    "Issues": ("Run At", "File", "Country", "Sheet", "Excel Row", "Column", "Severity", "Check",
               "Message", "Value"),
    "LOB Matching": ("Run At", "File", "Country", "Direction", "Name", "Best Candidate",
                     "Method", "Score", "Status", "Source Cells"),
    "Exclusions": ("Run At", "File", "Country", "Sheet", "Excel Row", "Column", "Value", "Scope",
                   "Reason", "Colour"),
}  # fmt: skip
MAX_COLUMN_WIDTH: Final = 60

# =========================================================================== Excel format facts

# Excel's theme-colour index order (light/dark are swapped relative to the theme XML).
THEME_SLOTS: Final = (
    "lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3", "accent4", "accent5",
    "accent6", "hlink", "folHlink",
)  # fmt: skip
THEME_NAMESPACE: Final = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
UNSET_RGB: Final = "00000000"  # openpyxl's placeholder for "no colour"
EXCEL_MAX_ROWS: Final = 1_048_576
EXCEL_MAX_COLUMNS: Final = 16_384
