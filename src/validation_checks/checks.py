"""Validation checks, kept in a registry.

To add a check, write a function and register it for a sheet:

    @check(SheetKind.PEERS)
    def my_rule(sheet: ParsedSheet, settings: Settings) -> Iterator[Issue]:
        ...

"Must not be blank" and "must be unique" checks are generated from the tables in config.py.
"""

import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import TypeAlias

from validation_checks.config import (
    EMAIL_PATTERN,
    PRACTICE_MARK,
    REQUIRED_FIELDS,
    UNIQUE_FIELDS,
    Settings,
)
from validation_checks.matching import normalise_name
from validation_checks.models import (
    CheckId,
    Entry,
    Field,
    Issue,
    ParsedSheet,
    Severity,
    SheetKind,
)

SheetCheck: TypeAlias = Callable[[ParsedSheet, Settings], Iterable[Issue]]

CHECKS: dict[SheetKind, list[SheetCheck]] = {kind: [] for kind in SheetKind}


def check(kind: SheetKind) -> Callable[[SheetCheck], SheetCheck]:
    """Decorator: register a check for one sheet kind."""

    def register(function: SheetCheck) -> SheetCheck:
        CHECKS[kind].append(function)
        return function

    return register


def run_checks(sheet: ParsedSheet, settings: Settings) -> list[Issue]:
    return [issue for rule in CHECKS[sheet.kind] for issue in rule(sheet, settings)]


# --------------------------------------------------------------------------- table-driven checks


def required(field: Field, check_id: CheckId) -> SheetCheck:
    def rule(sheet: ParsedSheet, _settings: Settings) -> Iterator[Issue]:
        if field not in sheet.active_fields:  # column absent or excluded
            return
        for record in sheet.records:
            if not record.get(field):
                yield sheet.issue(record.row, sheet.header(field), check_id, f"{field} is empty")

    return rule


def unique(field: Field, check_id: CheckId) -> SheetCheck:
    def rule(sheet: ParsedSheet, _settings: Settings) -> Iterator[Issue]:
        if field in sheet.active_fields:
            yield from _repeats(sheet, field, check_id, key=str.casefold)

    return rule


for _kind, _field, _check_id in REQUIRED_FIELDS:
    check(_kind)(required(_field, _check_id))
for _kind, _field, _check_id in UNIQUE_FIELDS:
    check(_kind)(unique(_field, _check_id))


def _repeats(
    sheet: ParsedSheet, field: Field, check_id: CheckId, *, key: Callable[[str], str]
) -> Iterator[Issue]:
    first_row: dict[str, int] = {}
    for record in sheet.records:
        if not (value := record.get(field)):
            continue
        if (first := first_row.setdefault(key(value), record.row)) != record.row:
            message = f"{field} '{value}' is also on row {first}"
            yield sheet.issue(record.row, sheet.header(field), check_id, message, value=value)


# --------------------------------------------------------------------------- Country Peers


@check(SheetKind.PEERS)
def too_few_peers(sheet: ParsedSheet, settings: Settings) -> Iterator[Issue]:
    """Distinct peers after name normalisation, not counting the carrier itself."""
    for record in sheet.records:
        own = normalise_name(record.get(Field.CARRIER_NAME), settings.stopwords)
        peers = {normalise_name(e.value, settings.stopwords) for e in record.entries} - {own}
        if len(peers) < settings.min_peers:
            message = f"Only {len(peers)} distinct peers; minimum is {settings.min_peers}"
            yield sheet.issue(
                record.row, "Peers", CheckId.TOO_FEW_PEERS, message, value=str(len(peers))
            )


