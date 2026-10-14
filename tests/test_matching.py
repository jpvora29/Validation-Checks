from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from tests.factories import SETTINGS
from validation_checks.config import CARRIER_STOPWORDS
from validation_checks.matching import (
    SemanticScorer,
    build_tiers,
    load_aliases,
    match_carriers,
    match_issue,
    normalise_name,
)
from validation_checks.models import (
    CarrierName,
    CellPos,
    CheckId,
    ConfigError,
    Direction,
    MatchMethod,
    MatchResult,
    MatchStatus,
    Severity,
)
from validation_checks.semantic import EmbeddingScorer, find_model_dir

# --------------------------------------------------------------------------- normalising


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Chubb Seguros Argentina S.A.", "chubb argentina"),
        ("CHUBB LIMITED", "chubb"),
        ("Mapfre Compañía de Seguros", "mapfre"),
        ("Zurich (Argentina)", "zurich argentina"),
        ("AXA & XL", "axa xl"),
        ("O\N{RIGHT SINGLE QUOTATION MARK}Brien Insurance", "obrien"),
        ("Seguros S.A.", "seguros sa"),  # only stopwords: words are kept
    ],
)
def test_normalise_name(raw: str, expected: str) -> None:
    assert normalise_name(raw, CARRIER_STOPWORDS) == expected


# --------------------------------------------------------------------------- tiers


def names(*displays: str) -> list[CarrierName]:
    return [
        CarrierName(display=d, key=normalise_name(d, CARRIER_STOPWORDS), sources=(CellPos(1, 1),))
        for d in displays
    ]


class FakeScorer:
    def __init__(self, table: Mapping[tuple[str, str], float]) -> None:
        self._table = table

    def scores(self, query: str, candidates: Sequence[str]) -> list[float]:
        return [self._table.get((query, candidate), 0.0) for candidate in candidates]


def run(
    peers: list[CarrierName],
    lob: list[CarrierName],
    *,
    aliases: Mapping[str, str] | None = None,
    scorer: SemanticScorer | None = None,
) -> list[MatchResult]:
    return match_carriers(peers, lob, build_tiers(SETTINGS, aliases=aliases or {}, scorer=scorer))


def test_exact_matches_are_not_reported() -> None:
    assert run(names("Chubb Seguros S.A."), names("CHUBB")) == []


def test_alias_match_is_informational() -> None:
    (result,) = run(names("ACE"), names("CHUBB"), aliases={"ace": "chubb", "chubb": "chubb"})

    assert result.hit.status is MatchStatus.MATCHED_ALIAS
    assert not result.needs_review


def test_typo_is_a_fuzzy_match() -> None:
    (result,) = run(names("Zurich Argentnia"), names("Zurich Argentina"))

    assert result.hit.method is MatchMethod.FUZZY


@pytest.mark.parametrize(("peer", "lob"), [("Carrier A", "Carrier B"), ("Mapfre", "Mapfre Re")])
def test_different_carriers_are_not_fuzzy_matched(peer: str, lob: str) -> None:
    assert run(names(peer), names(lob))[0].hit.status is MatchStatus.NOT_FOUND


def test_semantic_hit_is_only_a_suggestion() -> None:
    scorer = FakeScorer({("galicia", "sancor"): 0.95, ("galicia", "allianz"): 0.10})

    forward = run(names("Galicia"), names("Sancor", "Allianz"), scorer=scorer)[0]

    assert forward.hit.status is MatchStatus.SUGGESTED
    assert forward.hit.candidate is not None
    assert forward.hit.candidate.display == "Sancor"


def test_semantic_hit_without_clear_margin_is_not_suggested() -> None:
    scorer = FakeScorer({("galicia", "sancor"): 0.90, ("galicia", "allianz"): 0.88})

    forward = run(names("Galicia"), names("Sancor", "Allianz"), scorer=scorer)[0]

    assert (forward.hit.status, forward.hit.method) == (MatchStatus.NOT_FOUND, MatchMethod.SEMANTIC)


