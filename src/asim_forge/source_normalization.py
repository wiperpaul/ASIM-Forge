"""Target-neutral lexical normalization for log-source semantics."""

from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*|[0-9]+")
_IDENTIFIER_PART = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+")
_STRUCTURED_KEY = re.compile(
    r"(?:^|[\s,;|{])['\"]?([A-Za-z][A-Za-z0-9_.-]*)['\"]?"
    r"\s*(?:=|:)\s*['\"]?$"
)

# These are source-vocabulary expansions, not ASIM field or schema names. They are
# deliberately small and auditable so every deterministic approach sees the same
# concepts without learning from evaluation labels.
_ALIASES: dict[str, tuple[str, ...]] = {
    "addr": ("address",),
    "dhost": ("destination", "host"),
    "dpt": ("destination", "port"),
    "dst": ("destination",),
    "duser": ("destination", "user"),
    "ipaddr": ("ip", "address"),
    "ipv4": ("ip", "address"),
    "ipv6": ("ip", "address"),
    "num": ("number",),
    "shost": ("source", "host"),
    "spt": ("source", "port"),
    "src": ("source",),
    "suser": ("source", "user"),
    "usr": ("user",),
}

_NORMAL_FORMS: dict[str, str] = {
    "auth": "authentication",
    "authenticate": "authentication",
    "authenticated": "authentication",
    "authenticates": "authentication",
    "authenticating": "authentication",
    "configure": "configuration",
    "configured": "configuration",
    "configuring": "configuration",
    "create": "create",
    "created": "create",
    "creating": "create",
    "creation": "create",
    "delete": "delete",
    "deleted": "delete",
    "deleting": "delete",
    "deletion": "delete",
    "disable": "disable",
    "disabled": "disable",
    "disabling": "disable",
    "enable": "enable",
    "enabled": "enable",
    "enabling": "enable",
    "modify": "modify",
    "modified": "modify",
    "modifying": "modify",
    "modification": "modify",
    "update": "update",
    "updated": "update",
    "updating": "update",
}

_CONTEXT_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "client": ("source",),
    "from": ("source",),
    "login": ("authentication", "logon"),
    "logout": ("authentication", "logoff"),
    "server": ("destination",),
    "to": ("destination",),
}
_PHRASE_EXPANSIONS: dict[tuple[str, ...], tuple[str, ...]] = {
    ("signed", "in"): ("authentication", "login", "signedin"),
}


def strip_leading_bom(text: str) -> str:
    """Remove a decoded UTF byte-order mark from the start of a record."""

    return text.removeprefix("\ufeff")


def source_tokens(text: str) -> set[str]:
    """Return normalized concepts from free text and structured identifiers."""

    tokens: set[str] = set()
    for word in _WORD.findall(strip_leading_bom(text)):
        tokens.add(word.casefold())
        tokens.update(part.casefold() for part in _IDENTIFIER_PART.findall(word))

    for token in tuple(tokens):
        tokens.update(_ALIASES.get(token, ()))
        normal = _NORMAL_FORMS.get(token)
        if normal is not None:
            tokens.add(normal)

    for token in tuple(tokens):
        tokens.update(_CONTEXT_EXPANSIONS.get(token, ()))
    ordered = _ordered_source_tokens(text)
    for phrase, expansions in _PHRASE_EXPANSIONS.items():
        if _contains_sequence(ordered, phrase):
            tokens.update(expansions)
    return tokens


def contains_source_phrase(text: str, phrase: str) -> bool:
    """Match a phrase across identifier conventions while preserving word order."""

    expected = _ordered_source_tokens(phrase)
    return bool(expected) and _contains_sequence(_ordered_source_tokens(text), expected)


def structured_key_before(text: str, offset: int) -> str | None:
    """Return the key directly owning a placeholder at ``offset``, when present."""

    match = _STRUCTURED_KEY.search(text[:offset])
    return match.group(1) if match is not None else None


def _ordered_source_tokens(text: str) -> tuple[str, ...]:
    ordered: list[str] = []
    for word in _WORD.findall(strip_leading_bom(text)):
        parts = _IDENTIFIER_PART.findall(word)
        values = parts if len(parts) > 1 else [word]
        for value in values:
            token = value.casefold()
            expanded = _ALIASES.get(token)
            if expanded is not None:
                ordered.extend(expanded)
            else:
                ordered.append(_NORMAL_FORMS.get(token, token))
    return tuple(ordered)


def _contains_sequence(values: tuple[str, ...], expected: tuple[str, ...]) -> bool:
    width = len(expected)
    return any(
        values[index : index + width] == expected for index in range(len(values) - width + 1)
    )
