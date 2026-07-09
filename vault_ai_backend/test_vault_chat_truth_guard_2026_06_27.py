

from __future__ import annotations

import json

import pytest

from vault_chat_truth_guard import (
    CORRECTION_NOT_FOUND,
    CORRECTION_NOT_FOUND_SEARCH_LIMITED,
    GUARDED_TOOL_NAMES,
    claims_passport_found,
    correction_grounded_from_hits,
    correction_passport_got_driver_license,
    extract_filenames_from_reply,
    has_credential_language,
    reply_mentions_password_not_passport,
    requested_document_type,
    says_not_found,
    truth_guard,
)


@pytest.mark.parametrize(
    "text,expected",
    [
                                                   
        ("I found these: aolreal_emails-unchecked.txt and swiftmail.txt",
         ["aolreal_emails-unchecked.txt", "swiftmail.txt"]),
        ("Reply mentions **drivers_license.jpg** in markdown bold.",
         ["drivers_license.jpg"]),
        ("- aolreal_emails-unchecked.txt\n- crypt.txt\n- swiftmail.txt",
         ["aolreal_emails-unchecked.txt", "crypt.txt", "swiftmail.txt"]),
                                           
        ("crypt.txt and crypt.txt again", ["crypt.txt"]),
                                 
        ("Your passport, driver's license, or ID card.", []),
        ("I checked the vault and found nothing matching.", []),
                                                    
        ("Section 4.2 covers usage.", []),
    ],
)
def test_extract_filenames_from_reply(text, expected):
    assert extract_filenames_from_reply(text) == expected


@pytest.mark.parametrize(
    "query,expected",
    [
        ("find me any passport in my vault", "passport"),
        ("show all my passports", "passport"),
        ("can you find my driver's license?", "driver_license"),
        ("driver license please", "driver_license"),
        ("DL number lookup", "driver_license"),
        ("show me all ID photos I have in my vault", "id_photo"),
        ("find my identity card", "id_photo"),
        ("find anything related to Wells Fargo", None),
        ("find files that contain login details or passwords", None),
        ("show me my tax return", None),
    ],
)
def test_requested_document_type(query, expected):
    assert requested_document_type(query) == expected


def test_says_not_found_positive():
    assert says_not_found(
        "I checked your vault and couldn't find files matching that.",
    )
    assert says_not_found("I didn't find any matching files.")
    assert says_not_found("No documents matching that query.")


def test_says_not_found_negative():
    assert not says_not_found("I found 3 matching files.")
    assert not says_not_found("Here are the matching files.")


def test_claims_passport_found_positive():
    assert claims_passport_found("I found your passport.")
    assert claims_passport_found("Here is your passport.")
    assert claims_passport_found("Your passport is in the vault.")


def test_claims_passport_found_negative():
    assert not claims_passport_found("I didn't find a passport.")
    assert not claims_passport_found(
        "I checked your vault and there is no passport."
    )


def test_has_credential_language_positive():
    assert has_credential_language(
        "I found one password in your vault for Union Bank."
    )
    assert has_credential_language("Saved your Chase login.")
    assert has_credential_language(
        "Your saved login for Wells Fargo is here."
    )


def test_has_credential_language_negative():
    assert not has_credential_language(
        "I found your driver's license: drivers_license.jpg."
    )
    assert not has_credential_language(
        "I checked your vault and couldn't find any ID photos."
    )


def test_reply_mentions_password_not_passport():
                                                             
                       
    assert reply_mentions_password_not_passport(
        "I found one password for Union Bank."
    )
                                                    
    assert not reply_mentions_password_not_passport(
        "I didn't find a passport. I found a password for Union Bank."
    )
                                                              
    assert not reply_mentions_password_not_passport(
        "I checked your vault and found a driver's license."
    )


_DL_HIT = {
    "file_id": "img-1",
    "file_name": "drivers_license.jpg",
    "file_kind": "image",
    "document_type": "driver_license",
    "matched_name": "Louis Iodato",
    "evidence_type": "extracted_text",
    "match_type": "exact_text",
    "confidence": 0.85,
}


