from asim_forge.suggestions import suggest_schema


def test_suggests_authentication_from_explicit_activity() -> None:
    suggestion = suggest_schema("User <VAR:TEXT> login failed from <VAR:IPV4>")

    assert suggestion.schema_name == "Authentication"
    assert suggestion.confidence > 0
    assert "login" in suggestion.ranked_scores[0].evidence


def test_returns_no_fit_without_evidence() -> None:
    suggestion = suggest_schema("temperature is <VAR:NUMBER>")

    assert suggestion.schema_name == "NoFit"
    assert suggestion.confidence == 0
