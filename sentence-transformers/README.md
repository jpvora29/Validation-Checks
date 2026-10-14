# sentence-transformers model folder

This folder holds the embedding model used for semantic carrier-name suggestions (matching tier 4).
The model files are not committed to git; they're about 90 MB.

Copy the model from your work laptop here, in either of these layouts:

```
sentence-transformers/paraphrase_MiniLM-L6-v2/modules.json, config.json, ...   (model folder inside)
sentence-transformers/modules.json, config.json, ...                             (files directly here)
```

Then install the optional dependency:

```bash
uv sync --extra semantic
```

If this folder is empty or sentence-transformers isn't installed, the run still works. Semantic
suggestions are skipped with a warning, and exact, alias and fuzzy matching still run. To use a
model stored somewhere else, pass `--model-path` or set `VALIDATION_MODEL_PATH`.