def test_correction_passport_got_driver_license_uses_hit_name():
    text = correction_passport_got_driver_license([_DL_HIT])
                                                             
                                        
    assert text == (
        "I didn't find a passport. I did find a driver's "
        "license that may be related: drivers_license.jpg. "
        "The name on it reads Louis Iodato."
    )


def test_correction_passport_got_driver_license_falls_back_when_no_hits():
    assert (
        correction_passport_got_driver_license([])
        == CORRECTION_NOT_FOUND
    )


def test_correction_grounded_uses_hits_only():


    out = correction_grounded_from_hits(
        [_DL_HIT], requested_type="passport",
    )
    assert "drivers_license.jpg" in out
    assert "driver license" in out               
                                                    
    assert "aolreal_emails-unchecked.txt" not in out
    assert "swiftmail.txt" not in out


def test_correction_grounded_with_empty_hits_returns_not_found():
    assert (
        correction_grounded_from_hits([], requested_type="passport")
        == CORRECTION_NOT_FOUND
    )


def _result(*, hits, complete=True, doc_kind="id_photo", is_id_class=True):
    return json.dumps({
        "query": "...",
        "doc_kind": doc_kind,
        "is_id_class_search": is_id_class,
        "complete": complete,
        "hits": hits,
        "files_inspected": len(hits),
        "files_via_text": len(hits),
        "files_via_vision": 0,
        "coverage": {
            "total_relevant_files": max(len(hits), 1),
            "inspected": len(hits),
            "skipped_unrelated": 0,
            "vision_budget_used": 0,
            "vision_budget_max": 6,
            "is_complete": complete,
        },
    })


def test_guard_blocks_invented_filenames_with_empty_hits():


    reply = (
        "I found these:\n"
        "- aolreal_emails-unchecked.txt\n"
        "- swiftmail.txt\n"
        "- drivers_license.jpg"
    )
    corrected, slug = truth_guard(
        query="find files that contain login details or passwords",
        reply_text=reply,
        tool_name="find_in_vault",
        tool_result=_result(hits=[]),
    )
    assert slug == "empty_hits_invented_names"
    assert corrected == CORRECTION_NOT_FOUND


def test_guard_blocks_invented_filenames_when_hits_exist():


    reply = "I checked and the file is crypt.txt."
    corrected, slug = truth_guard(
        query="show me all ID photos",
        reply_text=reply,
        tool_name="find_in_vault",
        tool_result=_result(hits=[_DL_HIT]),
    )
    assert slug == "invented_filenames"
    assert "drivers_license.jpg" in corrected
    assert "crypt.txt" not in corrected


def test_guard_blocks_passport_password_confusion():


    reply = (
        "I found one password in your vault for Union Bank. "
        "Would you like to see the details?"
    )
    corrected, slug = truth_guard(
        query="find me any passport in my vault",
        reply_text=reply,
        tool_name="find_in_vault",
        tool_result=_result(hits=[_DL_HIT]),
    )
    assert slug == "password_passport_confusion"
                                                       
    assert "didn't find a passport" in corrected
    assert "drivers_license.jpg" in corrected
    assert "Union Bank" not in corrected


def test_guard_blocks_passport_confusion_with_empty_hits():


    reply = (
        "I found one password in your vault for Union Bank."
    )
    corrected, slug = truth_guard(
        query="find me any passport in my vault",
        reply_text=reply,
        tool_name="find_in_vault",
        tool_result=_result(hits=[]),
    )
    assert slug == "password_passport_confusion"
    assert corrected == CORRECTION_NOT_FOUND


def test_guard_blocks_credential_language_in_document_search():


    reply = (
        "Your saved login for Wells Fargo is in the vault. "
        "Would you like to see the details?"
    )
    corrected, slug = truth_guard(
        query="find anything related to Wells Fargo",
        reply_text=reply,
        tool_name="find_in_vault",
        tool_result=_result(hits=[]),
    )
    assert slug == "credential_language_in_doc_search"
    assert corrected == CORRECTION_NOT_FOUND


