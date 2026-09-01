import pytest
from semantic_fixtures import EXAMPLE_CASES, build_catalog

from asim_forge.controlled import perturb_case
from asim_forge.evaluation import load_semantic_mapping_cases
from asim_forge.models import AsimCatalogField, ParameterSlot
from asim_forge.semantic_mapping.approaches import APPROACH_NAMES, build_approach
from asim_forge.semantic_mapping.contracts import MappingRequest
from asim_forge.semantic_mapping.match_signals import (
    character_ngram_similarity,
    range_plausibility,
    type_affinity,
    type_compatibility,
    value_enumeration,
)
from asim_forge.semantic_mapping.metrics import evaluate_predictions
from asim_forge.semantic_mapping.profiling import profile_slot, profile_slots


def _slot(examples: list[str], slot_id: str = "p1") -> ParameterSlot:
    return ParameterSlot(
        slot_id=slot_id,
        label="VALUE",
        placeholder="<VAR:VALUE>",
        occurrence=1,
        examples=examples,
    )


def _field(name: str, kql_type: str = "string", logical: str | None = None, **kwargs):
    return AsimCatalogField(
        name=name,
        kql_type=kql_type,
        field_class="Recommended",
        schema_name="NetworkSession",
        logical_type=logical,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("examples", "expected"),
    [
        (["10.0.0.4", "192.0.2.10"], "ipv4"),
        (["2001:db8::1", "fe80::a"], "ipv6"),
        (["00:1a:2b:3c:4d:5e"], "mac"),
        (["443", "8443"], "integer"),
        (["1.5", "2.25"], "float"),
        (["2026-09-02T11:30:00Z"], "timestamp"),
        (["user@example.com"], "email"),
        (["https://example.com/a"], "url"),
        (["/var/log/syslog"], "path"),
        (["3f2504e0-4f89-11d3-9a0c-0305e82c3301"], "guid"),
        (["true", "false"], "boolean"),
        (["host.example.com"], "hostname"),
        (["some free text here"], "text"),
    ],
)
def test_profiler_detects_physical_types(examples: list[str], expected: str) -> None:
    assert profile_slot(_slot(examples)).physical_type == expected


def test_profiler_reports_no_information_without_examples() -> None:
    profile = profile_slot(_slot([]))

    assert profile.sample_count == 0
    assert profile.physical_type == "text"
    assert any("no example values" in note for note in profile.evidence)


def test_port_plausibility_requires_every_value_to_fit() -> None:
    assert profile_slot(_slot(["443", "8443"])).port_plausible
    # One value above the port ceiling disqualifies the whole slot.
    assert not profile_slot(_slot(["443", "162342"])).port_plausible


def test_profiler_summarises_shape_and_cardinality() -> None:
    profile = profile_slot(_slot(["443", "443", "8443"]))

    assert profile.sample_count == 3
    assert profile.distinct_count == 2
    assert profile.uniqueness == pytest.approx(2 / 3)
    assert profile.min_length == 3
    assert profile.max_length == 4
    assert profile.numeric_min == 443
    assert profile.numeric_max == 8443
    assert profile.has_digits and not profile.has_letters
    assert profile.character_entropy > 0


def test_profile_slots_is_keyed_by_slot_id() -> None:
    profiles = profile_slots([_slot(["443"], "p1"), _slot(["10.0.0.1"], "p2")])

    assert profiles["p1"].physical_type == "integer"
    assert profiles["p2"].physical_type == "ipv4"


def test_character_ngram_similarity_is_symmetric_and_bounded() -> None:
    assert character_ngram_similarity("source address", "source address") == 1.0
    assert character_ngram_similarity("source address", "") == 0.0
    left = character_ngram_similarity("source address", "SrcIpAddr")
    assert left == character_ngram_similarity("SrcIpAddr", "source address")
    assert 0.0 <= left <= 1.0


def test_type_compatibility_vetoes_an_impossible_target() -> None:
    ipv4 = profile_slot(_slot(["10.0.0.4"]))

    assert type_compatibility(ipv4, _field("SrcIpAddr")) == 1.0
    assert type_compatibility(ipv4, _field("EventCount", kql_type="int")) == 0.0


