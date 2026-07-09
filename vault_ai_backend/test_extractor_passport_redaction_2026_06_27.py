

from __future__ import annotations

import pytest

from extractor import redact_message


@pytest.mark.parametrize(
    "text",
    [
        "find me any passport in my vault",
        "show all my passports",
        "do I have a driver license?",
        "where is my driving license",
        "show me my national id",
        "look up my green card",
        "passport for John Doe",
        "I need my passports for travel",
        "is there a passport on file",
    ],
)
def test_document_query_passes_through_unchanged(text):


    assert redact_message(text) == text


def test_password_value_is_still_redacted():
    out = redact_message("my password is hunter2")
    assert "hunter2" not in out
    assert "password=***" in out


def test_pin_value_is_still_redacted():
    out = redact_message("my pin is 1234")
    assert "1234" not in out
    assert "pin=***" in out


def test_pass_short_form_still_redacted_with_separator():


    out = redact_message("pass: secretpass")
    assert "secretpass" not in out
    assert "password=***" in out


def test_username_value_still_redacted():
    out = redact_message("username: alice")
    assert "alice" not in out
    assert "username=***" in out


def test_email_value_still_redacted():
    out = redact_message("my email is foo@bar.com")
    assert "foo@bar.com" not in out


@pytest.mark.parametrize(
    "text",
    [
        "I passed the exam",
        "the passenger boarded",
        "passage of the bill",
        "passive income strategies",
        "passion project for the weekend",
                                
        "passport",
        "passports plural",
    ],
)
def test_pass_prefix_words_not_mangled(text):


    assert redact_message(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "I should pinch a penny",
        "the pine forest is beautiful",
        "she had a pink dress",
        "pinpoint the issue",
    ],
)
def test_pin_prefix_words_not_mangled(text):
    assert redact_message(text) == text