def test_not_found_still_offers_closest_candidate() -> None:
    forward = run(names("Carrier A"), names("CHUBB", "Carrier X"))[0]

    assert forward.hit.candidate is not None
    assert (forward.hit.method, forward.hit.candidate.display) == (MatchMethod.FUZZY, "Carrier X")


def test_unused_lob_carrier_reported_in_reverse() -> None:
    results = run(names("CHUBB"), names("CHUBB", "Sancor"))

    assert [(r.direction, r.name.display) for r in results] == [(Direction.LOB_TO_PEER, "Sancor")]


def test_peer_missing_from_lob_is_an_error_issue() -> None:
    forward = run(names("Carrier A"), names("CHUBB"))[0]

    issue = match_issue(forward, peers_sheet="Peers", lob_sheet="LOB")

    assert issue is not None
    assert (issue.sheet, issue.check, issue.severity) == (
        "Peers",
        CheckId.CARRIER_NOT_IN_LOB,
        Severity.ERROR,
    )


def test_unused_lob_carrier_is_a_warning_issue() -> None:
    (reverse,) = run(names("CHUBB"), names("CHUBB", "Sancor"))

    issue = match_issue(reverse, peers_sheet="Peers", lob_sheet="LOB")

    assert issue is not None
    assert (issue.sheet, issue.check, issue.severity) == (
        "LOB",
        CheckId.LOB_CARRIER_UNUSED,
        Severity.WARNING,
    )


def test_confirmed_matches_are_not_issues() -> None:
    (result,) = run(names("Zurich Argentnia"), names("Zurich Argentina"))

    assert match_issue(result, peers_sheet="Peers", lob_sheet="LOB") is None


def test_empty_lob_reports_not_found_without_candidate() -> None:
    (result,) = run(names("CHUBB"), [])

    assert (result.hit.status, result.hit.candidate) == (MatchStatus.NOT_FOUND, None)


# --------------------------------------------------------------------------- aliases and model


def test_alias_csv_is_normalised(tmp_path: Path) -> None:
    path = tmp_path / "aliases.csv"
    path.write_text("﻿Alias , Canonical\nACE, CHUBB Ltd\n,\n", encoding="utf-8")

    assert load_aliases(path, CARRIER_STOPWORDS) == {"ace": "chubb", "chubb": "chubb"}


def test_missing_alias_file_means_no_aliases(tmp_path: Path) -> None:
    assert load_aliases(tmp_path / "absent.csv", CARRIER_STOPWORDS) == {}


def test_alias_csv_with_wrong_header_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "aliases.csv"
    path.write_text("from,to\nACE,CHUBB\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_aliases(path, CARRIER_STOPWORDS)


def test_embedding_scorer_uses_cosine_and_caches() -> None:
    calls: list[list[str]] = []

    def encode(texts: list[str]) -> list[list[float]]:
        calls.append(texts)
        vectors = {"a": [1.0, 0.0], "b": [1.0, 0.0], "c": [0.0, 1.0]}
        return [vectors[text] for text in texts]

    scorer = EmbeddingScorer(encode)

    assert scorer.scores("a", ["b", "c"]) == [1.0, 0.0]
    assert scorer.scores("a", ["c"]) == [0.0]
    assert calls == [["a", "b", "c"]]


@pytest.mark.parametrize("layout", ["files directly", "model folder inside", "empty"])
def test_find_model_dir(tmp_path: Path, layout: str) -> None:
    (tmp_path / "README.md").write_text("copy the model here", encoding="utf-8")
    model = tmp_path if layout == "files directly" else tmp_path / "paraphrase_MiniLM-L6-v2"
    if layout != "empty":
        model.mkdir(exist_ok=True)
        (model / "modules.json").write_text("[]", encoding="utf-8")

    assert find_model_dir(tmp_path) == (None if layout == "empty" else model)
