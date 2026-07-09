

from __future__ import annotations

import json
import time

import pytest

import vault_credential_draft as draft_store
from vault_credential_draft import (
    CredentialDraft,
    DRAFT_TTL_SECONDS,
    clear_drafts_for_vault,
    consume_draft,
    get_draft,
    store_draft,
)


VAULT_A = "11111111-aaaa-bbbb-cccc-dddddddddddd"
VAULT_B = "22222222-aaaa-bbbb-cccc-dddddddddddd"


@pytest.fixture(autouse=True)
def _clean_store():
    draft_store._reset_store_for_test()
    yield
    draft_store._reset_store_for_test()


def test_credential_draft_repr_redacts_password():


    d = store_draft(
        vault_id=VAULT_A,
        service_name="Union Bank",
        username="calmanchor63",
        password="2XqFRvT$YCMGzvJ4r*M5",
    )
    rendered = repr(d)
    assert "2XqFRvT" not in rendered
    assert "<REDACTED>" in rendered
                                                               
                         
    assert str(d) == repr(d)


def test_credential_draft_to_public_dict_carries_password_intentionally():


    d = store_draft(
        vault_id=VAULT_A, service_name="Union Bank",
        username="calmanchor63", password="hunter2!hunter2!",
    )
    payload = d.to_public_dict()
    assert payload["password"] == "hunter2!hunter2!"
    assert payload["username"] == "calmanchor63"
    assert payload["service_name"] == "Union Bank"
    assert payload["saved"] is False
    assert isinstance(payload["draft_id"], str) and len(payload["draft_id"]) == 32
    assert isinstance(payload["expires_at"], int)


def test_get_draft_returns_most_recent_for_vault():
    a = store_draft(
        vault_id=VAULT_A, service_name="Union Bank",
        username="riverfox12", password="pw-A",
    )
    time.sleep(0.001)
    b = store_draft(
        vault_id=VAULT_A, service_name="Chase",
        username="northmark91", password="pw-B",
    )
    found = get_draft(vault_id=VAULT_A)
    assert found is not None
    assert found.draft_id == b.draft_id
                                    
    found_a = get_draft(vault_id=VAULT_A, service_name="union bank")
    assert found_a is not None and found_a.draft_id == a.draft_id


def test_get_draft_by_id_exact_match():
    a = store_draft(
        vault_id=VAULT_A, service_name="Gmail",
        username="lunardrift18", password="pw-A",
    )
    found = get_draft(vault_id=VAULT_A, draft_id=a.draft_id)
    assert found is not None
    assert found.draft_id == a.draft_id


def test_draft_store_is_vault_scoped():

    a = store_draft(
        vault_id=VAULT_A, service_name="Chase",
        username="silverbay44", password="pw-A",
    )
    assert get_draft(vault_id=VAULT_B) is None
    assert get_draft(vault_id=VAULT_B, draft_id=a.draft_id) is None
    assert get_draft(vault_id=VAULT_B, service_name="Chase") is None


def test_expired_drafts_dropped_silently():

    a = store_draft(
        vault_id=VAULT_A, service_name="Chase",
        username="quietglow88", password="pw-A",
        ttl_seconds=1,
    )
    assert get_draft(vault_id=VAULT_A, draft_id=a.draft_id) is not None
                                                         
                                                                 
    draft_store._store[VAULT_A][a.draft_id] = CredentialDraft(
        draft_id=a.draft_id, vault_id=a.vault_id,
        service_name=a.service_name, username=a.username,
        password=a.password, created_at=a.created_at,
        expires_at=time.time() - 1, saved=False,
        service_key=a.service_key,
    )
    assert get_draft(vault_id=VAULT_A, draft_id=a.draft_id) is None


def test_consume_draft_removes_from_store():
    a = store_draft(
        vault_id=VAULT_A, service_name="Gmail",
        username="cobaltgrove12", password="pw-A",
    )
    consumed = consume_draft(vault_id=VAULT_A, draft_id=a.draft_id)
    assert consumed is not None and consumed.saved is True
                                   
    assert get_draft(vault_id=VAULT_A, draft_id=a.draft_id) is None
                                        
    assert consume_draft(vault_id=VAULT_A, draft_id=a.draft_id) is None


def test_clear_drafts_for_vault_wipes_everything():
    store_draft(
        vault_id=VAULT_A, service_name="A",
        username="lonepine22", password="pw-A",
    )
    store_draft(
        vault_id=VAULT_A, service_name="B",
        username="willowpath31", password="pw-B",
    )
    n = clear_drafts_for_vault(VAULT_A)
    assert n == 2
    assert get_draft(vault_id=VAULT_A) is None


from vault_inspection_tools import generate_credential_draft

VALID_KEY = b"\x00" * 32


