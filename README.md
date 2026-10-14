# Validation Checks

This tool validates every country carrier-survey workbook in `inputs/` (Country Peers, LOB Mapping and User Panel sheets). Any cell with a **red** fill, a **red** font or **strikethrough** is treated as an exclusion. That includes every shade from pink to dark red, theme colours, and conditional formatting.

Each run writes two files to `output/`:
- `validation_results_<timestamp>.xlsx`, with the sheets **Summary**, **Issues**, **LOB Matching**, **Exclusions** and **File Errors**.
- `validation_run_<timestamp>.log`, the full run log (the same lines shown in the terminal).

The agreed behaviour is described in [docs/design-decisions.md](docs/design-decisions.md).

## Folders

| Folder | Purpose |
|---|---|
| `inputs/` | Survey files to validate (`<Country>_Carrier_Survey_<Year>_....xlsx`). Every file in it is processed, and one bad file never stops the others. |
| `output/` | Results workbooks and run logs. |
| `sentence-transformers/` | The embedding model used for semantic suggestions (see its README). It's optional. |

## Setup (Python 3.11.9)

```bash
uv python install 3.11.9
uv sync                       # core: exact, alias and fuzzy carrier matching
uv sync --extra semantic      # optional: adds sentence-transformers suggestions
```

## Run

```bash
uv run python -m validation_checks
```

Add `-v` for debug logging, which includes the header row, record count and exclusion count for each sheet.

| Setting | Flag | Environment variable | Default |
|---|---|---|---|
| Input folder | `--input` | `VALIDATION_INPUT_DIR` | `inputs` |
| Output folder | `--output` | `VALIDATION_OUTPUT_DIR` | `output` |
| Model folder | `--model-path` | `VALIDATION_MODEL_PATH` | `sentence-transformers` |
| Carrier alias CSV | `--aliases` | `VALIDATION_ALIAS_PATH` | `carrier_aliases.csv` |

Thresholds are also set through environment variables:
- `VALIDATION_MIN_PEERS`
- `VALIDATION_FUZZY_THRESHOLD`
- `VALIDATION_SEMANTIC_THRESHOLD`
- `VALIDATION_SEMANTIC_MARGIN`
- `VALIDATION_RED_*` (the hue, saturation and lightness bounds)
- `VALIDATION_EXTRA_STOPWORDS` (a JSON list)

**Aliases:** copy `carrier_aliases.example.csv` to `carrier_aliases.csv` and add one `alias,canonical` row per known rename, for example `ACE,CHUBB`.

## How the code is organised

All the code is in `src/validation_checks/`, one module per job. The whole run is a pipeline assembled with a builder in `main.py`:

```python
PipelineBuilder()
    .add_step(read_file(read_workbook))         # Excel -> raw sheets (colours resolved)
    .add_step(parse_sheets(settings))           # raw sheets -> records, exclusions applied
    .add_step(run_all_checks(settings))         # every registered check -> issues
    .add_step(match_lob_carriers(settings, tiers))  # Peers <-> LOB carrier matching
    .build()
```

| Module | What it does |
|---|---|
| `config.py` | **Every constant and setting**: paths, thresholds, red-colour bounds, header patterns, stopwords, output layout |
| `models.py` | All data types (enums, cells, records, issues, results) |
| `main.py` | Builds the pipeline and runs it over every file in `inputs/` |
| `pipeline.py` | `FileContext`, the four steps, `Pipeline` and `PipelineBuilder` |
| `excel_reader.py` | Reads Excel with openpyxl; resolves theme, indexed and RGB colours |
| `exclusions.py` | Is a cell red or struck through? Also evaluates conditional formatting (a registry of rule types) |
| `sheets.py` | Finds sheets, header rows and columns; applies the exclusion scope table |
| `checks.py` | The check **registry**: add a check with `@check(SheetKind.PEERS)` |
| `matching.py` | Carrier-name normalising and the tier chain (exact, alias, fuzzy, semantic, closest) |
| `semantic.py` | Optional sentence-transformers model from `sentence-transformers/` |
| `report.py` | `ReportBuilder` that writes the results workbook |
| `console.py` | Rich terminal logging, the log file, and the summary table |

To add a check, write one function in `checks.py`:

```python
@check(SheetKind.LOB)
def my_rule(sheet: ParsedSheet, settings: Settings) -> Iterator[Issue]:
    for record in sheet.records:
        if ...:
            yield sheet.issue(record.row, "Column", CheckId.MY_RULE, "What is wrong")
```

For "must not be blank" or "must be unique" rules, just add a row to `REQUIRED_FIELDS` or `UNIQUE_FIELDS` in `config.py`.

## Develop

```bash
uv run ruff format && uv run ruff check && uv run mypy src tests && uv run pytest
```

> The project sits inside OneDrive. If `uv sync` fails with *Access is denied* on a
> `validation_checks-*.dist-info` folder, OneDrive has turned it into a cloud placeholder.
> Delete that folder and run `uv sync` again, or mark `.venv` as *Always keep on this device*.
