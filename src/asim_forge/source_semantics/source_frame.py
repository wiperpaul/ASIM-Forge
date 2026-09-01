"""A versioned facet vocabulary for describing source events in source terms.

Free-text roles are scored by exact match, so `network.source.address` and
`network.src.addr` register as a disagreement and vocabulary growth reads as
approach regression. Decomposing a role into facets lets a near miss on one facet
be reported as a near miss rather than a total failure, and keeps the source
description independent of ASIM so a catalogue revision cannot erase it.

Facets are deliberately coarse. This is a registry to be extended by explicit
revision, not a general ontology.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import Field, model_validator

from ..models import StrictModel

REGISTRY_REVISION = "source-frame.v1"

Domain = Literal[
    "network",
    "identity",
    "process",
    "file",
    "application",
    "resource",
    "event",
    "other",
]
Relation = Literal[
    "actor",
    "target",
    "source",
    "destination",
    "observer",
    "event",
    "other",
    "unknown",
]
Entity = Literal[
    "user",
    "endpoint",
    "process",
    "file",
    "application",
    "resource",
    "rule",
    "other",
]
Property = Literal[
    "id",
    "name",
    "address",
    "port",
    "time",
    "action",
    "result",
    "protocol",
    "other",
]

FACET_NAMES = ("domain", "relation", "entity", "property")

DOMAINS = frozenset(get_args(Domain))
RELATIONS = frozenset(get_args(Relation))
ENTITIES = frozenset(get_args(Entity))
PROPERTIES = frozenset(get_args(Property))

# Compact aliases accepted in role strings, kept small and auditable.
_TOKEN_ALIASES: dict[str, str] = {
    "addr": "address",
    "allowed": "result",
    "authentication": "identity",
    "connection": "event",
    "denied": "result",
    "dest": "destination",
    "dst": "destination",
    "dvc": "observer",
    "device": "observer",
    "failed": "result",
    "failure": "result",
    "host": "endpoint",
    "hostname": "endpoint",
    "ip": "address",
    "login": "event",
    "logon": "event",
    "machine": "endpoint",
    "outcome": "result",
    "reporter": "observer",
    "sensor": "observer",
    "src": "source",
    "status": "result",
    "subject": "target",
    "succeeded": "result",
    "success": "result",
    "timestamp": "time",
    "usr": "user",
    "identifier": "id",
}

# Entity implied by a domain when a role string does not name one.
_IMPLIED_ENTITY: dict[str, str] = {
    "network": "endpoint",
    "identity": "user",
    "process": "process",
    "file": "file",
    "application": "application",
    "resource": "resource",
}


class SourceFrameFacets(StrictModel):
    """A role decomposed into independently scorable facets."""

    domain: Domain = "other"
    relation: Relation = "unknown"
    entity: Entity = "other"
    property: Property = "other"
    # Set when the role text could not be resolved into the registered vocabulary.
    custom: str | None = None

    @model_validator(mode="after")
    def custom_requires_unresolved_facets(self) -> SourceFrameFacets:
        if self.custom is not None and not self.custom.strip():
            raise ValueError("custom role text cannot be blank")
        return self

    def facet_values(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in FACET_NAMES}


class SourceFrameRole(StrictModel):
    """A registered role: its canonical name, facets, and documentation."""

    name: str = Field(min_length=1)
    facets: SourceFrameFacets
    definition: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


def _role_tokens(role: str) -> list[str]:
    separators = str.maketrans({".": " ", "_": " ", "-": " ", ":": " ", "/": " "})
    return [token for token in role.translate(separators).casefold().split() if token]


def _parse_facets(role: str) -> SourceFrameFacets:
    """Decompose a role string using its tokens alone, without the registry."""
    tokens = [_TOKEN_ALIASES.get(token, token) for token in _role_tokens(role)]
    domain = next((token for token in tokens if token in DOMAINS), None)
    relation = next((token for token in tokens if token in RELATIONS), None)
    entity = next((token for token in tokens if token in ENTITIES), None)
    prop = next((token for token in tokens if token in PROPERTIES), None)

    # `network.source.address` names no entity; the domain implies one.
    if entity is None and domain is not None:
        entity = _IMPLIED_ENTITY.get(domain)
    # Escape hatch for roles the vocabulary cannot anchor at all, not for roles
    # that simply leave a facet unstated.
    unanchored = domain is None and relation is None
    return SourceFrameFacets.model_validate(
        {
            "domain": domain or "other",
            "relation": relation or "unknown",
            "entity": entity or "other",
            "property": prop or "other",
            "custom": role.strip() if unanchored else None,
        }
    )


def _role(name: str, definition: str, aliases: list[str] | None = None) -> SourceFrameRole:
    return SourceFrameRole(
        name=name,
        facets=_parse_facets(name),
        definition=definition,
        aliases=aliases or [],
    )


# Seeded from the roles the current approaches already emit, plus their nearest
# neighbours, so the first registry revision covers observed output rather than a
# speculative ontology.
REGISTERED_ROLES: tuple[SourceFrameRole, ...] = (
    _role(
        "network.source.address",
        "Address of the endpoint that initiated the observed connection.",
        ["network.src.addr", "source.ip"],
    ),
    _role(
        "network.source.port",
        "Port used by the initiating endpoint.",
        ["network.src.port"],
    ),
    _role(
        "network.destination.address",
        "Address of the endpoint that received the observed connection.",
        ["network.dst.addr", "destination.ip"],
    ),
    _role(
        "network.destination.port",
        "Port on the receiving endpoint.",
        ["network.dst.port"],
    ),
    _role(
        "network.observer.address",
        "Address of the device reporting the event rather than taking part in it.",
        ["network.device.address", "network.dvc.addr"],
    ),
    _role(
        "network.connection.action",
        "Action the reporting device applied to the connection, such as allow or deny.",
    ),
    _role(
        "network.connection.allowed",
        "Template constant stating the connection was permitted.",
    ),
    _role(
        "network.connection.denied",
        "Template constant stating the connection was blocked.",
    ),
    _role(
        "authentication.login.succeeded",
        "Template constant stating the authentication attempt succeeded.",
    ),
    _role(
        "authentication.login.failed",
        "Template constant stating the authentication attempt failed.",
    ),
    _role(
        "identity.actor.user",
        "Account that initiated the action.",
        ["identity.source.user"],
    ),
    _role(
        "identity.target.user",
        "Account the action was performed against or authenticated as.",
        ["identity.destination.user"],
    ),
    _role(
        "event.event.action",
        "Action described by the event, independent of its outcome.",
    ),
    _role(
        "event.event.result",
        "Outcome of the event, such as success or failure.",
        ["event.event.outcome"],
    ),
    _role(
        "event.event.time",
        "Time the event occurred at the source.",
    ),
)

_BY_NAME: dict[str, SourceFrameRole] = {}
for _registered in REGISTERED_ROLES:
    _BY_NAME[_registered.name.casefold()] = _registered
    for _alias in _registered.aliases:
        _BY_NAME[_alias.casefold()] = _registered


def registered_role(role: str) -> SourceFrameRole | None:
    """Resolve a role string through the registry, including its aliases."""
    return _BY_NAME.get(role.strip().casefold())


def canonical_role(role: str) -> str:
    """Return the registered name for a role, or the trimmed input when unknown."""
    registered = registered_role(role)
    return registered.name if registered is not None else role.strip()


def parse_role(role: str) -> SourceFrameFacets:
    """Decompose a role string into facets without requiring registration.

    Unregistered roles still yield whatever facets their tokens support, so a new
    role reduces facet accuracy gradually instead of scoring as a total miss.
    """
    registered = _BY_NAME.get(role.strip().casefold())
    if registered is not None:
        return registered.facets
    return _parse_facets(role)


def facet_keys(role: str) -> dict[str, str]:
    """Facet values for a role, keyed by facet name."""
    return parse_role(role).facet_values()
