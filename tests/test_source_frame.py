import pytest
from semantic_fixtures import EXAMPLE_CASES, build_catalog

from asim_forge.evaluation import load_semantic_mapping_cases
from asim_forge.semantic_mapping.approaches.semantic_frame import SemanticFrameApproach
from asim_forge.semantic_mapping.comparison import compare_approaches
from asim_forge.semantic_mapping.context_views import (
    CONTEXT_VIEWS,
    VIEW_DESCRIPTIONS,
    ContextView,
    apply_context_view,
)
from asim_forge.semantic_mapping.contracts import MappingRequest, SourceFrameHint
from asim_forge.semantic_mapping.metrics import evaluate_predictions
from asim_forge.source_semantics import (
    FACET_NAMES,
    REGISTERED_ROLES,
    canonical_role,
    facet_keys,
    parse_role,
    registered_role,
)


def _case():
    return load_semantic_mapping_cases(EXAMPLE_CASES)[0]


def _request(view="full", frame_hint=None):
    case = _case()
    return MappingRequest(
        case_id=case.case_id,
        catalogue_revision=case.catalogue_revision,
        input=apply_context_view(case.input, view),
        frame_hint=frame_hint,
    )


def test_registered_roles_decompose_into_every_facet() -> None:
    for role in REGISTERED_ROLES:
        facets = role.facets
        assert facets.custom is None, role.name
        assert set(facets.facet_values()) == set(FACET_NAMES)


def test_aliases_resolve_to_one_canonical_role() -> None:
    assert canonical_role("network.src.addr") == "network.source.address"
    assert canonical_role("NETWORK.SRC.ADDR") == "network.source.address"
    assert registered_role("network.src.addr") is registered_role("network.source.address")


def test_domain_implies_an_entity_the_role_string_omits() -> None:
    facets = parse_role("network.source.address")

    assert facets.domain == "network"
    assert facets.relation == "source"
    # The role names no entity, so the domain supplies one.
    assert facets.entity == "endpoint"
    assert facets.property == "address"


def test_unregistered_role_still_yields_the_facets_its_tokens_support() -> None:
    facets = parse_role("network.destination.port.extra")

    assert facets.domain == "network"
    assert facets.relation == "destination"
    assert facets.property == "port"


def test_wholly_unknown_role_is_kept_as_custom_rather_than_discarded() -> None:
    facets = parse_role("vendor-specific-thing")

    assert facets.custom == "vendor-specific-thing"
    assert facets.relation == "unknown"


def test_canonical_role_passes_through_an_unknown_role() -> None:
    assert canonical_role("  vendor.custom.role  ") == "vendor.custom.role"


def test_facet_keys_cover_every_registered_facet_name() -> None:
    keys = facet_keys("identity.actor.user")

    assert set(keys) == set(FACET_NAMES)
    assert keys["relation"] == "actor"
    assert keys["entity"] == "user"


def test_near_miss_role_scores_partial_facet_credit() -> None:
    """A wrong relation should cost one facet, not the whole role."""
    case = _case()
    catalog = build_catalog()
    approach = SemanticFrameApproach()
    hint = [
        SourceFrameHint(
            source_kind=semantic.source_kind,
            locator=semantic.locator,
            # Swap source for destination: right domain and property, wrong relation.
            role=semantic.role.replace("source", "destination"),
        )
        for semantic in case.expected.source_semantics
    ]
    prediction = approach.predict(_request(frame_hint=hint), catalog)

    metrics = evaluate_predictions([case], [prediction])

    assert metrics.source_micro_f1 < 1.0
    assert metrics.source_domain_f1 > metrics.source_micro_f1
    assert metrics.source_property_f1 > metrics.source_micro_f1
    assert metrics.source_facet_micro_f1 > metrics.source_micro_f1


def test_source_frame_oracle_replaces_inferred_roles() -> None:
    catalog = build_catalog()
    hint = [
        SourceFrameHint(source_kind="slot", locator="p1", role="identity.actor.user"),
    ]

    prediction = SemanticFrameApproach().predict(_request(frame_hint=hint), catalog)

    roles = {
        semantic.locator: semantic.role
        for semantic in prediction.source_semantics
        if semantic.source_kind == "slot"
    }
    assert roles["p1"] == "identity.actor.user"
    evidence = next(
        semantic.evidence for semantic in prediction.source_semantics if semantic.locator == "p1"
    )
    assert any("oracle" in item for item in evidence)


def test_oracle_is_recorded_on_the_report_as_a_diagnostic() -> None:
    report = compare_approaches(
        [_case()],
        build_catalog(),
        ["semantic-frame"],
        oracle="schema-and-source-frame",
        resamples=20,
    )

    assert report.oracle == "schema-and-source-frame"
    assert any("not approach accuracy" in warning for warning in report.approaches[0].warnings)


@pytest.mark.parametrize("view", CONTEXT_VIEWS)
def test_every_context_view_is_described(view: ContextView) -> None:
    assert VIEW_DESCRIPTIONS[view]


def test_v0_physically_removes_template_labels_and_metadata() -> None:
    masked = apply_context_view(_case().input, "v0")

    assert "connection" not in masked.template.casefold()
    assert masked.source_metadata.vendor is None
    assert masked.source_metadata.product is None
    assert all(slot.label == "<withheld>" for slot in masked.parameter_slots)


def test_v1_keeps_the_local_window_but_drops_the_wider_template() -> None:
    original = _case().input
    masked = apply_context_view(original, "v1")

    assert masked.template != original.template
    # The window around a placeholder survives, so local lexical context remains.
    assert "from" in masked.template.casefold()
    assert all(slot.label != "<withheld>" for slot in masked.parameter_slots)
    assert masked.source_metadata.system == "withheld"


def test_v2_restores_the_template_but_still_withholds_metadata() -> None:
    original = _case().input
    masked = apply_context_view(original, "v2")

    assert masked.template == original.template
    assert masked.source_metadata.system == "withheld"


def test_v3_and_full_leave_the_input_untouched() -> None:
    original = _case().input

    assert apply_context_view(original, "v3") == original
    assert apply_context_view(original, "full") == original


def test_context_view_warning_marks_results_as_an_ablation() -> None:
    report = compare_approaches(
        [_case()],
        build_catalog(),
        ["direct-lexical"],
        context_view="v1",
        resamples=20,
    )

    assert report.context_view == "v1"
    assert any("ablation" in warning for warning in report.approaches[0].warnings)


def test_withholding_the_local_window_collapses_lexical_mapping() -> None:
    """V0 leaves no lexical evidence, so the approach must abstain rather than guess."""
    catalog = build_catalog()
    case = _case()

    starved = SemanticFrameApproach().predict(_request(view="v0"), catalog)
    windowed = SemanticFrameApproach().predict(_request(view="v1"), catalog)

    assert starved.disposition == "unresolved"
    assert evaluate_predictions([case], [windowed]).field_micro_f1 > 0
