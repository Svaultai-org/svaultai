

from __future__ import annotations

import json

import pytest

from vault_chat_save_guard import (
    SAFE_CORRECTION_TEXT,
    SAVE_TOOL_NAMES,
    detect_save_claim,
    guard_response_text,
    tool_call_was_successful_save,
)


@pytest.mark.parametrize(
    "text,expected_slug",
    [
                                                        
        ("I've saved the credentials for Union Bank.",        "i_saved"),
        ("I have saved your Chase login.",                    "i_saved"),
        ("I saved your Gmail credential.",                    "i_saved"),
                                                   
        ("Saved your Union Bank login.",                      "saved_your"),
        ("Your password is now stored in your vault.",        "stored_in_vault"),
        ("I added it to your vault.",                         "added_to_vault"),
        ("Put it in your vault for safekeeping.",             "added_to_vault"),
        ("All set — secured in your vault.",                  "secured_in_vault"),
        ("Your credentials are saved now.",                   "credentials_are_saved"),
        ("The credentials are stored.",                       "credentials_are_saved"),
        ("Your login is saved.",                              "login_is_saved"),
        ("Your login is now stored.",                         "login_is_saved"),
    ],
)
def test_detect_save_claim_positive(text, expected_slug):


    assert detect_save_claim(text) == expected_slug


@pytest.mark.parametrize(
    "text",
    [
        "",
        "I created a draft for Union Bank.",
                                                                         
        "Say save it now and I'll store it in your vault.",
                                          
        "Here is the username and password I generated.",
                                                                   
        SAFE_CORRECTION_TEXT,
                                                                              
        "I restored your settings.",
        "My savings account balance is high.",
        "Username: calmanchor63",
                                                                 
                                                                 
        "I couldn't find any photo ID cards. There are no images "
        "stored in your vault matching that query.",
        "No documents are stored in your vault yet.",
        "No files are stored in your vault that match Louis Iodato.",
        "There is no record stored in your vault for that query.",
        "I found nothing stored in your vault under that name.",
    ],
)
def test_detect_save_claim_negative(text):


    assert detect_save_claim(text) is None


def test_save_tool_names_closed_set():


    assert SAVE_TOOL_NAMES == frozenset({
        "save_secret",
        "save_generated_credential_after_confirmation",
    })


@pytest.mark.parametrize(
    "tool_name,result,expected",
    [
                              
        ("save_secret", json.dumps({"status": "saved"}), True),
        ("save_secret", '{"saved": true}', True),
        ("save_generated_credential_after_confirmation",
         json.dumps({"status": "saved", "service": "Union Bank"}), True),
        ("save_secret", {"status": "saved"}, True),
                                                   
        ("search_extracted_text",
         json.dumps({"hits": [], "returned": 0}), False),
        ("get_credential_metadata",
         json.dumps({"service": "Union Bank", "exists": True}), False),
        ("read_file_text",
         json.dumps({"extracted_text": "..."}), False),
                                         
        ("save_secret", json.dumps({"error": "unavailable"}), False),
        ("save_secret", '{"error": "vault_locked"}', False),
                                                      
        ("save_secret", None, False),
        ("save_secret", "", False),
        ("save_secret", "    ", False),
    ],
)
def test_tool_call_was_successful_save(tool_name, result, expected):
    assert tool_call_was_successful_save(tool_name, result) == expected


def test_save_tool_result_as_bytes():


    result = json.dumps({"status": "saved"}).encode("utf-8")
    assert tool_call_was_successful_save("save_secret", result) is True


def test_save_tool_result_bad_json_falls_through_safely():


    assert tool_call_was_successful_save(
        "save_secret", "{not really json",
    ) is True                                   
    assert tool_call_was_successful_save(
        "save_secret", "some error happened",
    ) is False


def test_guard_replaces_hallucinated_save_with_correction():


    bad_reply = "I've saved the credentials for Union Bank."
    corrected, slug = guard_response_text(
        reply_text=bad_reply,
        save_tool_succeeded=False,
    )
    assert corrected == SAFE_CORRECTION_TEXT
    assert slug == "i_saved"


def test_guard_allows_save_language_when_tool_succeeded():


    good_reply = (
        "Saved your Union Bank login. The username and password "
        "are stored securely in your vault."
    )
    corrected, slug = guard_response_text(
        reply_text=good_reply,
        save_tool_succeeded=True,
    )
    assert corrected == good_reply
    assert slug is None


def test_guard_passes_through_draft_replies_untouched():

    draft = (
        "I created a login draft for Union Bank.\n"
        "Username: calmanchor63\n"
        "Password: hunter2!hunter2!\n"
        "Say \"save it now\" and I'll store it in your vault."
    )
    corrected, slug = guard_response_text(
        reply_text=draft, save_tool_succeeded=False,
    )
    assert corrected == draft
    assert slug is None


def test_guard_correction_text_does_not_self_trigger():


    corrected, slug = guard_response_text(
        reply_text=SAFE_CORRECTION_TEXT,
        save_tool_succeeded=False,
    )
    assert corrected == SAFE_CORRECTION_TEXT
    assert slug is None


def test_guard_correction_message_explicit_text():


    assert SAFE_CORRECTION_TEXT == (
        "I created the login draft, but I haven't saved it yet. "
        "Say \"save it\" when you want me to store it in your vault."
    )


def test_guard_correction_does_not_echo_password():


    assert "Password:" not in SAFE_CORRECTION_TEXT
    assert "password is" not in SAFE_CORRECTION_TEXT.lower()


def test_guard_blocks_save_claim_even_with_unrelated_tool_success():


    flag = tool_call_was_successful_save(
        "search_extracted_text",
        json.dumps({"hits": [], "returned": 0}),
    )
    assert flag is False
    corrected, slug = guard_response_text(
        reply_text="I've saved the credentials for Union Bank.",
        save_tool_succeeded=flag,
    )
    assert corrected == SAFE_CORRECTION_TEXT
    assert slug == "i_saved"


def test_system_prompt_carries_never_fake_a_save_rule():


    from tools import STATIC_VAULT_SYSTEM_PROMPT
    assert "NEVER FAKE A SAVE" in STATIC_VAULT_SYSTEM_PROMPT
    assert "save_secret" in STATIC_VAULT_SYSTEM_PROMPT
    assert (
        "save_generated_credential_after_confirmation"
        in STATIC_VAULT_SYSTEM_PROMPT
    )


def test_system_prompt_forbids_password_echo_after_save():


    from tools import STATIC_VAULT_SYSTEM_PROMPT
    assert "MUST NOT echo the password" in STATIC_VAULT_SYSTEM_PROMPT


def test_system_prompt_carries_credential_draft_shape():


    from tools import STATIC_VAULT_SYSTEM_PROMPT
    assert "CREDENTIAL CREATION DRAFT" in STATIC_VAULT_SYSTEM_PROMPT
    assert "save it now" in STATIC_VAULT_SYSTEM_PROMPT
                                                            
                                                      
    assert "generate_credential_draft" in STATIC_VAULT_SYSTEM_PROMPT
    assert "username from tool result" in STATIC_VAULT_SYSTEM_PROMPT
    assert "password from tool result" in STATIC_VAULT_SYSTEM_PROMPT
