"""VaultAI server-side OPAQUE (RFC 9807) module.

Thin Python wrapper over the ``vaultai_opaque_server`` pyo3 wheel,
which in turn is a byte-in / byte-out shim over Meta's audited
``opaque-ke`` (RFC 9807) Rust crate. This module adds:

* Persistent ``ServerSetup`` loading from environment (never DB — the
  setup contains the OPRF master secret and MUST live only in the
  server's secret manager).
* Structured exceptions with closed-set error reasons (no plaintext
  ever surfaces in messages).
* Import-time diagnostic when the wheel is not installed, printed
  with an actionable message. This lets local Windows dev boxes that
  cannot compile the wheel due to WDAC continue to import the module
  and run non-crypto tests; any actual OPAQUE call raises
  ``OpaqueWheelMissing`` with the exact remediation.

The ciphersuite in the underlying Rust crate is
Ristretto255-SHA512-Argon2id — the same suite used by
``@serenity-kit/opaque`` (WASM built from the same ``opaque-ke``) on
the Web client, so wire-level interoperability is guaranteed.

The module contains NO cryptography. Every operation is delegated to
the audited crate.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Optional


logger = logging.getLogger(__name__)


class OpaqueError(Exception):
    """Base class for all OPAQUE server errors."""


class OpaqueWheelMissing(OpaqueError):
    """Raised when the vaultai_opaque_server wheel is not importable.

    Actionable message: build the wheel via the Dockerfile builder
    stage, or run the backend under Docker. Local Windows dev cannot
    compile the wheel because Windows Defender Application Control
    (WDAC) blocks Rust build-script execution; this is a documented
    environmental constraint and not a code bug.
    """


class OpaqueSetupMissing(OpaqueError):
    """Raised when VAULTAI_OPAQUE_SERVER_SETUP env var is unset or empty.

    The server setup contains the OPRF master secret. It must be
    generated ONCE (via `python -m vault_ai_backend.opaque_server_module
    --print-new-setup`) and injected via the deployment secret store.
    Never persist it in the database.
    """


class OpaqueProtocolError(OpaqueError):
    """Raised when the underlying Rust crate rejects a message.

    The wrapped error message is deliberately terse — the crate's
    verbose errors could echo protocol state that we do not want in
    logs. The route handler translates this into a generic HTTP 401
    with reason='opaque_finalize_failed'.
    """


try:
    import vaultai_opaque_server as _wheel
    _WHEEL_AVAILABLE = True
    _WHEEL_IMPORT_ERROR: Optional[Exception] = None
except ImportError as exc:
    _wheel = None
    _WHEEL_AVAILABLE = False
    _WHEEL_IMPORT_ERROR = exc
    logger.warning(
        "[OPAQUE] vaultai_opaque_server wheel not importable: %s. "
        "Any /auth/zk-* call will fail with OpaqueWheelMissing. "
        "Local Windows dev boxes cannot build this wheel due to WDAC "
        "— use Docker or WSL. Non-crypto tests remain unaffected.",
        exc,
    )


def _require_wheel() -> None:
    if not _WHEEL_AVAILABLE:
        raise OpaqueWheelMissing(
            "vaultai_opaque_server wheel is not installed in this "
            "Python environment. Build it via the Dockerfile builder "
            "stage or a Linux/WSL dev environment. Original import "
            f"error: {_WHEEL_IMPORT_ERROR!r}"
        )


_SETUP_ENV_VAR = "VAULTAI_OPAQUE_SERVER_SETUP"


def _load_setup_bytes() -> bytes:
    raw = os.environ.get(_SETUP_ENV_VAR, "").strip()
    if not raw:
        raise OpaqueSetupMissing(
            f"Set {_SETUP_ENV_VAR} to the base64url ServerSetup bytes "
            "produced by opaque_server_module --print-new-setup. This "
            "value is the deployment's OPAQUE OPRF master secret and "
            "must live only in the secret manager, never in the DB."
        )
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception as exc:
        raise OpaqueSetupMissing(
            f"{_SETUP_ENV_VAR} is not valid base64url: {exc!r}"
        ) from exc


_setup_bytes_cache: Optional[bytes] = None


def _cached_setup() -> bytes:
    global _setup_bytes_cache
    if _setup_bytes_cache is None:
        _setup_bytes_cache = _load_setup_bytes()
    return _setup_bytes_cache


def clear_setup_cache_for_tests() -> None:
    """Reset the setup cache. Test-only."""
    global _setup_bytes_cache
    _setup_bytes_cache = None


def generate_new_server_setup_bytes() -> bytes:
    """Generate a fresh long-term ServerSetup. Call ONCE per deployment.
    The result is a long random byte string that must be stored as a
    deployment secret (env / secret manager), never in the DB.
    """
    _require_wheel()
    return _wheel.server_setup_new()


def registration_start(
    ke1_msg: bytes,
    credential_id: bytes,
) -> bytes:
    """OPAQUE registration round 1 (server side).

    Consumes the client's ``RegistrationRequest`` and returns the
    ``RegistrationResponse`` bytes to send back. Uses the process-cached
    long-term ServerSetup.
    """
    _require_wheel()
    try:
        return _wheel.server_registration_start(
            _cached_setup(), ke1_msg, credential_id,
        )
    except ValueError as exc:
        raise OpaqueProtocolError("registration_start rejected") from exc


def registration_finish(ke3_msg: bytes) -> bytes:
    """OPAQUE registration round 2 (server side).

    Consumes the client's ``RegistrationUpload`` and returns the
    serialized registration record for storage in
    ``vault_zk_state.opaque_registration_record``.
    """
    _require_wheel()
    try:
        return _wheel.server_registration_finish(ke3_msg)
    except ValueError as exc:
        raise OpaqueProtocolError("registration_finish rejected") from exc


def login_start(
    record_bytes: bytes,
    ke1_msg: bytes,
    credential_id: bytes,
) -> tuple[bytes, bytes]:
    """OPAQUE login round 1 (server side).

    Consumes the client's ``CredentialRequest`` (KE1). Returns a pair:

    * ``ke2_bytes`` — the ``CredentialResponse`` bytes to send back
      to the client.
    * ``server_state_bytes`` — opaque server state that MUST be
      stored in a short-TTL slot keyed by the client's ephemeral
      session id and passed back at login_finish. It contains
      protocol-internal state, not a secret; but treat it as an
      opaque blob and do not log it.
    """
    _require_wheel()
    try:
        return _wheel.server_login_start(
            _cached_setup(), record_bytes, ke1_msg, credential_id,
        )
    except ValueError as exc:
        raise OpaqueProtocolError("login_start rejected") from exc


def login_finish(
    server_state_bytes: bytes,
    ke3_msg: bytes,
) -> bytes:
    """OPAQUE login round 2 (server side).

    Consumes the client's ``CredentialFinalization`` (KE3) and returns
    the shared session key. The route handler must NOT log this value.
    It is used only to encrypt the wrapped MVK for return to the
    client (defense-in-depth over TLS).
    """
    _require_wheel()
    try:
        return _wheel.server_login_finish(server_state_bytes, ke3_msg)
    except ValueError as exc:
        raise OpaqueProtocolError("login_finish rejected") from exc


def wheel_available() -> bool:
    """Return True if the pyo3 wheel imported successfully."""
    return _WHEEL_AVAILABLE


def wheel_import_error() -> Optional[Exception]:
    """Return the ImportError object caught at import time, if any."""
    return _WHEEL_IMPORT_ERROR


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="OPAQUE server setup ops CLI.",
    )
    parser.add_argument(
        "--print-new-setup", action="store_true",
        help="Generate a fresh ServerSetup and print it in base64url "
             "format ready to be pasted into VAULTAI_OPAQUE_SERVER_SETUP. "
             "The value is the OPRF master secret — handle it as "
             "a deployment-tier secret.",
    )
    args = parser.parse_args()
    if args.print_new_setup:
        setup = generate_new_server_setup_bytes()
        encoded = base64.urlsafe_b64encode(setup).decode("ascii").rstrip("=")
        print(encoded)
    else:
        parser.print_help()


__all__ = [
    "OpaqueError",
    "OpaqueWheelMissing",
    "OpaqueSetupMissing",
    "OpaqueProtocolError",
    "clear_setup_cache_for_tests",
    "generate_new_server_setup_bytes",
    "registration_start",
    "registration_finish",
    "login_start",
    "login_finish",
    "wheel_available",
    "wheel_import_error",
]
