"""Default-off V2 staging and release readback for a linked legacy link.

The old wrapped key and credential package remain intact. The existing
approval/cooldown state gates release, while a separate ceremony is still
needed to verify decryption and retire the old protocol.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.extras import RealDictCursor
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from inheritance_protocol import ZK_BENEFICIARY_V2_MARKER, zk_beneficiary_v2_enabled
from routes.auth_zk_routes import consume_recent_zk_proof_on_cursor
from rate_limit_sensitive import enforce_export_rate_limit
from subscription_entitlement import require_content_write
from vault_core import get_db


router = APIRouter(tags=["linked-inheritance-v2-upgrade"])
FLAG_NAME = "VAULTAI_ZK_LINKED_BENEFICIARY_V2_STAGE_ENABLED"
KEYCHECK_FLAG_NAME = "VAULTAI_ZK_LINKED_BENEFICIARY_KEYCHECK_ENABLED"
RELEASE_READBACK_FLAG_NAME = (
    "VAULTAI_ZK_LINKED_BENEFICIARY_RELEASE_READBACK_ENABLED"
)
_KEYCHECK_INFO = b"vaultai.inh-v2-beneficiary-keycheck.v1"
_CHALLENGE_LIFETIME = timedelta(minutes=5)


class StageLinkedV2Package(BaseModel):
    model_config = ConfigDict(extra="forbid")
    beneficiary_link_id: int = Field(gt=0)
    crypto_version: Literal[2]
    expected_beneficiary_pk_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_stage_revision: int | None = Field(default=None, gt=0)
    zk_proof_token: str = Field(min_length=1, max_length=128)
    encrypted_payload: str = Field(min_length=1)
    payload_nonce: str = Field(min_length=1)
    wrapped_key: str = Field(min_length=1)
    wrapping_ephemeral_pk: str = Field(min_length=1)
    wrapping_nonce: str = Field(min_length=1)


class CompleteBeneficiaryKeyCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    beneficiary_link_id: int = Field(gt=0)
    stage_revision: int = Field(gt=0)
    offer_commitment: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    challenge_secret: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    expected_beneficiary_pk_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    zk_proof_token: str = Field(min_length=1, max_length=128)


_LINK_FIELDS = (
    "id", "passer_vault_id", "beneficiary_vault_id", "passer_label",
    "passer_label_ciphertext", "wrapped_vault_key", "status",
    "pairing_state", "transfer_requested_at", "transfer_executes_at",
    "access_requested_at", "cooldown_ends_at", "decision_at",
)
_CREDENTIAL_FIELDS = (
    "id", "owner_vault_id", "crypto_version", "encrypted_payload", "payload_nonce",
    "wrapped_key", "wrapping_ephemeral_pk", "wrapping_nonce", "state",
)
_SOURCE_LINK_FIELDS = (
    "id", "passer_vault_id", "beneficiary_vault_id", "wrapped_vault_key",
)
_SOURCE_CREDENTIAL_FIELDS = tuple(
    field for field in _CREDENTIAL_FIELDS if field != "state"
)
_ENVELOPE_FIELDS = (
    "encrypted_payload", "payload_nonce", "wrapped_key",
    "wrapping_ephemeral_pk", "wrapping_nonce",
)


def _enabled() -> None:
    if (os.getenv(FLAG_NAME, "false").strip().lower() != "true" or
            os.getenv("VAULTAI_ZK_BENEFICIARY_PROOF_ENABLED", "false")
            .strip().lower() != "true" or
            not zk_beneficiary_v2_enabled()):
        raise HTTPException(status_code=404, detail="not_found")


def _keycheck_enabled() -> None:
    _enabled()
    if os.getenv(KEYCHECK_FLAG_NAME, "false").strip().lower() != "true":
        raise HTTPException(status_code=404, detail="not_found")


def _release_readback_enabled() -> None:
    _keycheck_enabled()
    if os.getenv(RELEASE_READBACK_FLAG_NAME, "false").strip().lower() != "true":
        raise HTTPException(status_code=404, detail="not_found")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(value: str, *, low: int, high: int) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise HTTPException(status_code=400, detail="invalid_v2_envelope")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="invalid_v2_envelope") from exc
    if not low <= len(raw) <= high or _b64(raw) != value:
        raise HTTPException(status_code=400, detail="invalid_v2_envelope")
    return raw


def _envelope(payload: StageLinkedV2Package) -> dict[str, bytes]:
    return {
        "encrypted_payload": _decode(payload.encrypted_payload, low=32, high=65536),
        "payload_nonce": _decode(payload.payload_nonce, low=12, high=12),
        "wrapped_key": _decode(payload.wrapped_key, low=32, high=4096),
        "wrapping_ephemeral_pk": _decode(
            payload.wrapping_ephemeral_pk, low=32, high=32,
        ),
        "wrapping_nonce": _decode(payload.wrapping_nonce, low=12, high=12),
    }


def _feed(h, value: object) -> None:
    if value is None:
        raw = b""
    elif isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
    else:
        raw = str(value).encode("utf-8")
    h.update(len(raw).to_bytes(8, "big"))
    h.update(raw)


def _source_snapshot(link: dict, credential: dict | None) -> str:
    # The V2 package is staged before an access request. Pairing state,
    # timestamps, and the escrow state then change during the legitimate
    # cooldown. Bind only identity and ciphertext, and check release state
    # separately when the beneficiary requests the package. The v2 domain
    # makes any QA row staged under the earlier mutable digest fail closed.
    h = hashlib.sha256(b"linked-inheritance-v2-old-source/v2\x00")
    for name in _SOURCE_LINK_FIELDS:
        _feed(h, link.get(name))
    for name in _SOURCE_CREDENTIAL_FIELDS:
        _feed(h, credential.get(name) if credential else None)
    return _b64(h.digest())


def _load_old_link(
    cur, *, link_id: int, lock: bool,
    owner_vault_id: str | None = None,
    beneficiary_vault_id: str | None = None,
) -> tuple[dict, dict | None]:
    if (owner_vault_id is None) == (beneficiary_vault_id is None):
        raise ValueError("Exactly one link role is required")
    column = "passer_vault_id" if owner_vault_id is not None else "beneficiary_vault_id"
    actor = owner_vault_id if owner_vault_id is not None else beneficiary_vault_id
    suffix = "FOR UPDATE" if lock else "FOR SHARE"
    cur.execute(
        f"SELECT {', '.join(_LINK_FIELDS)} FROM beneficiary_links "
        f"WHERE id=%s AND {column}=%s {suffix}",
        (link_id, actor),
    )
    link = cur.fetchone()
    if (not link or
            not isinstance(link["wrapped_vault_key"], str) or
            not link["wrapped_vault_key"] or
            link["wrapped_vault_key"] == ZK_BENEFICIARY_V2_MARKER or
            link["beneficiary_vault_id"] is None or
            str(link["beneficiary_vault_id"]) == str(owner_vault_id) or
            link["status"] != "linked" or
            link.get("pairing_state") not in
            (None, "paired_no_credentials", "credentials_saved") or
            any(link.get(name) is not None for name in (
                "transfer_requested_at", "transfer_executes_at",
                "access_requested_at", "cooldown_ends_at", "decision_at",
            ))):
        raise HTTPException(status_code=409, detail="old_link_not_idle_and_linked")
    cur.execute(
        """SELECT id,owner_vault_id,crypto_version,encrypted_payload,payload_nonce,
                  wrapped_key,wrapping_ephemeral_pk,wrapping_nonce,state
             FROM inheritance_credentials
            WHERE beneficiary_link_id=%s AND deleted_at IS NULL
            FOR SHARE""",
        (link_id,),
    )
    credential = cur.fetchone()
    if credential and str(credential["owner_vault_id"]) != str(link["passer_vault_id"]):
        raise HTTPException(status_code=409, detail="old_link_package_owner_changed")
    if credential and int(credential["crypto_version"]) != 1:
        raise HTTPException(status_code=409, detail="old_link_package_protocol_changed")
    if ((credential is None and link.get("pairing_state") == "credentials_saved") or
            (credential is not None and
             (link.get("pairing_state") == "paired_no_credentials" or
              credential.get("state") != "credentials_saved"))):
        raise HTTPException(status_code=409, detail="old_link_package_state_changed")
    return link, credential


def _beneficiary_pk(cur, beneficiary_vault_id: str) -> bytes:
    cur.execute(
        """SELECT pk_vault_public,vault_handle,opaque_registration_record,
                  wrapped_mvk FROM vaults WHERE vault_id=%s FOR SHARE""",
        (beneficiary_vault_id,),
    )
    row = cur.fetchone()
    if (not row or row.get("pk_vault_public") is None or
            row.get("vault_handle") is None or
            row.get("opaque_registration_record") is None or
            row.get("wrapped_mvk") is None):
        raise HTTPException(status_code=409, detail="beneficiary_private_key_required")
    pk = bytes(row["pk_vault_public"])
    if len(pk) != 32:
        raise HTTPException(status_code=409, detail="beneficiary_private_key_required")
    return pk


def _stage_response(link_id: int, prior: dict, snapshot: str, pk_hash: bytes) -> dict:
    return {
        "beneficiary_link_id": link_id,
        "crypto_version": 2,
        "stage_revision": int(prior["stage_revision"]),
        "old_source_snapshot": snapshot,
        "beneficiary_pk_sha256": pk_hash.hex(),
        "state": "staged",
        "legacy_link_unchanged": True,
    }


def _offer_commitment(link_id: int, stage: dict) -> str:
    h = hashlib.sha256(b"linked-inheritance-beneficiary-keycheck/v1\x00")
    _feed(h, link_id)
    for name in (
        "owner_vault_id", "beneficiary_vault_id", "old_source_snapshot",
        "beneficiary_pk_sha256", "stage_revision", *_ENVELOPE_FIELDS,
    ):
        _feed(h, stage[name])
    return _b64(h.digest())


def _current_stage_for_beneficiary(cur, *, link: dict, credential: dict | None,
                                   pk_hash: bytes) -> dict:
    cur.execute(
        """SELECT owner_vault_id,beneficiary_vault_id,old_source_snapshot,
                  beneficiary_pk_sha256,encrypted_payload,payload_nonce,
                  wrapped_key,wrapping_ephemeral_pk,wrapping_nonce,
                  stage_revision,state,beneficiary_challenge_hash,
                  beneficiary_challenge_revision,
                  beneficiary_challenge_expires_at,
                  beneficiary_keycheck_revision,beneficiary_keycheck_at
             FROM beneficiary_link_v2_upgrades WHERE old_link_id=%s
             FOR UPDATE""",
        (link["id"],),
    )
    stage = cur.fetchone()
    if not stage:
        raise HTTPException(status_code=404, detail="upgrade_not_staged")
    if (str(stage["owner_vault_id"]) != str(link["passer_vault_id"]) or
            str(stage["beneficiary_vault_id"]) !=
            str(link["beneficiary_vault_id"]) or
            stage["state"] != "staged" or
            stage["old_source_snapshot"] != _source_snapshot(link, credential) or
            bytes(stage["beneficiary_pk_sha256"]) != pk_hash):
        raise HTTPException(status_code=409, detail="old_link_or_key_changed")
    return stage


def _challenge_aad(link_id: int, revision: int, commitment: str) -> bytes:
    return f"svaultai:old-link-v2-beneficiary-keycheck:v1:{link_id}:{revision}:{commitment}".encode("ascii")


def _encrypt_challenge(public_key: bytes, secret: bytes, aad: bytes) -> dict:
    ephemeral = X25519PrivateKey.generate()
    ephemeral_public = ephemeral.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    try:
        shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(public_key))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="beneficiary_key_invalid") from exc
    key = HKDF(
        algorithm=hashes.SHA256(), length=32,
        salt=ephemeral_public, info=_KEYCHECK_INFO,
    ).derive(shared)
    nonce = secrets.token_bytes(12)
    return {
        "challenge_ciphertext": _b64(AESGCM(key).encrypt(nonce, secret, aad)),
        "challenge_nonce": _b64(nonce),
        "challenge_ephemeral_pk": _b64(ephemeral_public),
    }


def _load_releasable_old_link(
    cur, *, link_id: int, beneficiary_vault_id: str,
) -> tuple[dict, dict, str]:
    """Lock old source before checking the existing approval/cooldown state."""
    cur.execute(
        f"SELECT {', '.join(_LINK_FIELDS)} FROM beneficiary_links "
        "WHERE id=%s AND beneficiary_vault_id=%s FOR UPDATE",
        (link_id, beneficiary_vault_id),
    )
    link = cur.fetchone()
    if (not link or link["status"] != "linked" or
            not isinstance(link["wrapped_vault_key"], str) or
            not link["wrapped_vault_key"] or
            link["wrapped_vault_key"] == ZK_BENEFICIARY_V2_MARKER or
            str(link["passer_vault_id"]) ==
            str(link["beneficiary_vault_id"])):
        raise HTTPException(status_code=404, detail="released_package_unavailable")
    state = link.get("pairing_state")
    now = datetime.now(timezone.utc)
    if state == "approved":
        if link.get("decision_at") is None:
            raise HTTPException(status_code=409, detail="approval_state_incomplete")
    elif state == "claimable":
        ends = link.get("cooldown_ends_at")
        if (link.get("access_requested_at") is None or
                ends is None or ends > now):
            raise HTTPException(status_code=409, detail="cooldown_not_complete")
    elif state != "released":
        raise HTTPException(status_code=409, detail="release_not_permitted")
    cur.execute(
        """SELECT id,owner_vault_id,crypto_version,encrypted_payload,
                  payload_nonce,wrapped_key,wrapping_ephemeral_pk,
                  wrapping_nonce,state,released_at
             FROM inheritance_credentials
            WHERE beneficiary_link_id=%s AND deleted_at IS NULL
            FOR UPDATE""",
        (link_id,),
    )
    credential = cur.fetchone()
    if (not credential or
            str(credential["owner_vault_id"]) != str(link["passer_vault_id"]) or
            int(credential["crypto_version"]) != 1 or
            credential["state"] != state or
            (state == "released" and credential.get("released_at") is None)):
        raise HTTPException(status_code=409, detail="old_package_state_changed")
    return link, credential, state


@router.post("/inheritance/old-link-v2/stage")
def stage_linked_v2_package(
    payload: StageLinkedV2Package,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    require_content_write(principal)
    envelope = _envelope(payload)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link, credential = _load_old_link(
            cur, link_id=payload.beneficiary_link_id,
            owner_vault_id=principal["vault_id"], lock=True,
        )
        pk_hash = hashlib.sha256(
            _beneficiary_pk(cur, str(link["beneficiary_vault_id"])),
        ).digest()
        if pk_hash.hex() != payload.expected_beneficiary_pk_sha256:
            raise HTTPException(status_code=409, detail="beneficiary_key_changed")
        snapshot = _source_snapshot(link, credential)
        cur.execute(
            """SELECT owner_vault_id,beneficiary_vault_id,
                      old_source_snapshot,beneficiary_pk_sha256,
                      encrypted_payload,payload_nonce,wrapped_key,
                      wrapping_ephemeral_pk,wrapping_nonce,
                      stage_revision,state
                 FROM beneficiary_link_v2_upgrades
                WHERE old_link_id=%s FOR UPDATE""",
            (payload.beneficiary_link_id,),
        )
        prior = cur.fetchone()
        if prior and (str(prior["owner_vault_id"]) != str(principal["vault_id"]) or
                      str(prior["beneficiary_vault_id"]) !=
                      str(link["beneficiary_vault_id"]) or
                      prior["state"] != "staged"):
            raise HTTPException(status_code=409, detail="old_link_upgrade_changed")
        same = bool(prior and prior["old_source_snapshot"] == snapshot and
                    bytes(prior["beneficiary_pk_sha256"]) == pk_hash and
                    all(bytes(prior[name]) == envelope[name]
                        for name in _ENVELOPE_FIELDS))
        if prior and not same and (
                payload.expected_stage_revision != int(prior["stage_revision"])):
            raise HTTPException(status_code=409, detail="stage_revision_required")
        if not prior and payload.expected_stage_revision is not None:
            raise HTTPException(status_code=409, detail="stage_revision_changed")
        consume_recent_zk_proof_on_cursor(payload.zk_proof_token, principal, cur)
        if prior is None:
            cur.execute(
                """INSERT INTO beneficiary_link_v2_upgrades (
                      old_link_id,owner_vault_id,beneficiary_vault_id,
                      old_source_snapshot,beneficiary_pk_sha256,
                      encrypted_payload,payload_nonce,wrapped_key,
                      wrapping_ephemeral_pk,wrapping_nonce)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING stage_revision""",
                (payload.beneficiary_link_id, principal["vault_id"],
                 link["beneficiary_vault_id"], snapshot, pk_hash,
                 *(envelope[name] for name in _ENVELOPE_FIELDS)),
            )
            revision = int(cur.fetchone()["stage_revision"])
        elif same:
            revision = int(prior["stage_revision"])
        else:
            cur.execute(
                """UPDATE beneficiary_link_v2_upgrades
                      SET old_source_snapshot=%s,beneficiary_pk_sha256=%s,
                          encrypted_payload=%s,payload_nonce=%s,
                          wrapped_key=%s,wrapping_ephemeral_pk=%s,
                          wrapping_nonce=%s,stage_revision=stage_revision+1,
                          beneficiary_challenge_hash=NULL,
                          beneficiary_challenge_revision=NULL,
                          beneficiary_challenge_expires_at=NULL,
                          beneficiary_keycheck_revision=NULL,
                          beneficiary_keycheck_at=NULL,updated_at=NOW()
                    WHERE old_link_id=%s AND owner_vault_id=%s
                      AND stage_revision=%s AND state='staged'
                    RETURNING stage_revision""",
                (snapshot, pk_hash,
                 *(envelope[name] for name in _ENVELOPE_FIELDS),
                 payload.beneficiary_link_id, principal["vault_id"],
                 payload.expected_stage_revision),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=409, detail="stage_revision_changed")
            revision = int(row["stage_revision"])
        conn.commit()
        return _stage_response(
            payload.beneficiary_link_id,
            {"stage_revision": revision}, snapshot, pk_hash,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/inheritance/old-link-v2/{link_id}/beneficiary-challenge")
def issue_beneficiary_key_challenge(
    link_id: int,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    """Prove the beneficiary can decrypt its own key, without releasing MVK."""
    _keycheck_enabled()
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link, credential = _load_old_link(
            cur, link_id=link_id, beneficiary_vault_id=principal["vault_id"],
            lock=True,
        )
        public_key = _beneficiary_pk(cur, str(link["beneficiary_vault_id"]))
        pk_hash = hashlib.sha256(public_key).digest()
        stage = _current_stage_for_beneficiary(
            cur, link=link, credential=credential, pk_hash=pk_hash,
        )
        revision = int(stage["stage_revision"])
        commitment = _offer_commitment(link_id, stage)
        secret = secrets.token_bytes(32)
        ciphertext = _encrypt_challenge(
            public_key, secret, _challenge_aad(link_id, revision, commitment),
        )
        expires_at = datetime.now(timezone.utc) + _CHALLENGE_LIFETIME
        cur.execute(
            """UPDATE beneficiary_link_v2_upgrades
                  SET beneficiary_challenge_hash=%s,
                      beneficiary_challenge_revision=%s,
                      beneficiary_challenge_expires_at=%s,updated_at=NOW()
                WHERE old_link_id=%s AND stage_revision=%s AND state='staged'""",
            (hashlib.sha256(secret).digest(), revision, expires_at,
             link_id, revision),
        )
        conn.commit()
        return {
            "beneficiary_link_id": link_id,
            "stage_revision": revision,
            "offer_commitment": commitment,
            "beneficiary_pk_sha256": pk_hash.hex(),
            "expires_at": expires_at.isoformat(),
            **ciphertext,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/inheritance/old-link-v2/beneficiary-keycheck")
def complete_beneficiary_key_check(
    payload: CompleteBeneficiaryKeyCheck,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    """Record private-key possession for exactly one unchanged stage."""
    _keycheck_enabled()
    secret = _decode(payload.challenge_secret, low=32, high=32)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link, credential = _load_old_link(
            cur, link_id=payload.beneficiary_link_id,
            beneficiary_vault_id=principal["vault_id"], lock=True,
        )
        pk_hash = hashlib.sha256(
            _beneficiary_pk(cur, str(link["beneficiary_vault_id"])),
        ).digest()
        stage = _current_stage_for_beneficiary(
            cur, link=link, credential=credential, pk_hash=pk_hash,
        )
        if (pk_hash.hex() != payload.expected_beneficiary_pk_sha256 or
                int(stage["stage_revision"]) != payload.stage_revision or
                _offer_commitment(payload.beneficiary_link_id, stage) !=
                payload.offer_commitment):
            raise HTTPException(status_code=409, detail="stage_revision_changed")
        expires_at = stage.get("beneficiary_challenge_expires_at")
        stored_hash = stage.get("beneficiary_challenge_hash")
        if (stored_hash is None or
                stage.get("beneficiary_challenge_revision") !=
                payload.stage_revision or
                expires_at is None or
                expires_at <= datetime.now(timezone.utc) or
                not hmac.compare_digest(
                    bytes(stored_hash), hashlib.sha256(secret).digest(),
                )):
            raise HTTPException(status_code=409, detail="beneficiary_challenge_invalid")
        consume_recent_zk_proof_on_cursor(
            payload.zk_proof_token, principal, cur,
        )
        cur.execute(
            """UPDATE beneficiary_link_v2_upgrades
                  SET beneficiary_keycheck_revision=%s,
                      beneficiary_keycheck_at=NOW(),
                      beneficiary_challenge_hash=NULL,
                      beneficiary_challenge_revision=NULL,
                      beneficiary_challenge_expires_at=NULL,updated_at=NOW()
                WHERE old_link_id=%s AND stage_revision=%s AND state='staged'""",
            (payload.stage_revision, payload.beneficiary_link_id,
             payload.stage_revision),
        )
        conn.commit()
        return {
            "beneficiary_link_id": payload.beneficiary_link_id,
            "stage_revision": payload.stage_revision,
            "offer_commitment": payload.offer_commitment,
            "beneficiary_key_possession_confirmed": True,
            "package_decryption_verified": False,
            "legacy_link_unchanged": True,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/inheritance/old-link-v2/{link_id}/readback")
def readback_linked_v2_package(
    link_id: int,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link, credential = _load_old_link(
            cur, link_id=link_id, owner_vault_id=principal["vault_id"],
            lock=False,
        )
        snapshot = _source_snapshot(link, credential)
        pk_hash = hashlib.sha256(
            _beneficiary_pk(cur, str(link["beneficiary_vault_id"])),
        ).digest()
        cur.execute(
            """SELECT beneficiary_vault_id,old_source_snapshot,beneficiary_pk_sha256,
                      encrypted_payload,payload_nonce,wrapped_key,
                      wrapping_ephemeral_pk,wrapping_nonce,
                      stage_revision,state
                 FROM beneficiary_link_v2_upgrades
                WHERE old_link_id=%s AND owner_vault_id=%s""",
            (link_id, principal["vault_id"]),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="upgrade_not_staged")
        if (row["state"] != "staged" or
                str(row["beneficiary_vault_id"]) !=
                str(link["beneficiary_vault_id"]) or
                row["old_source_snapshot"] != snapshot or
                bytes(row["beneficiary_pk_sha256"]) != pk_hash):
            raise HTTPException(status_code=409, detail="old_link_or_key_changed")
        return {
            **_stage_response(link_id, row, snapshot, pk_hash),
            **{name: _b64(bytes(row[name])) for name in _ENVELOPE_FIELDS},
        }
    finally:
        conn.close()


@router.post("/inheritance/old-link-v2/{link_id}/released-package")
def read_released_linked_v2_package(
    link_id: int,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    """Release only after the existing owner approval or completed cooldown.

    This returns the staged V2 ciphertext, not an owner plaintext key. The old
    credential package and wrapped key remain available while the beneficiary
    verifies decryption locally; this route does not retire the old protocol.
    """
    _release_readback_enabled()
    if link_id <= 0:
        raise HTTPException(status_code=404, detail="not_found")
    conn = get_db()
    transitioned = False
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link, credential, state = _load_releasable_old_link(
            cur, link_id=link_id,
            beneficiary_vault_id=principal["vault_id"],
        )
        pk_hash = hashlib.sha256(
            _beneficiary_pk(cur, str(link["beneficiary_vault_id"])),
        ).digest()
        cur.execute(
            """SELECT owner_vault_id,beneficiary_vault_id,
                      old_source_snapshot,beneficiary_pk_sha256,
                      encrypted_payload,payload_nonce,wrapped_key,
                      wrapping_ephemeral_pk,wrapping_nonce,
                      stage_revision,state,beneficiary_keycheck_revision,
                      beneficiary_keycheck_at
                 FROM beneficiary_link_v2_upgrades
                WHERE old_link_id=%s FOR UPDATE""",
            (link_id,),
        )
        stage = cur.fetchone()
        if (not stage or stage["state"] != "staged" or
                str(stage["owner_vault_id"]) != str(link["passer_vault_id"]) or
                str(stage["beneficiary_vault_id"]) !=
                str(link["beneficiary_vault_id"]) or
                stage["old_source_snapshot"] !=
                _source_snapshot(link, credential) or
                bytes(stage["beneficiary_pk_sha256"]) != pk_hash or
                stage["beneficiary_keycheck_revision"] !=
                stage["stage_revision"] or
                stage["beneficiary_keycheck_at"] is None):
            raise HTTPException(status_code=409, detail="v2_package_not_verified")
        enforce_export_rate_limit(vault_id=str(principal["vault_id"]))
        released_at = credential.get("released_at")
        if state != "released":
            released_at = datetime.now(timezone.utc)
            cur.execute(
                """UPDATE inheritance_credentials
                      SET released_at=COALESCE(released_at,%s),
                          state='released',updated_at=NOW()
                    WHERE id=%s AND deleted_at IS NULL""",
                (released_at, credential["id"]),
            )
            cur.execute(
                """UPDATE beneficiary_links SET pairing_state='released',
                          updated_at=NOW() WHERE id=%s""",
                (link_id,),
            )
            transitioned = True
        result = {
            "beneficiary_link_id": link_id,
            "owner_vault_id": str(link["passer_vault_id"]),
            "crypto_version": 2,
            "stage_revision": int(stage["stage_revision"]),
            "offer_commitment": _offer_commitment(link_id, stage),
            "old_source_snapshot": stage["old_source_snapshot"],
            "pairing_state": "released",
            "released_at": released_at.isoformat(),
            "legacy_package_preserved": True,
            "package_decryption_verified": False,
            **{name: _b64(bytes(stage[name])) for name in _ENVELOPE_FIELDS},
        }
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if transitioned:
        from routes.inheritance_release_routes import (
            _notify, _NOTIFY_KIND_RELEASED,
        )
        _notify(
            str(principal["vault_id"]), _NOTIFY_KIND_RELEASED,
            title="Inheritance: private package released",
            body="The encrypted inheritance package is available to open.",
            metadata={"beneficiary_link_id": link_id},
        )
    return result