def test_guard_rewrites_passport_claim_when_hit_is_driver_license():


    reply = (
        "I found your passport: drivers_license.jpg. "
        "The name reads Louis Iodato."
    )
    corrected, slug = truth_guard(
        query="find me any passport in my vault",
        reply_text=reply,
        tool_name="find_in_vault",
        tool_result=_result(hits=[_DL_HIT]),
    )
                                                            
                                                           
    assert slug == "passport_mismatch_driver_license"
    assert "didn't find a passport" in corrected
    assert "driver's license" in corrected
    assert "drivers_license.jpg" in corrected


def test_guard_blocks_empty_hits_without_not_found_phrase():


    reply = "There are files here that might match your query."
    corrected, slug = truth_guard(
        query="find anything related to Wells Fargo",
        reply_text=reply,
        tool_name="find_in_vault",
        tool_result=_result(hits=[]),
    )
    assert slug == "empty_hits_no_not_found"
    assert corrected == CORRECTION_NOT_FOUND


def test_guard_allows_honest_empty_hits_reply():


    reply = "I checked your vault and couldn't find anything related to Wells Fargo."
    corrected, slug = truth_guard(
        query="find anything related to Wells Fargo",
        reply_text=reply,
        tool_name="find_in_vault",
        tool_result=_result(hits=[]),
    )
    assert slug is None
    assert corrected == reply


def test_guard_allows_correct_hit_reply():


    reply = (
        "I found your driver's license: drivers_license.jpg. "
        "The name on it reads Louis Iodato."
    )
    corrected, slug = truth_guard(
        query="show me all ID photos I have in my vault",
        reply_text=reply,
        tool_name="find_in_vault",
        tool_result=_result(hits=[_DL_HIT]),
    )
    assert slug is None
    assert corrected == reply


def test_guard_handles_search_limit_overflow():


    reply = "I couldn't find a matching file."
    corrected, slug = truth_guard(
        query="find me a passport",
        reply_text=reply,
        tool_name="find_in_vault",
        tool_result=_result(hits=[], complete=False),
    )
    assert slug == "search_limit_unannounced"
    assert corrected == CORRECTION_NOT_FOUND_SEARCH_LIMITED


def test_guard_accepts_search_limit_honest_reply():

    reply = (
        "The search ran past the budget for this turn. "
        "Ask again to keep looking."
    )
    corrected, slug = truth_guard(
        query="find me a passport",
        reply_text=reply,
        tool_name="find_in_vault",
        tool_result=_result(hits=[], complete=False),
    )
    assert slug is None
    assert corrected == reply


def test_guard_ignores_non_find_in_vault_tools():

    reply = "I've saved your Union Bank login."
    corrected, slug = truth_guard(
        query="save it now",
        reply_text=reply,
        tool_name="save_generated_credential_after_confirmation",
        tool_result='{"saved": true}',
    )
    assert slug is None
    assert corrected == reply


def test_guard_ignores_none_tool():


    reply = "I'm your vault. I can help you with many things."
    corrected, slug = truth_guard(
        query="What can you do?",
        reply_text=reply,
        tool_name=None,
        tool_result=None,
    )
    assert slug is None
    assert corrected == reply


def test_guard_ignores_tool_error_envelope():


    reply = "I couldn't run the search right now."
    corrected, slug = truth_guard(
        query="find me my driver's license",
        reply_text=reply,
        tool_name="find_in_vault",
        tool_result='{"error": "unavailable"}',
    )
    assert slug is None
    assert corrected == reply


def test_guard_handles_string_json_result():


    result_str = _result(hits=[])
    corrected, slug = truth_guard(
        query="find Wells Fargo",
        reply_text="There are files here matching your query.",
        tool_name="find_in_vault",
        tool_result=result_str,
    )
    assert slug == "empty_hits_no_not_found"


def test_guard_handles_dict_result():


    result_dict = json.loads(_result(hits=[]))
    corrected, slug = truth_guard(
        query="find Wells Fargo",
        reply_text="There are files here matching your query.",
        tool_name="find_in_vault",
        tool_result=result_dict,
    )
    assert slug == "empty_hits_no_not_found"


def test_correction_text_does_not_carry_filenames_from_reply():


    reply = (
        "I found these:\n"
        "- super_secret_passwords.txt\n"
        "- bank_routing_numbers.csv"
    )
    corrected, slug = truth_guard(
        query="find anything related to Wells Fargo",
        reply_text=reply,
        tool_name="find_in_vault",
        tool_result=_result(hits=[]),
    )
    assert "super_secret_passwords.txt" not in corrected
    assert "bank_routing_numbers.csv" not in corrected
    assert slug == "empty_hits_invented_names"


