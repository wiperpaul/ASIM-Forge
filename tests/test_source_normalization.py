from asim_forge.source_normalization import (
    contains_source_phrase,
    source_tokens,
    structured_key_before,
)


def test_source_tokens_split_identifiers_and_normalize_security_actions() -> None:
    concepts = source_tokens(
        "userAuthenticate AuthActivityAuditEvent delete_report_execution src=192.0.2.1"
    )

    assert {
        "authentication",
        "audit",
        "delete",
        "report",
        "execution",
        "source",
    } <= concepts


def test_source_tokens_expand_common_cef_endpoint_keys() -> None:
    concepts = source_tokens("suser=alice duser=bob spt=12345 dpt=443")

    assert {"source", "destination", "user", "port"} <= concepts


def test_source_phrases_cross_identifier_styles_without_losing_order() -> None:
    assert contains_source_phrase("event=connectionAllowed", "connection allowed")
    assert not contains_source_phrase("allowed connection", "connection allowed")
    assert "authentication" in source_tokens("user signed in")


def test_structured_key_before_preserves_cef_and_json_field_context() -> None:
    cef = "CEF:0|Vendor|Product|event|src=<VAR:IPV4>;dst=<VAR:IPV4>"
    json = '{"sourceAddress":"<VAR:IPV4>"}'

    assert structured_key_before(cef, cef.index("<VAR:IPV4>")) == "src"
    assert structured_key_before(cef, cef.rindex("<VAR:IPV4>")) == "dst"
    assert structured_key_before(json, json.index("<VAR:IPV4>")) == "sourceAddress"
