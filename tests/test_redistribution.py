import json
from pathlib import Path

import pytest
from semantic_fixtures import EXAMPLE_CASES, build_catalog

from asim_forge.benchmarking import CorpusSource, load_corpus_manifests
from asim_forge.evaluation import load_semantic_mapping_cases
from asim_forge.redistribution import (
    REDISTRIBUTION_CLASSES,
    RedistributionClass,
    RedistributionError,
    permits_per_case_output,
    permits_publication,
    require_publishable,
    strictest,
)
from asim_forge.semantic_mapping.comparison import (
    compare_approaches,
    redact_report,
    write_comparison_report,
)

CORPORA = Path("evaluation/corpora")


def _report():
    case = load_semantic_mapping_cases(EXAMPLE_CASES)[0]
    return compare_approaches([case], build_catalog(), ["direct-lexical"], resamples=20)


def test_strictest_class_governs_a_combined_artefact() -> None:
    assert strictest(["content", "derived", "metrics"]) == "metrics"
    assert strictest(["content", "derived"]) == "derived"
    assert strictest(["content"]) == "content"
    # An empty set must fail closed rather than open.
    assert strictest([]) == "none"


@pytest.mark.parametrize("value", REDISTRIBUTION_CLASSES)
def test_permission_helpers_agree_with_the_ordering(value: RedistributionClass) -> None:
    if permits_per_case_output(value):
        assert permits_publication(value)


def test_only_content_and_derived_permit_per_case_output() -> None:
    assert permits_per_case_output("content")
    assert permits_per_case_output("derived")
    assert not permits_per_case_output("metrics")
    assert not permits_per_case_output("none")


def test_unpublishable_evidence_is_refused_with_its_reason() -> None:
    with pytest.raises(RedistributionError, match="classed 'none'"):
        require_publishable("none", "Corpus 'x'")


def test_metrics_class_still_publishes_aggregates() -> None:
    require_publishable("metrics", "Corpus 'x'")


def test_redaction_withholds_predictions_but_keeps_metrics() -> None:
    report = _report()
    assert report.approaches[0].predictions

    redacted = redact_report(report, "metrics")

    evaluation = redacted.approaches[0]
    assert evaluation.predictions == []
    assert evaluation.predictions_withheld == 1
    # The numbers survive; only the per-case evidence is withheld.
    assert evaluation.metrics == report.approaches[0].metrics
    assert evaluation.intervals == report.approaches[0].intervals
    assert any("withheld" in warning for warning in redacted.warnings)


def test_redaction_is_a_no_op_when_derived_output_is_permitted() -> None:
    report = _report()

    assert redact_report(report, "derived") is report
    assert redact_report(report, "content") is report


def test_written_report_omits_evidence_for_a_metrics_only_corpus(tmp_path: Path) -> None:
    """Prediction evidence quotes template text, so it is derived corpus content."""
    report = _report()
    output = tmp_path / "comparison.json"

    write_comparison_report(output, report, redistribution="metrics")

    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["approaches"][0]["predictions"] == []
    assert "local slot context" not in output.read_text(encoding="utf-8")
    assert written["approaches"][0]["metrics"]["field_micro_f1"] > 0


def test_written_report_keeps_evidence_when_the_licence_permits(tmp_path: Path) -> None:
    output = tmp_path / "comparison.json"

    write_comparison_report(output, _report(), redistribution="content")

    assert "local slot context" in output.read_text(encoding="utf-8")


def test_writing_an_unpublishable_report_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RedistributionError):
        write_comparison_report(tmp_path / "comparison.json", _report(), redistribution="none")


def test_corpus_source_defaults_to_the_conservative_class() -> None:
    source = CorpusSource(project="p", url="https://example.invalid", terms="unreviewed")

    # An undeclared corpus must not be assumed publishable in full.
    assert source.redistribution == "metrics"


def test_every_registered_corpus_declares_a_redistribution_class() -> None:
    manifests = load_corpus_manifests(CORPORA)

    assert manifests
    for path, manifest, _ in manifests:
        declared = json.loads(path.read_text(encoding="utf-8"))["source"]
        assert "redistribution" in declared, manifest.corpus_id
        assert manifest.source.redistribution in REDISTRIBUTION_CLASSES


def test_corpora_without_a_clear_licence_are_not_marked_publishable() -> None:
    """Matryoshka's code licence does not clearly cover its dataset download."""
    manifests = {manifest.corpus_id: manifest for _, manifest, _ in load_corpus_manifests(CORPORA)}

    assert manifests["matryoshka-sshd-1k"].source.redistribution == "metrics"
    assert manifests["loginject-ssh-benign-500"].source.redistribution == "content"
    assert manifests["loginject-ssh-benign-500"].source.attribution is not None
