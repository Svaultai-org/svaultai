"""Regression coverage for the 2026-08-15 production incident.

These tests intentionally exercise intent boundaries without touching a
database, provider, production account, or plaintext logging path.
"""

from durable_personal_memory import parse_personal_memory_intent


def _assert_mothers_name_memory(text: str) -> None:
    intent = parse_personal_memory_intent(text)

    assert intent is not None
    assert intent.action in {"save", "propose"}
    assert intent.subject == "mother"
    assert intent.relationship == "mother"
    assert intent.attribute == "name"
    assert intent.memory_type == "identity"
    assert intent.category == "family"
    assert intent.value == "Iodato"


def test_trailing_save_directive_is_a_structured_personal_fact() -> None:
    _assert_mothers_name_memory("my mother's name is Iodato, save it")


def test_leading_remember_directive_is_a_structured_personal_fact() -> None:
    _assert_mothers_name_memory("remember that my mother's name is Iodato")


def test_relationship_name_parser_handles_natural_variants() -> None:
    cases = {
        "please remember that my mum's full name is Iodato": "mother",
        "save that my dad's name is Rowan": "father",
        "my father's given name is Rowan, please save this": "father",
    }
    for text, expected_subject in cases.items():
        intent = parse_personal_memory_intent(text)
        assert intent is not None
        assert intent.subject == expected_subject
        assert intent.relationship == expected_subject
        assert intent.attribute == "name"
        assert intent.memory_type == "identity"


def test_explicit_credentials_never_enter_personal_memory_routing() -> None:
    for text in (
        "save my Facebook username john and password X",
        "create me a Facebook login",
        "generate a password for my Facebook login",
    ):
        assert parse_personal_memory_intent(text) is None
