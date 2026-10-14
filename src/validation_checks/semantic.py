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
    """The model folder itself, or the single model folder inside it."""
    if not folder.is_dir():
        return None
    candidates = [folder, *sorted(child for child in folder.iterdir() if child.is_dir())]
    return next(
        (path for path in candidates if any((path / m).is_file() for m in SENTENCE_MODEL_MARKERS)),
        None,
    )


def load_scorer(folder: Path) -> SemanticScorer | None:
    model_dir = find_model_dir(folder)
    if model_dir is None:
        logger.warning(
            "No sentence-transformers model in %s; semantic suggestions are disabled",
            folder.resolve(),
        )
        return None
    try:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415 - optional extra
    except ImportError:
        logger.warning("sentence-transformers is not installed (uv sync --extra semantic)")
        return None
    logger.info("Loading embedding model from %s", model_dir)
    model = SentenceTransformer(str(model_dir))

    def encode(texts: list[str]) -> list[list[float]]:
        # Untyped library boundary: convert the returned array to plain floats immediately.
        return [[float(number) for number in vector] for vector in model.encode(texts)]

    return EmbeddingScorer(encode)