def test_correction_text_is_idempotent():


    text = CORRECTION_NOT_FOUND
    corrected, slug = truth_guard(
        query="find anything related to Wells Fargo",
        reply_text=text,
        tool_name="find_in_vault",
        tool_result=_result(hits=[]),
    )
    assert slug is None
    assert corrected == text


def test_guarded_tool_names_closed_set():
    assert GUARDED_TOOL_NAMES == frozenset({
        "find_in_vault",
        "list_saved_credentials",
        "get_credential_metadata",
        "list_secrets",
        "retrieve_secret",
    })


def test_credential_tool_names_closed_set():
    from vault_chat_truth_guard import CREDENTIAL_TOOL_NAMES
    assert CREDENTIAL_TOOL_NAMES == frozenset({
        "list_saved_credentials",
        "get_credential_metadata",
        "list_secrets",
        "retrieve_secret",
    })


def test_guard_blocks_passport_query_routed_to_list_saved_credentials():


    reply = (
        "I found one password stored for the following service:\n\n"
        "- Union Bank\n\n"
        "If you need the details for this login, just let me know!"
    )
    corrected, slug = truth_guard(
        query="find me any passport in my vault",
        reply_text=reply,
        tool_name="list_saved_credentials",
        tool_result='{"services":["Union Bank"]}',
    )
    assert slug == "document_query_credential_tool"
    assert corrected == CORRECTION_NOT_FOUND


def test_guard_blocks_drivers_license_query_routed_to_credentials():

    reply = "I have your saved Chase login. Want to see the details?"
    corrected, slug = truth_guard(
        query="find my driver's license",
        reply_text=reply,
        tool_name="get_credential_metadata",
        tool_result='{"service":"Chase"}',
    )
    assert slug == "document_query_credential_tool"
    assert corrected == CORRECTION_NOT_FOUND


def test_guard_blocks_id_card_query_routed_to_credentials():
    reply = "I found your saved Apple ID login."
    corrected, slug = truth_guard(
        query="show me my ID card",
        reply_text=reply,
        tool_name="list_saved_credentials",
        tool_result='{"services":["Apple"]}',
    )
    assert slug == "document_query_credential_tool"


def test_guard_allows_credential_query_to_credential_tool():


    reply = "Your saved credentials: Union Bank, Chase, Amazon."
    corrected, slug = truth_guard(
        query="show me all my saved logins",
        reply_text=reply,
        tool_name="list_saved_credentials",
        tool_result='{"services":["Union Bank","Chase","Amazon"]}',
    )
    assert slug is None
    assert corrected == reply


def test_query_asks_for_document_positive_set():
    from vault_chat_truth_guard import _query_asks_for_document
    for q in (
        "find me any passport in my vault",
        "show my passports",
        "where is my driver's license",
        "I need my drivers license",
        "do I have an ID card",
        "show me my identity card",
        "national ID lookup",
        "find my green card",
        "do I have a birth certificate",
        "show my SSN card",
    ):
        assert _query_asks_for_document(q), f"should match: {q!r}"


def test_query_asks_for_document_negative_set():
    from vault_chat_truth_guard import _query_asks_for_document
    for q in (
        "show me all my saved logins",
        "what is my Chase password",
        "find anything related to Wells Fargo",
        "find files that contain login details",
        "show me my tax return",
        "what's in my vault",
    ):
        assert not _query_asks_for_document(q), f"should NOT match: {q!r}"


def test_correction_constants_do_not_carry_secrets():


    for s in (CORRECTION_NOT_FOUND, CORRECTION_NOT_FOUND_SEARCH_LIMITED):
        assert "password" not in s.lower()
        assert "username" not in s.lower()
        assert ".jpg" not in s
        assert ".txt" not in s


def test_ai_stream_invokes_truth_guard():


    with open("main.py", encoding="utf-8") as f:
        src = f.read()
    assert "from vault_chat_truth_guard import" in src
    assert "truth_guard(" in src
