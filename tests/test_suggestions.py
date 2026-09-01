from asim_forge.suggestions import suggest_schema


def test_suggests_authentication_from_explicit_activity() -> None:
    suggestion = suggest_schema("User <VAR:TEXT> login failed from <VAR:IPV4>")

    assert suggestion.schema_name == "Authentication"
    assert suggestion.confidence > 0
    assert "login" in suggestion.ranked_scores[0].evidence


def test_suggests_authentication_from_camel_case_cef_concepts() -> None:
    suggestion = suggest_schema(
        "CEF:0|CrowdStrike|FalconHost|1.0|userAuthenticate|userAuthenticate|1|"
        "cat=AuthActivityAuditEvent deviceProcessName=CrowdStrike Authentication"
    )

    assert suggestion.schema_name == "Authentication"
    assert suggestion.method == "source-concept-v1"
    assert suggestion.ranked_scores[0].evidence == ["auth", "authentication"]


def test_suggests_audit_from_identifier_actions_and_audit_context() -> None:
    suggestion = suggest_schema(
        "CEF:0|CrowdStrike|FalconHost|1.0|UserActivityAuditEvent|create_rule|1|"
        "cat=UserActivityAuditEvent"
    )

    assert suggestion.schema_name == "AuditEvent"
    assert suggestion.ranked_scores[0].evidence == ["audit", "create"]


def test_structural_network_terms_outweigh_an_embedded_policy_term() -> None:
    suggestion = suggest_schema(
        "CEF:0|Cisco|Firepower|6.0|POLICY VIOLATION|src=<VAR:IPV4>;dst=<VAR:IPV4>"
    )

    assert suggestion.schema_name == "NetworkSession"
    assert suggestion.ranked_scores[0].evidence == ["destination", "source"]


def test_abstains_when_multiple_schemas_have_equal_evidence() -> None:
    suggestion = suggest_schema("authentication audit")

    assert suggestion.schema_name == "NoFit"
    assert suggestion.confidence == 0
    assert suggestion.ranked_scores[0].score == suggestion.ranked_scores[1].score


def test_returns_no_fit_without_evidence() -> None:
    suggestion = suggest_schema("temperature is <VAR:NUMBER>")

    assert suggestion.schema_name == "NoFit"
    assert suggestion.confidence == 0
