"""Backend contract tests for the inheritance credential escrow.

These tests do not require a live database. They exercise:

  * the router surface (paths, verbs, wire schemas);
  * the operator-safe error catalog (every INH-* raises the
    documented HTTPException detail and status);
  * the byte-length invariants of the ``inheritance_credentials``
    columns (min/max, exact-nonce, exact-X25519-pk);
  * the log redaction filter (values of credential-shaped keys are
    replaced before a formatter sees them);
  * a source-scan that no plaintext ``username``/``pin`` column
    was added to any migration or route module.

DB-side integration (the state machine, SELECT-FOR-UPDATE races,
the LEFT JOIN on /beneficiary/list-mine) is covered by the Docker
integration suite that runs against a Postgres container. The
in-process tests here are the fast contract layer.
"""

from __future__ import annotations

import io
import logging
import re

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from routes.inheritance_credential_routes import (
    DeleteCredentialPackageRequest,
    ReplaceCredentialPackageRequest,
    SaveCredentialPackageRequest,
    _b64url_decode_bytes,
    _NONCE_BYTES,
    _X25519_PUB_BYTES,
    _ENCRYPTED_PAYLOAD_MIN,
    _ENCRYPTED_PAYLOAD_MAX,
    router as inh_router,
)

from inheritance_error_codes import (
    INHERR,
    _InheritanceRedactionFilter,
    _scrub_mapping,
    inheritance_http_error,
    install_inheritance_redaction,
)


# ---------------------------------------------------------------------
# Router surface
# ---------------------------------------------------------------------


def test_router_exposes_only_phase_one_endpoints() -> None:
    paths = {getattr(r, "path", None) for r in inh_router.routes}
    expected = {
        "/inheritance/credentials/save",
        "/inheritance/credentials/replace",
        "/inheritance/credentials/delete",
        "/inheritance/credentials/status",
        "/inheritance/beneficiary/{link_id}/pubkey",
    }
    assert expected.issubset(paths), (
        f"missing endpoints: {sorted(expected - paths)}"
    )
    # Phase 2 endpoints must NOT be exposed until they land.
    forbidden = {
        "/inheritance/access/request",
        "/inheritance/access/approve",
        "/inheritance/access/cancel",
        "/inheritance/access/claim",
        "/inheritance/credentials/retrieve",
        "/inheritance/device/authorize",
        "/inheritance/device/consume",
    }
    leaked = forbidden & paths
    assert not leaked, (
        f"phase-2 endpoints must not appear in phase-1 router: "
        f"{sorted(leaked)}"
    )


# ---------------------------------------------------------------------
# Byte-length invariants
# ---------------------------------------------------------------------


