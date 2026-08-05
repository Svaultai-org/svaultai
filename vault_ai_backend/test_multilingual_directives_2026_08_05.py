import pytest

import vault_multilingual as multilingual


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("Tagalog", "tl"), ("Filipino", "tl"), ("Spanish", "es"),
        ("French", "fr"), ("German", "de"), ("Arabic", "ar"),
        ("Hindi", "hi"), ("Chinese", "zh"), ("Japanese", "ja"),
        ("Korean", "ko"), ("Russian", "ru"), ("Portuguese", "pt"),
        ("Somali", "so"), ("Swahili", "sw"), ("Turkish", "tr"),
        ("Persian", "fa"), ("Urdu", "ur"), ("Thai", "th"),
        ("Vietnamese", "vi"), ("Indonesian", "id"),
    ],
)
def test_explicit_language_directives(name, code):
    assert multilingual.detect_requested_language(
        f"Please explain this in {name}"
    ) == code


@pytest.mark.parametrize(
    ("alias", "code"),
    [
        ("Farsi", "fa"), ("Mandarin", "zh"), ("Castilian", "es"),
        ("Brazilian Portuguese", "pt"), ("Bangla", "bn"),
    ],
)
def test_language_aliases(alias, code):
    assert multilingual.detect_requested_language(f"reply in {alias}") == code


def test_requested_language_beats_message_and_app_language_per_message():
    requested = multilingual.detect_requested_language(
        "Tell me about yourself in Filipino"
    )
    assert multilingual.resolve_reply_language(
        detected_from_message="en",
        requested_from_message=requested,
        app_locale_hint="fr",
    ) == "tl"
    # A later turn has no persistent mutation: resolution uses that turn only.
    assert multilingual.resolve_reply_language(
        detected_from_message="en",
        requested_from_message=None,
        app_locale_hint="fr",
    ) == "fr"


def test_current_non_english_message_beats_ambient_app_locale():
    assert multilingual.resolve_reply_language(
        detected_from_message="ar",
        app_locale_hint="en",
    ) == "ar"


@pytest.mark.parametrize(
    "message",
    [
        "show my passport in Spanish",
        "find my contract and answer in French",
        "tell me my ETH balance in Arabic",
        "show my saved login in German",
    ],
)
def test_language_extraction_does_not_rewrite_vault_request(message):
    before = message
    assert multilingual.detect_requested_language(message)
    assert message == before


@pytest.mark.parametrize(
    "message",
    ["use the value in the form", "reply in whichever is best", "in private"],
)
def test_ambiguous_or_unsupported_language_wording_falls_through(message):
    assert multilingual.detect_requested_language(message) is None

