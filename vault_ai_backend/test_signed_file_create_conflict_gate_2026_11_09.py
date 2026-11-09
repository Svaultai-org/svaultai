"""Synthetic safety checks while private duplicate parity is unavailable."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi import HTTPException
import pytest

from file_create_conflict_gate import new_file_conflict_parity_ready
from routes import file_v2_new_upload_routes as uploads
from routes import file_v2_routes as staging


def test_deployment_flags_cannot_claim_unbuilt_conflict_parity(monkeypatch):
    monkeypatch.setenv("VAULTAI_SIGNED_FILE_CREATE_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_NEW_FILE_V2_ENABLED", "true")
    assert new_file_conflict_parity_ready() is False


@pytest.mark.parametrize("mode", ["signed_create", "strict_file", "v2_pilot"])
def test_unindexed_new_manifest_stops_before_storage_or_billing(
    monkeypatch, mode,
):
    monkeypatch.setenv("VAULTAI_ZK_NEW_FILE_V2_ENABLED", "true")
    if mode == "signed_create":
        monkeypatch.setenv("VAULTAI_SIGNED_FILE_CREATE_ENABLED", "true")
    elif mode == "strict_file":
        monkeypatch.setenv("VAULTAI_ENABLE_ZK_FILE_PIN_FREE_ONLY", "true")
    monkeypatch.setattr(staging, "_enabled", lambda *_: None)

    def unexpected_database(*_args, **_kwargs):
        raise AssertionError("unindexed manifest reached billing or storage")

    monkeypatch.setattr(staging, "require_content_write", unexpected_database)
    monkeypatch.setattr(staging, "get_db", unexpected_database)
    manifest = staging.Manifest(
        file_id="v2-AAAAAAAAAAAAAAAAAAAAAAAAAAA",
        crypto_version="client_mvk_v2",
        manifest_ciphertext="AQID",
        total_bytes=3,
        chunk_size=1024,
        chunk_count=1,
    )
    with pytest.raises(HTTPException) as blocked:
        staging.create_manifest(manifest, {"vault_id": "synthetic-vault"})
    assert blocked.value.status_code == 409
    assert blocked.value.detail == "private_file_conflict_index_unavailable"


@pytest.mark.parametrize("mode,offer_bits", [
    ("signed_create", 8),
    ("strict_file", 0),
    ("v2_pilot", 0),
])
def test_two_concurrent_publishes_stop_in_every_new_v2_mode(
    monkeypatch, mode, offer_bits,
):
    # Client modes share this publish route. Even an unoffered pilot or strict
    # build cannot bypass the prerequisite by omitting signed offer bit 8.
    if mode == "signed_create":
        monkeypatch.setenv("VAULTAI_SIGNED_FILE_CREATE_ENABLED", "true")
    elif mode == "strict_file":
        monkeypatch.setenv("VAULTAI_ENABLE_ZK_FILE_PIN_FREE_ONLY", "true")
    else:
        monkeypatch.setenv("VAULTAI_ZK_NEW_FILE_V2_ENABLED", "true")
    monkeypatch.setattr(uploads, "_new_upload_enabled", lambda: None)

    def unexpected_database():
        raise AssertionError("unindexed signed publish reached the database")

    monkeypatch.setattr(uploads, "get_db", unexpected_database)
    barrier = Barrier(2)
    principal = {
        "vault_id": "synthetic-vault-with-older-files",
        "pin_free_read_offers": offer_bits,
        "file_v2_reader_capable": True,
    }

    def attempt(file_id: str):
        barrier.wait()
        try:
            uploads.publish_new_file(
                file_id,
                uploads.PublishNewFile(confirm=True),
                principal,
            )
        except HTTPException as exc:
            return exc.status_code, exc.detail
        raise AssertionError("unindexed signed file became visible")

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(attempt, (
            "v2-AAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "v2-BBBBBBBBBBBBBBBBBBBBBBBBBBB",
        )))

    assert results == [
        (409, "private_file_conflict_index_unavailable"),
        (409, "private_file_conflict_index_unavailable"),
    ]