def test_generate_credential_draft_returns_expected_shape():
    out = json.loads(generate_credential_draft(
        vault_id=VAULT_A, key=VALID_KEY, service_name="Union Bank",
    ))
    assert out["service_name"] == "Union Bank"
    assert out["saved"] is False
    assert isinstance(out["draft_id"], str) and len(out["draft_id"]) == 32
    assert isinstance(out["expires_at"], int)
                               
    pw = out["password"]
    assert len(pw) >= 16
    assert any(c.isupper() for c in pw)
    assert any(c.islower() for c in pw)
    assert any(c.isdigit() for c in pw)
                               
    un = out["username"]
    assert 8 <= len(un) <= 16
    assert un == un.lower()
    assert un.isalnum()


def test_generate_credential_draft_username_does_not_leak_service():

    for service in ("Union Bank", "Chase", "Gmail", "Capital One"):
        out = json.loads(generate_credential_draft(
            vault_id=VAULT_A, key=VALID_KEY, service_name=service,
        ))
        token = "".join(c for c in service.lower() if c.isalnum())
        assert token not in out["username"], (
            f"username {out['username']!r} leaks service {service!r}"
        )


def test_generate_credential_draft_username_does_not_leak_vault_word():

    out = json.loads(generate_credential_draft(
        vault_id=VAULT_A, key=VALID_KEY, service_name="Anywhere",
    ))
    assert "vault" not in out["username"].lower()


def test_generate_credential_draft_locks_on_invalid_key():
    out = json.loads(generate_credential_draft(
        vault_id=VAULT_A, key=b"too-short", service_name="X",
    ))
    assert out == {"error": "vault_locked"}


def test_generate_credential_draft_rejects_missing_service():
    out = json.loads(generate_credential_draft(
        vault_id=VAULT_A, key=VALID_KEY, service_name="   ",
    ))
    assert out == {"error": "missing_service"}


def test_generate_credential_draft_persists_pending_draft():


    out = json.loads(generate_credential_draft(
        vault_id=VAULT_A, key=VALID_KEY, service_name="Union Bank",
    ))
    found = get_draft(vault_id=VAULT_A, draft_id=out["draft_id"])
    assert found is not None
    assert found.password == out["password"]
    assert found.username == out["username"]
    assert found.saved is False


def test_two_consecutive_drafts_produce_different_passwords():


    a = json.loads(generate_credential_draft(
        vault_id=VAULT_A, key=VALID_KEY, service_name="Union Bank",
    ))
    b = json.loads(generate_credential_draft(
        vault_id=VAULT_A, key=VALID_KEY, service_name="Union Bank",
    ))
    assert a["draft_id"] != b["draft_id"]
    assert a["password"] != b["password"]


def test_generate_credential_draft_is_never_cacheable():
    from vault_tool_result_cache import (
        CACHEABLE_TOOLS, NEVER_CACHEABLE_TOOLS,
    )
    assert "generate_credential_draft" in NEVER_CACHEABLE_TOOLS
    assert "generate_credential_draft" not in CACHEABLE_TOOLS


def test_cache_refuses_to_store_a_draft_result():


    from vault_tool_result_cache import maybe_get_cached, maybe_store
    maybe_store(
        vault_id=VAULT_A,
        token_id="t1",
        tool_name="generate_credential_draft",
        args={"service_name": "Union Bank"},
        result='{"password": "should-never-be-cached"}',
    )
    hit = maybe_get_cached(
        vault_id=VAULT_A, token_id="t1",
        tool_name="generate_credential_draft",
        args={"service_name": "Union Bank"},
    )
    assert hit is None


class _FakeSaveSecretTool:


    def __init__(self):
        self.calls: list[tuple] = []

    def __call__(self, vault_id, args, key, generated: bool = False):
        self.calls.append((vault_id, args, key, generated))
        return "Saved (fake)."


@pytest.fixture
def fake_save_secret(monkeypatch):
    fake = _FakeSaveSecretTool()
    monkeypatch.setattr(
        "main.save_secret_tool", fake, raising=True,
    )
    return fake


def test_save_with_draft_id_consumes_pending_draft(fake_save_secret):


    from vault_inspection_tools import (
        save_generated_credential_after_confirmation,
    )
    draft_out = json.loads(generate_credential_draft(
        vault_id=VAULT_A, key=VALID_KEY, service_name="Union Bank",
    ))
    out = json.loads(save_generated_credential_after_confirmation(
        vault_id=VAULT_A, key=VALID_KEY,
        draft_id=draft_out["draft_id"],
        user_confirmed=True,
    ))
    assert out["saved"] is True
    assert out["service"] == "Union Bank"
    assert out["draft_consumed"] is True
                                                           
                                
    assert len(fake_save_secret.calls) == 1
    _, save_args, _, _ = fake_save_secret.calls[0]
    assert save_args["service"] == "Union Bank"
    assert save_args["secret_type"] == "login"
    assert save_args["fields"]["username"] == draft_out["username"]
    assert save_args["fields"]["password"] == draft_out["password"]
                                   
    assert get_draft(vault_id=VAULT_A, draft_id=draft_out["draft_id"]) is None