@check(SheetKind.PEERS)
def duplicate_peer(sheet: ParsedSheet, settings: Settings) -> Iterator[Issue]:
    for record in sheet.records:
        groups: defaultdict[str, list[Entry]] = defaultdict(list)
        for entry in record.entries:
            groups[normalise_name(entry.value, settings.stopwords)].append(entry)
        for entries in (group for group in groups.values() if len(group) > 1):
            where = ", ".join(entry.column.header for entry in entries)
            message = f"Peer '{entries[0].value}' appears {len(entries)} times ({where})"
            yield sheet.issue(
                record.row,
                entries[1].column.header,
                CheckId.DUPLICATE_PEER,
                message,
                value=entries[1].value,
            )


@check(SheetKind.PEERS)
def self_peer(sheet: ParsedSheet, settings: Settings) -> Iterator[Issue]:
    for record in sheet.records:
        own = normalise_name(record.get(Field.CARRIER_NAME), settings.stopwords)
        for entry in record.entries:
            if own and normalise_name(entry.value, settings.stopwords) == own:
                yield sheet.issue(
                    record.row,
                    entry.column.header,
                    CheckId.SELF_PEER,
                    "Carrier is listed as its own peer",
                    value=entry.value,
                )


@check(SheetKind.PEERS)
def duplicate_carrier(sheet: ParsedSheet, settings: Settings) -> Iterator[Issue]:
    if Field.CARRIER_NAME in sheet.active_fields:
        yield from _repeats(
            sheet,
            Field.CARRIER_NAME,
            CheckId.DUPLICATE_CARRIER,
            key=lambda name: normalise_name(name, settings.stopwords),
        )


# --------------------------------------------------------------------------- LOB Mapping


@check(SheetKind.LOB)
def no_practice(sheet: ParsedSheet, _settings: Settings) -> Iterator[Issue]:
    for record in sheet.records:
        if not record.entries:
            message = "No (non-excluded) practice is marked for the carrier"
            yield sheet.issue(
                record.row,
                "Practices",
                CheckId.NO_PRACTICE,
                message,
                value=record.get(Field.CARRIER),
            )


@check(SheetKind.LOB)
def unexpected_practice_value(sheet: ParsedSheet, _settings: Settings) -> Iterator[Issue]:
    for record in sheet.records:
        for entry in record.entries:
            if entry.value.casefold() != PRACTICE_MARK:
                yield sheet.issue(
                    record.row,
                    entry.column.header,
                    CheckId.INVALID_PRACTICE_VALUE,
                    f"Practice cells should contain '{PRACTICE_MARK.upper()}'",
                    value=entry.value,
                    severity=Severity.WARNING,
                )


# --------------------------------------------------------------------------- User Panel


@check(SheetKind.PANEL)
def invalid_email(sheet: ParsedSheet, _settings: Settings) -> Iterator[Issue]:
    if Field.EMAIL not in sheet.active_fields:
        return
    for record in sheet.records:
        email = record.get(Field.EMAIL)
        if email and not EMAIL_PATTERN.match(email):
            yield sheet.issue(
                record.row,
                sheet.header(Field.EMAIL),
                CheckId.EMAIL_INVALID,
                "Email is not a valid address",
                value=email,
            )


# --------------------------------------------------------------------------- across sheets


def country_mismatch(sheets: Sequence[ParsedSheet], file_country: str) -> list[Issue]:
    """Warn once per distinct Country value that differs from the country in the file name."""
    expected = _fold(file_country)
    issues: list[Issue] = []
    for sheet in sheets:
        if not expected or Field.COUNTRY not in sheet.active_fields:
            continue
        seen = {expected}
        for record in sheet.records:
            value = record.get(Field.COUNTRY)
            if value and _fold(value) not in seen:
                seen.add(_fold(value))
                issues.append(
                    sheet.issue(
                        record.row,
                        sheet.header(Field.COUNTRY),
                        CheckId.COUNTRY_MISMATCH,
                        f"Country '{value}' differs from file country '{file_country}'",
                        value=value,
                        severity=Severity.WARNING,
                    )
                )
    return issues


def _fold(text: str) -> str:
    """Case-, accent- and spacing-insensitive form of a country name."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(plain.casefold().split())
