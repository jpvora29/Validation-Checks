# Validation Checks: Refactor Design Decisions

Agreed during the design interview on 2026-10-14. Use this as the spec for the refactor.

## Scope
- Refactor the per-country-file pipeline (formerly `test.py`). Delete the legacy `Final_MF.xlsx` flow (`main.py`, `check_LOB.py`).
- One input file = one country. Sheets: Country Peers, Country LOB Mapping, User Panel.

## Exclusion detection
- A cell is **excluded** when its static fill or font colour is red, **or** its font is strikethrough.
- **Red** = colour resolved to RGB (theme + tint via workbook theme, indexed via legacy palette), then HSL with
  hue >= 320 deg or <= 20 deg (includes pink/hot pink, rejects orange and pure magenta), saturation >= ~0.35, lightness ~0.15–0.92.
  Thresholds live in config.
- **Rich text**: excluded only if every non-blank run is red/struck; partial formatting gives a Warning.
- **Conditional formatting**: read with openpyxl and evaluated in pure Python for `cellIs`, `containsText`, `beginsWith`,
  `endsWith`, `containsBlanks`, `duplicateValues`. Other rule types with a red or strike format get a "not evaluated, review" File Error/Warning.
- Colour reading sits behind a `CellFormatSource`-style Protocol so a COM adapter can be added later.
- Legend `EXCLUDE` cell: log a warning if it is not red by the rule above. Green / `INCLUDE` has no effect.
- Hidden rows/columns: not excluded, Warning logged. Cell comments: ignored.

## Exclusion scope
| Sheet | Marked cell | Effect |
|---|---|---|
| Peers | Identity column (Region, Country, Carrier Group, Carrier Name, Carrier Entity, ICA carrier) | Whole row excluded |
| Peers | `Peer N` cell | That peer dropped (min-count, duplicate and matching use the remaining peers) |
| LOB | Region / Country / Carrier / ICA carrier | Whole row excluded; not a match target |
| LOB | Practice cell | That practice not counted |
| User Panel | Any cell | Whole employee row excluded |
| Any | Header cell | Whole column excluded |

- Exclusion wins over validation: excluded rows raise no "empty" errors.
- Every exclusion is recorded in the **Exclusions** output sheet.

## Column resolution (never hardcoded)
- Header row: the first row containing the sheet's required identity headers (regex).
- LOB practices: every non-blank header right of `ICA carrier` (fallback: right of `Carrier`, excluding identity headers). Zero practices gives a File Error. CE/CM is a practice.
- Peer columns: headers matching `Peer\s*\d+`.
- Sheets matched by keyword (`peer`, `lob`, `panel`); a missing or ambiguous sheet gives a File Error.
- Fully blank rows and blank-header columns are skipped. Excel row numbers come from openpyxl directly.

## Carrier matching (Peers <-> LOB, within one file; Country column ignored)
Tiered pipeline; the first confident hit wins:
1. Normalised exact (casefold, strip accents/punctuation, collapse whitespace, drop configurable legal/industry suffixes): **Matched**
2. Alias CSV (`alias,canonical`, user-maintained, optional): **Matched (alias)**
3. rapidfuzz `token_set_ratio` >= 92: **Matched (fuzzy)**
4. Embeddings, cosine top-1 >= 0.80 and margin >= 0.05 over runner-up: **Suggested, needs review** (never auto-accepted)
5. Otherwise: **Not in LOB**, with the best candidate and its score

- Bidirectional: Peer→LOB (missing from LOB) and LOB→Peer (LOB carrier never used in Peers).
- Embeddings: sentence-transformers behind an `EmbeddingModel` Protocol. Model path comes from `--model-path` /
  `VALIDATION_MODEL_PATH`; if it is unset or missing, tier 4 is skipped with a warning. `[semantic]` optional extra.

## Checks (registry of pure functions)
- Peers: Carrier Group empty; Carrier Name empty; < N distinct peers (N=5, config); duplicate peer (normalised); carrier is its own peer; duplicate Carrier Name across rows.
- LOB: Carrier empty; no (non-excluded) practice marked; practice value other than `X`/`x` (Warning).
- User Panel: Email empty; Email invalid; Country empty; Name empty; duplicate Employee ID / Email.
- Cross-sheet: Country differs between sheets or from the filename (Warning).
- File: bad filename, missing/ambiguous sheet, header not found, unreadable file.

## Output
A fresh `Output File/validation_results_<YYYYMMDD_HHMMSS>.xlsx` per run (never appended). All sheets are always written, with autofilter and a frozen header:
- **Summary**: per file, country, status, counts
- **Issues**: `File, Country, Sheet, Excel Row, Column, Severity, Check, Message, Value`
- **LOB Matching**: `File, Country, Direction, Name, Best Candidate, Method, Score, Status, Source cells`
- **Exclusions**: `File, Sheet, Excel Row, Column, Value, Scope, Reason, Colour`
- **File Errors**

One bad file never stops the run.

## Toolchain
- Python 3.11.9 via uv (`.python-version`, `requires-python = ">=3.11.9,<3.12"`).
- No PEP 695 syntax / `typing.override` (3.12+): use `TypeAlias`, `TypeVar`, `typing_extensions.override`.
- No pandas. Runtime: openpyxl, pydantic, pydantic-settings, rapidfuzz; `[semantic]`: sentence-transformers, numpy.
- Dev: ruff, mypy --strict, pytest. Tests build fixture workbooks in code and also use the Argentina sample.
- Layout: `src/validation_checks/{domain,services,adapters,config.py,__main__.py}`; run with `python -m validation_checks`.
