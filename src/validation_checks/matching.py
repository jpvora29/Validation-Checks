"""Match carrier names between the Peers and LOB sheets.

Each name goes through a chain of tiers; the first tier that returns a hit wins:

    exact (after normalising)  ->  alias CSV  ->  fuzzy string  ->  semantic (suggestion only)
    ->  closest candidate, reported as "Not found"
"""

import csv
import logging
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, TypeAlias

from rapidfuzz import fuzz, process

from validation_checks.config import ALIAS_CSV_COLUMNS, Settings
from validation_checks.models import (
    CarrierName,
    CellPos,
    CheckId,
    ConfigError,
    Direction,
    Field,
    Hit,
    Issue,
    MatchMethod,
    MatchResult,
    MatchStatus,
    ParsedSheet,
    Severity,
    SheetKind,
)

logger = logging.getLogger(__name__)

Tier: TypeAlias = Callable[[CarrierName, Sequence[CarrierName]], Hit | None]


class SemanticScorer(Protocol):
    """Similarity in [0, 1] between a query and each candidate."""

    def scores(self, query: str, candidates: Sequence[str]) -> list[float]: ...


# --------------------------------------------------------------------------- names


def normalise_name(name: str, stopwords: frozenset[str]) -> str:
    """ "Chubb Seguros Argentina S.A." -> "chubb argentina" (case, accents, punctuation and
    legal-form words removed). A name made only of stopwords keeps its words."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    plain = re.sub(
        "[.'\N{RIGHT SINGLE QUOTATION MARK}]", "", plain.casefold().replace("&", " and ")
    )
    words = re.sub(r"[^0-9a-z]+", " ", plain).split()
    return " ".join([word for word in words if word not in stopwords] or words)


def carrier_names(sheet: ParsedSheet, stopwords: frozenset[str]) -> list[CarrierName]:
    """Names a sheet contributes: Peers = each carrier and all its peers; LOB = each carrier."""
    field = Field.CARRIER_NAME if sheet.kind is SheetKind.PEERS else Field.CARRIER
    found: list[tuple[str, CellPos]] = []  # (name, cell)
    for record in sheet.records:
        if field in sheet.active_fields and record.get(field):
            found.append((record.get(field), CellPos(record.row, sheet.fields[field].index)))
        if sheet.kind is SheetKind.PEERS:
            found.extend((e.value, CellPos(e.row, e.column.index)) for e in record.entries)
    names: dict[str, CarrierName] = {}
    for text, cell in found:
        key = normalise_name(text, stopwords)
        previous = names.get(key)
        sources = (*previous.sources, cell) if previous else (cell,)
        names[key] = CarrierName(
            display=previous.display if previous else text, key=key, sources=sources
        )
    return list(names.values())


def load_aliases(path: Path, stopwords: frozenset[str]) -> dict[str, str]:
    """Alias CSV (`alias,canonical`) -> {normalised name: normalised canonical name}."""
    if not path.is_file():
        logger.info("No alias file at %s; alias matching has no entries", path)
        return {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    columns = {key.strip().casefold() for row in rows[:1] for key in row if key}
    if rows and not columns >= ALIAS_CSV_COLUMNS:
        raise ConfigError(f"{path} must have the header row: alias,canonical")
    aliases: dict[str, str] = {}
    for row in rows:
        cleaned = {
            key.strip().casefold(): (value or "").strip() for key, value in row.items() if key
        }
        if cleaned.get("alias") and cleaned.get("canonical"):
            canonical = normalise_name(cleaned["canonical"], stopwords)
            aliases[normalise_name(cleaned["alias"], stopwords)] = canonical
            aliases.setdefault(canonical, canonical)
    logger.info("Loaded %d carrier aliases from %s", len(aliases), path)
    return aliases


# --------------------------------------------------------------------------- tiers


def exact(query: CarrierName, candidates: Sequence[CarrierName]) -> Hit | None:
    match = next((c for c in candidates if c.key == query.key), None)
    return (
        Hit(candidate=match, method=MatchMethod.EXACT, status=MatchStatus.MATCHED, score=1.0)
        if match
        else None
    )


def alias(aliases: Mapping[str, str]) -> Tier:
    def tier(query: CarrierName, candidates: Sequence[CarrierName]) -> Hit | None:
        wanted = aliases.get(query.key, query.key)
        match = next((c for c in candidates if aliases.get(c.key, c.key) == wanted), None)
        if match is None:
            return None
        return Hit(
            candidate=match, method=MatchMethod.ALIAS, status=MatchStatus.MATCHED_ALIAS, score=1.0
        )

    return tier


def fuzzy(threshold: float) -> Tier:
    # token_sort_ratio ignores word order but, unlike token_set_ratio, does not score a
    # subset ("mapfre" vs "mapfre re") as a perfect match.
    def tier(query: CarrierName, candidates: Sequence[CarrierName]) -> Hit | None:
        best = _best_fuzzy(query, candidates)
        if best is None or best[1] < threshold:
            return None
        return Hit(
            candidate=best[0],
            method=MatchMethod.FUZZY,
            status=MatchStatus.MATCHED_FUZZY,
            score=best[1],
        )

    return tier


def semantic(scorer: SemanticScorer, *, threshold: float, margin: float) -> Tier:
    """Suggest the top candidate only if it is similar enough AND clearly ahead of the next."""

    def tier(query: CarrierName, candidates: Sequence[CarrierName]) -> Hit | None:
        if not candidates:
            return None
        scores = scorer.scores(query.key, [c.key for c in candidates])
        ranked = sorted(
            zip(scores, candidates, strict=True), key=lambda pair: pair[0], reverse=True
        )
        best_score, best = ranked[0]
        runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
        if best_score < threshold or best_score - runner_up < margin:
            return None
        return Hit(
            candidate=best,
            method=MatchMethod.SEMANTIC,
            status=MatchStatus.SUGGESTED,
            score=round(best_score, 3),
        )

    return tier


def closest(scorer: SemanticScorer | None) -> Tier:
    """Last tier: "Not found", with the nearest candidate so the reviewer has a lead."""

    def tier(query: CarrierName, candidates: Sequence[CarrierName]) -> Hit | None:
        if candidates and scorer is not None:
            scores = scorer.scores(query.key, [c.key for c in candidates])
            score, best = max(zip(scores, candidates, strict=True), key=lambda pair: pair[0])
            return Hit(
                candidate=best,
                method=MatchMethod.SEMANTIC,
                status=MatchStatus.NOT_FOUND,
                score=round(score, 3),
            )
        if (found := _best_fuzzy(query, candidates)) is not None:
            return Hit(
                candidate=found[0],
                method=MatchMethod.FUZZY,
                status=MatchStatus.NOT_FOUND,
                score=found[1],
            )
        return Hit(
            candidate=None, method=MatchMethod.NONE, status=MatchStatus.NOT_FOUND, score=None
        )

    return tier


def _best_fuzzy(
    query: CarrierName, candidates: Sequence[CarrierName]
) -> tuple[CarrierName, float] | None:
    best = process.extractOne(query.key, [c.key for c in candidates], scorer=fuzz.token_sort_ratio)
    return None if best is None else (candidates[best[2]], round(best[1] / 100, 3))


def build_tiers(
    settings: Settings, *, aliases: Mapping[str, str], scorer: SemanticScorer | None
) -> tuple[Tier, ...]:
    """Exact, alias and fuzzy confirm a match; semantic tiers only ever suggest one."""
    tiers: list[Tier] = [exact, alias(aliases), fuzzy(settings.fuzzy_threshold)]
    if scorer is not None:
        tiers.append(
            semantic(scorer, threshold=settings.semantic_threshold, margin=settings.semantic_margin)
        )
    tiers.append(closest(scorer))
    return tuple(tiers)


# --------------------------------------------------------------------------- matching


def match_carriers(
    peer_names: Iterable[CarrierName], lob_names: Iterable[CarrierName], tiers: Sequence[Tier]
) -> list[MatchResult]:
    """Peers -> LOB for every name, plus LOB -> Peers for LOB carriers nobody uses.
    Exact matches are dropped: only what a reviewer should see is returned."""
    peers, lob = list(peer_names), list(lob_names)
    results = [
        MatchResult(direction=Direction.PEER_TO_LOB, name=n, hit=_first_hit(n, lob, tiers))
        for n in peers
    ]
    for name in lob:
        reverse = MatchResult(
            direction=Direction.LOB_TO_PEER, name=name, hit=_first_hit(name, peers, tiers)
        )
        if reverse.needs_review:
            results.append(reverse)
    return [result for result in results if result.hit.method is not MatchMethod.EXACT]


def _first_hit(query: CarrierName, candidates: Sequence[CarrierName], tiers: Sequence[Tier]) -> Hit:
    for tier in tiers:
        if (hit := tier(query, candidates)) is not None:
            return hit
    return Hit(candidate=None, method=MatchMethod.NONE, status=MatchStatus.NOT_FOUND, score=None)


def match_issue(result: MatchResult, *, peers_sheet: str, lob_sheet: str) -> Issue | None:
    """Turn a match that needs a human into an Issue, so the Issues sheet lists everything."""
    if not result.needs_review:
        return None
    hit, name = result.hit, result.name.display
    candidate = hit.candidate.display if hit.candidate else ""
    closest = f" (closest: '{candidate}', score {hit.score})" if candidate else ""
    if hit.status is MatchStatus.SUGGESTED:
        check, severity = CheckId.POSSIBLE_CARRIER_MATCH, Severity.WARNING
        message = f"'{name}' may be the same carrier as '{candidate}'; please confirm"
    elif result.direction is Direction.PEER_TO_LOB:
        check, severity = CheckId.CARRIER_NOT_IN_LOB, Severity.ERROR
        message = f"'{name}' is not in the LOB sheet{closest}"
    else:
        check, severity = CheckId.LOB_CARRIER_UNUSED, Severity.WARNING
        message = f"LOB carrier '{name}' is not used on the Peers sheet{closest}"
    first = result.name.sources[0] if result.name.sources else None
    return Issue(
        sheet=peers_sheet if result.direction is Direction.PEER_TO_LOB else lob_sheet,
        row=first.row if first else None,
        column=", ".join(cell.coordinate for cell in result.name.sources),
        severity=severity,
        check=check,
        message=message,
        value=name,
    )
