"""Cross-language OPAQUE wire-interop test.

Verifies that the Python pyo3 wrapper (backend, built from Meta's
audited opaque-ke Rust crate) produces the same session key as
``@serenity-kit/opaque`` (frontend, WASM built from the same crate)
when both sides run a full RFC 9807 handshake against each other.

The test is auto-skipped in environments that lack either the
pyo3 wheel or Node. It runs in the Dockerfile builder stage (both
present) and in any Linux CI that installs Node.

Fixture path:
  * ``$VAULTAI_INTEROP_NODE_MODULES`` — directory containing
    ``@serenity-kit/opaque`` under its ``node_modules/``.
    Defaults to ``$HOME/scratch-opaque-npm`` for local dev.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


_wheel = pytest.importorskip(
    "vaultai_opaque_server",
    reason="vaultai_opaque_server pyo3 wheel unavailable; interop only "
           "runs where the Docker builder stage has installed it.",
)


def _node_available() -> bool:
    return shutil.which("node") is not None


if not _node_available():
    pytest.skip(
        "node is not on PATH; wire-interop test requires Node runtime",
        allow_module_level=True,
    )

_NODE_EXE = shutil.which("node")


_DEFAULT_NPM_DIR = Path.home() / "scratch-opaque-npm"
_NPM_DIR = Path(
    os.environ.get("VAULTAI_INTEROP_NODE_MODULES", str(_DEFAULT_NPM_DIR)),
)
_SERENITY_PACKAGE = _NPM_DIR / "node_modules" / "@serenity-kit" / "opaque"

if not _SERENITY_PACKAGE.exists():
    pytest.skip(
        f"@serenity-kit/opaque not found under {_SERENITY_PACKAGE}. "
        "Run `npm install @serenity-kit/opaque` in "
        f"{_NPM_DIR} to enable the interop test.",
        allow_module_level=True,
    )


import opaque_server_module  # noqa: E402


PASSWORD = "correct-horse-battery-staple-1234567890"
CREDENTIAL_ID_STR = "VLT-TEST-INTEROP-1234-5678-9012"


def _client_script() -> str:
    return textwrap.dedent(
        f"""
        const opaque = require({str(_SERENITY_PACKAGE).replace("\\\\", "/") !r});
        opaque.ready.then(async () => {{
          const {{client}} = opaque;
          const input = JSON.parse(process.env.INPUT || "{{}}");
          const stage = input.stage;
          let out;
          switch (stage) {{
            case "register-start": {{
              const r = client.startRegistration({{password: input.password}});
              out = {{
                clientRegistrationState: r.clientRegistrationState,
                registrationRequest: r.registrationRequest,
              }};
              break;
            }}
            case "register-finish": {{
              const r = client.finishRegistration({{
                password: input.password,
                registrationResponse: input.registrationResponse,
                clientRegistrationState: input.clientRegistrationState,
                identifiers: input.identifiers,
              }});
              out = {{
                registrationRecord: r.registrationRecord,
                exportKey: r.exportKey,
              }};
              break;
            }}
            case "login-start": {{
              const r = client.startLogin({{password: input.password}});
              out = {{
                clientLoginState: r.clientLoginState,
                startLoginRequest: r.startLoginRequest,
              }};
              break;
            }}
            case "login-finish": {{
              const r = client.finishLogin({{
                clientLoginState: input.clientLoginState,
                loginResponse: input.loginResponse,
                password: input.password,
                identifiers: input.identifiers,
              }});
              out = {{
                finishLoginRequest: r.finishLoginRequest,
                sessionKey: r.sessionKey,
                exportKey: r.exportKey,
              }};
              break;
            }}
            default:
              throw new Error("unknown stage " + stage);
          }}
          process.stdout.write(JSON.stringify(out));
        }}).catch((err) => {{
          console.error("CLIENT_ERR", err);
          process.exit(1);
        }});
        """
    )


def _client_call(stage: str, **kwargs) -> dict:
    script = _client_script()
    payload = {"stage": stage, **kwargs}
    child_env = dict(os.environ)
    for unsafe_name in ("NODE_OPTIONS", "OPENSSL_CONF", "RANDFILE"):
        child_env.pop(unsafe_name, None)
    child_env["INPUT"] = json.dumps(payload)
    proc = subprocess.run(
        [_NODE_EXE, "-e", script],
        input="",
        env=child_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"node client failed: {proc.stderr}")
    return json.loads(proc.stdout)


def _b64url_encode_bytes(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode_str(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@pytest.mark.opaque_interop
def test_full_opaque_round_trip_client_serenity_kit_server_opaque_ke(
    monkeypatch,
) -> None:
    """Full OPAQUE registration + login: client is serenity-kit (WASM),
    server is our pyo3 wrapper over the same opaque-ke crate. Both
    sides derive identical session_key and export_key.
    """
    setup_bytes = _wheel.server_setup_new()
    monkeypatch.setenv(
        "VAULTAI_OPAQUE_SERVER_SETUP",
        _b64url_encode_bytes(setup_bytes),
    )
    opaque_server_module.clear_setup_cache_for_tests()

    reg_start = _client_call(
        "register-start", password=PASSWORD,
    )
    registration_request = _b64url_decode_str(reg_start["registrationRequest"])

    registration_response = opaque_server_module.registration_start(
        registration_request,
        CREDENTIAL_ID_STR.encode("utf-8"),
    )
    reg_response_b64 = _b64url_encode_bytes(registration_response)

    reg_finish = _client_call(
        "register-finish",
        password=PASSWORD,
        registrationResponse=reg_response_b64,
        clientRegistrationState=reg_start["clientRegistrationState"],
    )
    registration_upload = _b64url_decode_str(
        reg_finish["registrationRecord"],
    )
    export_key_registration = reg_finish["exportKey"]

    server_record = opaque_server_module.registration_finish(
        registration_upload,
    )
    assert isinstance(server_record, (bytes, bytearray))
    assert len(server_record) > 0

    login_start = _client_call(
        "login-start", password=PASSWORD,
    )
    credential_request = _b64url_decode_str(login_start["startLoginRequest"])

    ke2, server_state = opaque_server_module.login_start(
        server_record,
        credential_request,
        CREDENTIAL_ID_STR.encode("utf-8"),
    )

    login_finish = _client_call(
        "login-finish",
        password=PASSWORD,
        loginResponse=_b64url_encode_bytes(ke2),
        clientLoginState=login_start["clientLoginState"],
    )
    session_key_client = login_finish["sessionKey"]
    export_key_login = login_finish["exportKey"]

    session_key_server = opaque_server_module.login_finish(
        server_state,
        _b64url_decode_str(login_finish["finishLoginRequest"]),
    )

    assert _b64url_encode_bytes(session_key_server) == session_key_client, (
        "OPAQUE wire-interop FAILED: server session_key does not match "
        "client session_key. Verify that both sides use "
        "Ristretto255-SHA512-Argon2id + TripleDH and the SAME credential "
        "identifier bytes."
    )
    assert export_key_login == export_key_registration, (
        "OPAQUE export_key mismatch across registration vs login runs; "
        "opaque-ke should produce identical export_key for identical "
        "password + record on the client."
    )