def test_text_profile_is_neutral_rather_than_a_veto() -> None:
    """An uninformative profile must not exclude every candidate."""
    text = profile_slot(_slot(["free form message"]))

    assert type_compatibility(text, _field("EventCount", kql_type="int")) == 0.5


def test_type_affinity_separates_fields_sharing_one_catalogue_type() -> None:
    ipv4 = profile_slot(_slot(["10.0.0.4"]))

    # Both are strings, so only the value shape can tell them apart.
    assert type_affinity(ipv4, _field("SrcIpAddr", logical="IP Address")) == 1.0
    assert type_affinity(ipv4, _field("Src")) == 0.0


def test_port_plausible_values_prefer_a_port_field() -> None:
    port = profile_slot(_slot(["443", "8443"]))

    assert type_affinity(port, _field("DstPortNumber", kql_type="int")) == 1.0
    assert type_affinity(port, _field("EventCount", kql_type="int")) == 0.0


def test_value_enumeration_matches_the_catalogue_allowed_values() -> None:
    field = _field("EventResult", allowed_values=["Success", "Failure"])

    assert value_enumeration(["Success"], field) == 1.0
    assert value_enumeration(["success", "nope"], field) == 0.5
    assert value_enumeration(["Success"], _field("SrcIpAddr")) == 0.0


def test_range_plausibility_rejects_out_of_range_port_values() -> None:
    wide = profile_slot(_slot(["443", "162342"]))
    port_field = _field("DstPortNumber", kql_type="int", logical="Port Number")

    assert range_plausibility(wide, port_field) == 0.0
    assert range_plausibility(profile_slot(_slot(["443"])), port_field) == 1.0
    # Non-port fields are not range constrained by this signal.
    assert range_plausibility(wide, _field("SrcIpAddr")) == 0.5


def test_matcher_ensemble_is_registered() -> None:
    assert "matcher-ensemble" in APPROACH_NAMES
    assert build_approach("matcher-ensemble").identity.name == "matcher-ensemble"


def _predict(case, approach_name: str):
    approach = build_approach(approach_name)
    return approach.predict(
        MappingRequest(
            case_id=case.case_id,
            catalogue_revision=case.catalogue_revision,
            input=case.input,
        ),
        build_catalog(),
    )


def test_matcher_ensemble_reports_each_signal_as_evidence() -> None:
    case = load_semantic_mapping_cases(EXAMPLE_CASES)[0]

    prediction = _predict(case, "matcher-ensemble")

    assert prediction.disposition == "mapped"
    evidence = " ".join(item for field in prediction.asim_fields for item in field.evidence)
    assert "profile:" in evidence
    assert "affinity" in evidence


def test_matcher_ensemble_survives_meaningless_slot_labels() -> None:
    """Value evidence should hold the mapping when the label carries none."""
    seed = load_semantic_mapping_cases(EXAMPLE_CASES)[0]
    variant = perturb_case(seed, "opaque-labels")
    assert variant is not None

    baseline = evaluate_predictions([seed], [_predict(seed, "matcher-ensemble")])
    opaque = evaluate_predictions([variant.case], [_predict(variant.case, "matcher-ensemble")])

    assert opaque.field_micro_f1 == baseline.field_micro_f1


def test_lexical_baseline_does_not_survive_meaningless_slot_labels() -> None:
    """Pins the gap the ensemble exists to close."""
    seed = load_semantic_mapping_cases(EXAMPLE_CASES)[0]
    variant = perturb_case(seed, "opaque-labels")
    assert variant is not None

    baseline = evaluate_predictions([seed], [_predict(seed, "direct-lexical")])
    opaque = evaluate_predictions([variant.case], [_predict(variant.case, "direct-lexical")])

    assert opaque.field_micro_f1 < baseline.field_micro_f1


def test_matcher_ensemble_reports_the_pool_it_cut_from() -> None:
    case = load_semantic_mapping_cases(EXAMPLE_CASES)[0]

    prediction = _predict(case, "matcher-ensemble")

    for field in prediction.asim_fields:
        assert field.candidate_pool_size is not None
        assert field.considered_field_count is not None
        assert field.candidate_pool_size <= field.considered_field_count