def test_save_without_draft_id_uses_most_recent(fake_save_secret):


    from vault_inspection_tools import (
        save_generated_credential_after_confirmation,
    )
    draft_out = json.loads(generate_credential_draft(
        vault_id=VAULT_A, key=VALID_KEY, service_name="Union Bank",
    ))
    out = json.loads(save_generated_credential_after_confirmation(
        vault_id=VAULT_A, key=VALID_KEY,
        user_confirmed=True,
    ))
    assert out["saved"] is True
    assert out["draft_consumed"] is True
    _, save_args, _, _ = fake_save_secret.calls[0]
    assert save_args["fields"]["password"] == draft_out["password"]


def test_save_rejects_without_user_confirmed():
    from vault_inspection_tools import (
        save_generated_credential_after_confirmation,
    )
    store_draft(
        vault_id=VAULT_A, service_name="Chase",
        username="riverpath92", password="pw-A",
    )
    out = json.loads(save_generated_credential_after_confirmation(
        vault_id=VAULT_A, key=VALID_KEY,
        draft_id=None,
        user_confirmed=None,
    ))
    assert out["error"] == "confirmation_required"


def test_save_rejects_when_no_draft_and_no_fields():
    from vault_inspection_tools import (
        save_generated_credential_after_confirmation,
    )
    out = json.loads(save_generated_credential_after_confirmation(
        vault_id=VAULT_A, key=VALID_KEY,
        service="",
        fields=None,
        user_confirmed=True,
    ))
    assert out["error"] == "missing_service"


def test_save_response_does_not_echo_password(fake_save_secret):


    from vault_inspection_tools import (
        save_generated_credential_after_confirmation,
    )
    draft_out = json.loads(generate_credential_draft(
        vault_id=VAULT_A, key=VALID_KEY, service_name="Union Bank",
    ))
    pw = draft_out["password"]
    raw = save_generated_credential_after_confirmation(
        vault_id=VAULT_A, key=VALID_KEY,
        draft_id=draft_out["draft_id"],
        user_confirmed=True,
    )
    assert pw not in raw
    out = json.loads(raw)
    assert "password" not in out
    assert "fields" not in out


def test_save_then_save_again_finds_no_draft(fake_save_secret):


    from vault_inspection_tools import (
        save_generated_credential_after_confirmation,
    )
    draft_out = json.loads(generate_credential_draft(
        vault_id=VAULT_A, key=VALID_KEY, service_name="Union Bank",
    ))
    save_generated_credential_after_confirmation(
        vault_id=VAULT_A, key=VALID_KEY,
        draft_id=draft_out["draft_id"], user_confirmed=True,
    )
    out = json.loads(save_generated_credential_after_confirmation(
        vault_id=VAULT_A, key=VALID_KEY,
        user_confirmed=True,
    ))
                                                               
                                                                  
    assert out["error"] == "missing_service"


def test_history_compression_does_not_touch_draft_store():


    draft_out = json.loads(generate_credential_draft(
        vault_id=VAULT_A, key=VALID_KEY, service_name="Union Bank",
    ))
    from vault_history_compressor import compress_messages
                                                       
                                                          
    history = []
    for i in range(8):
        history.append({"role": "user", "content": f"turn {i} question"})
        history.append({"role": "assistant", "content": f"turn {i} answer"})
    _ = compress_messages(history)
                                              
    still_there = get_draft(
        vault_id=VAULT_A, draft_id=draft_out["draft_id"],
    )
    assert still_there is not None
    assert still_there.password == draft_out["password"]


def test_planner_allows_generate_credential_draft_tool_name():
    from vault_planner import _VALID_TOOL_NAMES
    assert "generate_credential_draft" in _VALID_TOOL_NAMES


def test_planner_prompt_mentions_generate_credential_draft():


    from vault_planner import PLANNER_SYSTEM_PROMPT
    assert "generate_credential_draft" in PLANNER_SYSTEM_PROMPT


def test_system_prompt_references_generate_credential_draft_tool():
    from tools import STATIC_VAULT_SYSTEM_PROMPT
    assert "generate_credential_draft" in STATIC_VAULT_SYSTEM_PROMPT


def test_system_prompt_keeps_save_password_no_echo_rule():


    from tools import STATIC_VAULT_SYSTEM_PROMPT
    assert "MUST NOT echo the password" in STATIC_VAULT_SYSTEM_PROMPT


def test_inspection_dispatch_carries_generate_credential_draft():
    from vault_inspection_tools import INSPECTION_DISPATCH
    assert "generate_credential_draft" in INSPECTION_DISPATCH
    assert callable(INSPECTION_DISPATCH["generate_credential_draft"])


def test_inspection_functions_carries_generate_credential_draft_schema():
    from vault_inspection_tools import INSPECTION_FUNCTIONS
    names = [
        fn.get("function", {}).get("name") for fn in INSPECTION_FUNCTIONS
    ]
    assert "generate_credential_draft" in names
    schema = next(
        fn for fn in INSPECTION_FUNCTIONS
        if fn["function"]["name"] == "generate_credential_draft"
    )["function"]
    assert "service_name" in schema["parameters"]["properties"]
    assert schema["parameters"]["required"] == ["service_name"]
