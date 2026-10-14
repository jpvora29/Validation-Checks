"""Optional semantic matching with a local sentence-transformers model.

The model lives in the `sentence-transformers/` folder (its files directly, or one model folder
inside it). If the folder is empty or the library is not installed, `load_scorer` returns None
and matching simply runs without the semantic tier.
"""

import logging
import math
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypeAlias

from validation_checks.config import SENTENCE_MODEL_MARKERS
from validation_checks.matching import SemanticScorer

logger = logging.getLogger(__name__)

Encoder: TypeAlias = Callable[[list[str]], list[list[float]]]


class EmbeddingScorer:
    """Cosine similarity between embeddings; each name is encoded once per run."""

    def __init__(self, encode: Encoder) -> None:
        self._encode = encode
        self._vectors: dict[str, list[float]] = {}

    def scores(self, query: str, candidates: Sequence[str]) -> list[float]:
        missing = [
            text for text in dict.fromkeys([query, *candidates]) if text not in self._vectors
        ]
        if missing:
            self._vectors.update(zip(missing, self._encode(missing), strict=True))
        return [_cosine(self._vectors[query], self._vectors[text]) for text in candidates]


def _cosine(left: list[float], right: list[float]) -> float:
    norm = math.hypot(*left) * math.hypot(*right)
    return sum(a * b for a, b in zip(left, right, strict=True)) / norm if norm else 0.0


def find_model_dir(folder: Path) -> Path | None:
    """The model's root folder: the shallowest folder at or under `folder` holding a
    sentence-transformers marker file. Any depth works, e.g. a copied Hugging Face cache
    (`models--.../snapshots/<hash>/`)."""
    if not folder.is_dir():
        return None
    roots = sorted(
        {marker.parent for name in SENTENCE_MODEL_MARKERS for marker in folder.rglob(name)},
        key=lambda path: (len(path.parts), str(path)),
    )
    if len(roots) > 1:
        logger.warning("Several models under %s; using %s", folder.resolve(), roots[0])
    return roots[0] if roots else None


def load_scorer(folder: Path) -> SemanticScorer | None:
    """Load the model if one is present; otherwise matching runs without the semantic tier."""
    model_dir = find_model_dir(folder)
    if model_dir is None:
        logger.warning(
            "Semantic matching OFF: no sentence-transformers model found in %s", folder.resolve()
        )
        return None
    # Imported here, not at the top: importing torch takes seconds, and is wasted without a model.
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    try:
        model = SentenceTransformer(str(model_dir), local_files_only=True)  # never download
    except (OSError, ValueError, RuntimeError) as error:
        logger.error(
            "Semantic matching OFF: the model in %s could not be loaded: %s", model_dir, error
        )
        return None
    logger.info("Semantic matching ON: using the model in %s", model_dir.resolve())

    def encode(texts: list[str]) -> list[list[float]]:
        # Library boundary: convert the returned array to plain floats immediately.
        return [
            [float(number) for number in vector]
            for vector in model.encode(texts, show_progress_bar=False)
        ]

    return EmbeddingScorer(encode)
