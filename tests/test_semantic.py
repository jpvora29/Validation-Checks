"""Semantic matching with a real (tiny, offline-built) sentence-transformers model."""

import logging
from pathlib import Path

import pytest
import torch
from sentence_transformers import SentenceTransformer
from sentence_transformers.sentence_transformer.modules import StaticEmbedding
from tokenizers import Tokenizer, models, pre_tokenizers

from tests.factories import SETTINGS, lob_row, peers_row, save, survey_workbook
from validation_checks.main import build_pipeline
from validation_checks.models import CheckId
from validation_checks.semantic import find_model_dir, load_scorer

# Two-dimensional word vectors: "ace" points almost the same way as "chubb", "mapfre" opposite.
VECTORS = {
    "[UNK]": [0.0, 0.0],
    "[PAD]": [0.0, 0.0],
    "chubb": [1.0, 0.0],
    "ace": [0.9, 0.1],
    "zurich": [0.0, 1.0],
    "mapfre": [-1.0, 0.0],
}


def save_tiny_model(root: Path) -> Path:
    """Save a real sentence-transformers model without downloading anything."""
    tokenizer = Tokenizer(
        models.WordLevel(vocab={word: i for i, word in enumerate(VECTORS)}, unk_token="[UNK]")
    )
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    embedding = StaticEmbedding(tokenizer, embedding_weights=torch.tensor(list(VECTORS.values())))
    SentenceTransformer(modules=[embedding]).save(str(root))
    return root


@pytest.fixture(scope="module")
def model_folder(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("sentence-transformers")
    # Hugging Face cache layout: the model sits three levels down.
    save_tiny_model(folder / "models--org--tiny" / "snapshots" / "abc123")
    return folder


def test_model_is_found_at_any_depth(model_folder: Path) -> None:
    found = find_model_dir(model_folder)

    assert found is not None
    assert found.name == "abc123"


def test_model_is_used_when_present(model_folder: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="validation_checks")

    scorer = load_scorer(model_folder)

    assert scorer is not None
    assert "Semantic matching ON" in caplog.text
    assert [round(s, 2) for s in scorer.scores("chubb", ["ace", "zurich", "mapfre"])] == [
        0.99,
        0.0,
        -1.0,
    ]


def test_broken_model_is_reported_and_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "modules.json").write_text("not json", encoding="utf-8")

    assert load_scorer(tmp_path) is None
    assert "could not be loaded" in caplog.text


def test_pipeline_suggests_semantic_match(model_folder: Path, tmp_path: Path) -> None:
    peers = ["Zurich", "Mapfre", "Carrier C", "Carrier D", "Carrier E"]
    lob = ["CHUBB", *peers]
    workbook = survey_workbook(
        peers=[peers_row("ACE", peers)], lob=[lob_row(n, ["X"]) for n in lob], panel=[]
    )
    pipeline = build_pipeline(SETTINGS.model_copy(update={"model_path": model_folder}))

    report = pipeline.run(save(workbook, tmp_path / "Chile_Carrier_Survey_2027.xlsx"))

    # "ACE" is not in LOB by name, but the model sees it is CHUBB: suggested, never auto-matched.
    suggestions = [i for i in report.issues if i.check is CheckId.POSSIBLE_CARRIER_MATCH]
    assert [(i.value, i.message) for i in suggestions] == [
        ("ACE", "'ACE' may be the same carrier as 'CHUBB'; please confirm")
    ]
