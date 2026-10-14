# sentence-transformers model folder

Put the embedding model used for semantic carrier matching here. **When a model is present it is
used automatically.** The run log says `Semantic matching ON: using the model in ...`. The model
files are not committed to git; they're about 90 MB.

Copy the model in any of these layouts. It's found at any depth:

```
sentence-transformers/modules.json, config.json, ...                         (files directly here)
sentence-transformers/paraphrase_MiniLM-L6-v2/modules.json, ...             (model folder inside)
sentence-transformers/models--.../snapshots/<hash>/modules.json, ...        (copied Hugging Face cache)
```

`uv sync` already installs the sentence-transformers library, so nothing else needs installing.
The model is loaded from disk only and nothing is downloaded.

If the folder is empty, the run still works: the log says `Semantic matching OFF` and exact,
alias and fuzzy matching still run. If a model is present but can't be loaded, the log shows the
error and the run continues the same way. To use a model stored somewhere else, pass
`--model-path` or set `VALIDATION_MODEL_PATH`.