def _b64u(raw: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_b64url_decode_enforces_exact_length() -> None:
    with pytest.raises(HTTPException) as ei:
        _b64url_decode_bytes(_b64u(b"\x00" * 31), exact=_X25519_PUB_BYTES)
    assert ei.value.status_code == INHERR.CRED_INVALID_PACKAGE.status
    assert ei.value.detail["code"] == INHERR.CRED_INVALID_PACKAGE.code


def test_b64url_decode_enforces_range() -> None:
    with pytest.raises(HTTPException):
        _b64url_decode_bytes(
            _b64u(b"\x00" * (_ENCRYPTED_PAYLOAD_MIN - 1)),
            lo=_ENCRYPTED_PAYLOAD_MIN,
            hi=_ENCRYPTED_PAYLOAD_MAX,
        )
    with pytest.raises(HTTPException):
        _b64url_decode_bytes(
            _b64u(b"\x00" * (_ENCRYPTED_PAYLOAD_MAX + 1)),
            lo=_ENCRYPTED_PAYLOAD_MIN,
            hi=_ENCRYPTED_PAYLOAD_MAX,
        )


def test_b64url_decode_operator_safe_on_malformed() -> None:
    with pytest.raises(HTTPException) as ei:
        _b64url_decode_bytes("!!! not base64 !!!",
                              exact=_NONCE_BYTES)
    assert ei.value.status_code == 400
    assert ei.value.detail["code"] == "INH-CRED-004"
    # Wire response must not carry any parser internal:
    detail = ei.value.detail
    assert "binascii" not in str(detail)
    assert "traceback" not in str(detail).lower()


# ---------------------------------------------------------------------
# Pydantic request-model contract
# ---------------------------------------------------------------------


def test_save_request_rejects_missing_fields() -> None:
    with pytest.raises(ValidationError):
        SaveCredentialPackageRequest()


def test_save_request_rejects_zero_link_id() -> None:
    with pytest.raises(ValidationError):
        SaveCredentialPackageRequest(
            beneficiary_link_id=0,
            crypto_version=1,
            encrypted_payload="AA",
            payload_nonce="AA",
            wrapped_key="AA",
            wrapping_ephemeral_pk="AA",
            wrapping_nonce="AA",
        )


def test_save_request_rejects_unsupported_crypto_version() -> None:
    with pytest.raises(ValidationError):
        SaveCredentialPackageRequest(
            beneficiary_link_id=1,
            crypto_version=2,  # only v1 is allowed at the wire layer
            encrypted_payload="AA",
            payload_nonce="AA",
            wrapped_key="AA",
            wrapping_ephemeral_pk="AA",
            wrapping_nonce="AA",
        )


def test_replace_request_shares_shape_with_save() -> None:
    payload = ReplaceCredentialPackageRequest(
        beneficiary_link_id=1,
        crypto_version=1,
        encrypted_payload=_b64u(b"\x00" * 32),
        payload_nonce=_b64u(b"\x00" * 12),
        wrapped_key=_b64u(b"\x00" * 32),
        wrapping_ephemeral_pk=_b64u(b"\x00" * 32),
        wrapping_nonce=_b64u(b"\x00" * 12),
    )
    assert payload.crypto_version == 1


def test_delete_request_only_needs_link_id() -> None:
    payload = DeleteCredentialPackageRequest(beneficiary_link_id=5)
    assert payload.beneficiary_link_id == 5


def test_credential_package_repr_never_contains_ciphertext() -> None:
    payload = SaveCredentialPackageRequest(
        beneficiary_link_id=42,
        crypto_version=1,
        encrypted_payload="SENTINEL_CIPHERTEXT_MUST_NOT_LEAK",
        payload_nonce=_b64u(b"\x00" * 12),
        wrapped_key=_b64u(b"\x00" * 32),
        wrapping_ephemeral_pk=_b64u(b"\x00" * 32),
        wrapping_nonce=_b64u(b"\x00" * 12),
    )
    s = repr(payload)
    assert "SENTINEL_CIPHERTEXT_MUST_NOT_LEAK" not in s
    assert "link=42" in s


# ---------------------------------------------------------------------
# Error catalog
# ---------------------------------------------------------------------


def test_every_error_carries_a_stable_reference() -> None:
    seen = set()
    for name in dir(INHERR):
        if name.startswith("_"):
            continue
        code = getattr(INHERR, name)
        # Every code must have a 3-part identifier and a non-empty
        # user message.
        assert re.match(r"^INH-[A-Z]+-\d+$", code.code), code
        assert code.user_message.strip()
        assert 400 <= code.status < 500
        # No two codes may share an identifier.
        assert code.code not in seen
        seen.add(code.code)


def test_inheritance_http_error_returns_operator_safe_detail(
    caplog,
) -> None:
    caplog.set_level(logging.WARNING, logger="vaultai.inheritance")
    exc = inheritance_http_error(
        INHERR.CRED_LINK_NOT_FOUND,
        log_details={"link_id": 7, "owner_tail": "abcdef"},
    )
    assert exc.status_code == 404
    assert exc.detail["code"] == "INH-CRED-001"
    # The user-visible message must never contain the log-details
    # dict (owner_tail, link_id, etc.).
    assert "abcdef" not in exc.detail["message"]
    assert "link_id" not in exc.detail["message"]
    # The log line must contain the reference for grep-ability.
    assert any(
        "INH-CRED-001" in rec.getMessage() for rec in caplog.records
    )


# ---------------------------------------------------------------------
# Log redaction
# ---------------------------------------------------------------------


def test_scrub_mapping_replaces_credential_keys() -> None:
    scrubbed = _scrub_mapping({
        "vault_id_tail": "abcdef",
        "pin": "89262828",
        "credential_bytes": b"\x00\x01\x02",
        "encrypted_payload": "SENTINEL_ENCPAYLOAD",
        "wrapped_key": "SENTINEL_WRAP",
        "wrapping_nonce": "SENTINEL_NONCE",
        "wrapping_ephemeral_pk": "SENTINEL_PK",
        "authorization": "Bearer secret",
        "session_token": "tok_1",
        "safe_field": "keep_me",
        "nested": {"pin": "1234", "vault_id_tail": "aabbcc"},
    })
    # Sensitive fields are redacted verbatim; benign fields are
    # untouched.
    assert scrubbed["pin"] == "<redacted>"
    assert scrubbed["credential_bytes"] == "<redacted>"
    assert scrubbed["encrypted_payload"] == "<redacted>"
    assert scrubbed["wrapped_key"] == "<redacted>"
    assert scrubbed["wrapping_nonce"] == "<redacted>"
    assert scrubbed["wrapping_ephemeral_pk"] == "<redacted>"
    assert scrubbed["authorization"] == "<redacted>"
    assert scrubbed["session_token"] == "<redacted>"
    assert scrubbed["safe_field"] == "keep_me"
    assert scrubbed["vault_id_tail"] == "abcdef"
    # Nested dicts are scrubbed recursively.
    assert scrubbed["nested"]["pin"] == "<redacted>"
    assert scrubbed["nested"]["vault_id_tail"] == "aabbcc"


def test_redaction_filter_scrubs_before_formatter() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(_InheritanceRedactionFilter())

    logger = logging.getLogger("vaultai.test.redaction.unit")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        logger.info(
            "escrow row saved link=%(link_id)s pin=%(pin)s",
            {"link_id": 42, "pin": "SENTINEL_PIN"},
        )
        rendered = stream.getvalue()
        assert "SENTINEL_PIN" not in rendered
        # The benign link_id must survive.
        assert "42" in rendered
    finally:
        logger.removeHandler(handler)


def test_install_redaction_is_idempotent() -> None:
    install_inheritance_redaction()
    install_inheritance_redaction()  # must not raise or double-add
    root = logging.getLogger("")
    matches = [
        f for f in root.filters
        if isinstance(f, _InheritanceRedactionFilter)
    ]
    assert len(matches) <= 1


# ---------------------------------------------------------------------
# Source-scan invariants
# ---------------------------------------------------------------------


_PROJECT_ROOT = None


def _find_root() -> str:
    global _PROJECT_ROOT
    if _PROJECT_ROOT is not None:
        return _PROJECT_ROOT
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    _PROJECT_ROOT = here
    return here


def test_no_plaintext_credential_column_in_migrations() -> None:
    """No migration in the escrow feature may declare a plaintext
    ``username`` or ``pin`` column with a Postgres type. Only DDL
    lines are checked (docstring / comment text is fine).
    """
    import os
    root = os.path.join(_find_root(), "migrations", "versions")
    # A DDL column definition: identifier immediately followed by a
    # concrete Postgres type keyword. We check on a single line so
    # narrative prose in docstrings does not trigger.
    _PG_TYPES = (
        r"TEXT|VARCHAR|CHARACTER|CHAR|BYTEA|INTEGER|BIGINT|SMALLINT|"
        r"BOOLEAN|BOOL|TIMESTAMPTZ|TIMESTAMP|DATE|UUID|JSON|JSONB|"
        r"NUMERIC|SERIAL|BIGSERIAL"
    )
    forbidden = re.compile(
        rf"(?im)^\s*(?:username|pin)\s+(?:{_PG_TYPES})\b",
    )
    offenders = []
    for name in os.listdir(root):
        if not name.endswith(".py"):
            continue
        # Only look at the escrow migration.
        if "credential_escrow" not in name:
            continue
        with open(os.path.join(root, name), "r", encoding="utf-8") as f:
            src = f.read()
        if forbidden.search(src):
            offenders.append(name)
    assert offenders == [], (
        f"migration {offenders} declares a plaintext credential "
        "column — every credential byte must stay wrapped."
    )


def test_credential_route_never_selects_plaintext_username_or_pin() -> None:
    """Static guard: the escrow route module must never issue a
    SELECT statement that mentions ``username`` or ``pin`` as a
    column of ``inheritance_credentials``. Those fields exist only
    as encrypted bytes inside ``encrypted_payload``.
    """
    import os
    path = os.path.join(
        _find_root(), "routes",
        "inheritance_credential_routes.py",
    )
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    # Any occurrence of the words ``username`` or ``pin`` as SQL
    # column identifiers alongside inheritance_credentials.
    bad = re.compile(
        r"(?ix)inheritance_credentials[^;]*?\b(username|pin)\b",
    )
    match = bad.search(src)
    assert match is None, (
        f"escrow routes reference plaintext column {match.group(1)} "
        "of inheritance_credentials — this must never happen."
    )
