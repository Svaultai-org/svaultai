"""AI memory persistence for a ZK/adopted Vault must never reach
the plaintext INSERT path server-side.

Verifies by mocking `is_vault_zk_adopted` to True and `update_memory_safe`
as a spy. `_handle_remember_fact` must emit the memory_proposal sentinel
prefix and NOT call `update_memory_safe`.
"""

from __future__ import annotations

from unittest import mock


def test_zk_adopted_vault_emits_memory_proposal_and_does_not_persist() -> None:
    from main import _handle_remember_fact
    with mock.patch("vault_core.is_vault_zk_adopted", return_value=True), \
         mock.patch("ai_memory.update_memory_safe") as spy_update, \
         mock.patch("ai_memory.is_enabled", return_value=True):
        reply = _handle_remember_fact(
            vault_id="00000000-0000-0000-0000-000000000000",
            memory_type="preference",
            memory_key="favorite_color",
            memory_value="teal",
            memory_event_date=None,
        )
    assert reply is not None
    assert reply.startswith("<<VAULTAI_MEMORY_PROPOSAL>>"), (
        "ZK-adopted vault memory-save must emit the "
        "memory_proposal sentinel so the Flutter client can encrypt "
        "and finalize. Got: " + repr(reply[:80])
    )
    assert "<<END>>" in reply
    assert spy_update.call_count == 0, (
        "ZK-adopted vault MUST NOT reach update_memory_safe — the "
        "backend must not persist readable memory_key / memory_value "
        "even briefly. update_memory_safe was called."
    )


def test_legacy_vault_still_persists_via_plaintext_path() -> None:
    """Non-adopted vaults keep the legacy code path so the product
    doesn't regress for un-migrated users. This test ensures the
    ZK branch doesn't short-circuit legacy behavior."""
    from main import _handle_remember_fact
    with mock.patch("vault_core.is_vault_zk_adopted", return_value=False), \
         mock.patch("ai_memory.update_memory_safe",
                    return_value={"ok": True, "status": "inserted",
                                  "prior_value": None, "new_value": "teal",
                                  "key": "favorite_color"}), \
         mock.patch("ai_memory.is_enabled", return_value=True), \
         mock.patch("relationship_builder.build_relationships_for_memory_safe",
                    return_value=None), \
         mock.patch("expiry_engine.build_expiry_alerts_for_memory_safe",
                    return_value=None):
        reply = _handle_remember_fact(
            vault_id="00000000-0000-0000-0000-000000000000",
            memory_type="preference",
            memory_key="favorite_color",
            memory_value="teal",
            memory_event_date=None,
        )
    assert reply is not None
    assert not reply.startswith("<<VAULTAI_MEMORY_PROPOSAL>>")
