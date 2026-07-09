

from __future__ import annotations

import logging

from vault_complete_search import (
    _is_valid_name_capture,
    extract_name_from_vision,
)


def test_name_visible_on_it_is():
    text = "This is a driver's license. The name visible on it is LOUIS IODATO."
    assert extract_name_from_vision(text) == "Louis Iodato"


def test_name_on_it_reads():
    text = "The name on it reads LOUIS IODATO."
    assert extract_name_from_vision(text) == "Louis Iodato"


def test_holder_label():
    text = "Holder: LOUIS IODATO."
    assert extract_name_from_vision(text) == "Louis Iodato"


def test_name_label():
    text = "Name: LOUIS IODATO"
    assert extract_name_from_vision(text) == "Louis Iodato"


def test_full_name_label():
    text = "Full Name: LOUIS IODATO"
    assert extract_name_from_vision(text) == "Louis Iodato"


def test_driver_label():
    text = "Driver: LOUIS IODATO"
    assert extract_name_from_vision(text) == "Louis Iodato"


def test_issued_to_phrase():
    text = "Issued to LOUIS IODATO"
    assert extract_name_from_vision(text) == "Louis Iodato"


def test_belongs_to_still_works():
    text = "The driver license belongs to Louis Lodato."
    assert extract_name_from_vision(text) == "Louis Lodato"


def test_straight_quoted_name():
    text = 'The name visible on it is "LOUIS IODATO."'
    assert extract_name_from_vision(text) == "Louis Iodato"


def test_smart_quoted_name():
    text = "The name on it reads “LOUIS IODATO”."
    assert extract_name_from_vision(text) == "Louis Iodato"


def test_markdown_bold_name():
    text = "The name visible on it is **LOUIS IODATO**."
    assert extract_name_from_vision(text) == "Louis Iodato"


def test_markdown_italic_name():
    text = "Holder: _LOUIS IODATO_"
    assert extract_name_from_vision(text) == "Louis Iodato"


def test_trailing_period_inside_quote_stripped():


    text = 'The name visible on it is "LOUIS IODATO."'
    out = extract_name_from_vision(text)
    assert out == "Louis Iodato"
    assert not (out or "").endswith(".")


def test_does_not_return_visible_on_it_is():
    text = "This is a driver's license. The name visible on it is LOUIS IODATO."
    name = extract_name_from_vision(text)
    assert name != "Visible On It Is"
    assert name != "Name Visible On It Is"
    assert name == "Louis Iodato"


def test_does_not_return_pure_connector_phrase():


    text = "I can see a driver's license but I cannot tell the name."
    assert extract_name_from_vision(text) is None


def test_random_prose_returns_none():
    text = "This page contains some scribbled marginalia."
    assert extract_name_from_vision(text) is None


def test_empty_or_none_returns_none():
    assert extract_name_from_vision(None) is None
    assert extract_name_from_vision("") is None
    assert extract_name_from_vision("   ") is None


def test_label_pattern_beats_sentence_pattern():


    text = (
        "Holder: LOUIS IODATO. The name visible on it is "
        "JANE DOE for context only."
    )
                                                               
    assert extract_name_from_vision(text) == "Louis Iodato"


def test_full_name_wins_over_plain_name():


    text = "Full Name: LOUIS IODATO\nName: JOE FOR DOB FIELD"
    assert extract_name_from_vision(text) == "Louis Iodato"


def test_titlecases_all_caps():
    assert extract_name_from_vision("Holder: LOUIS IODATO") == "Louis Iodato"


def test_preserves_apostrophe():


    out = extract_name_from_vision("Holder: MARY O'BRIEN")
    assert out is not None
                                                             
                                                         
    assert out.lower().startswith("mary ")
    assert "brien" in out.lower()


def test_validator_rejects_connector_capture():
    assert _is_valid_name_capture("Visible On It Is") is False
    assert _is_valid_name_capture("Name Visible") is False
    assert _is_valid_name_capture("Issued To") is False
    assert _is_valid_name_capture("Holder Driver") is False


def test_validator_accepts_real_name():
    assert _is_valid_name_capture("Louis Iodato") is True
    assert _is_valid_name_capture("Mary O'Brien") is True
    assert _is_valid_name_capture("LOUIS IODATO") is True


def test_validator_rejects_empty():
    assert _is_valid_name_capture("") is False
    assert _is_valid_name_capture("   ") is False


def test_does_not_log_extracted_name(caplog):
    caplog.set_level(logging.DEBUG, logger="vault_complete_search")
    name = extract_name_from_vision(
        "This is a driver's license. The name visible on it is LOUIS IODATO."
    )
    assert name == "Louis Iodato"                    
    joined = "\n".join(r.getMessage() for r in caplog.records)
                                                             
    assert "LOUIS IODATO" not in joined
    assert "Louis Iodato" not in joined
    assert "IODATO" not in joined
