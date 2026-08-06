"""End-to-end regression test for the 7bcaf81 production failure.

Symptom (production, 7bcaf81):
    every login attempt — including a freshly registered account,
    with the exact PIN the user just typed — surfaces "Wrong
    username or PIN." The client-side diagnostic pinpointed
    ``opaque_finish_login`` as the failing step and the JS-side
    signature ``Cannot read properties of undefined (reading
    'finishLoginRequest')``, meaning ``client.finishLogin(...)``
    returned undefined.

Hypothesis:
    the frontend passes ``identifiers.client = credentialId`` in
    both ``finishRegistration`` and ``finishLogin``, but the Rust
    backend calls ``ServerLogin::start(..., ServerLoginParameters::
    default())`` — identifiers set to None. Per RFC 9807 the OPAQUE
    AKE binds ``identifiers.client / .server`` into the 3DH key
    exchange transcript. A mismatch makes the client's finish step
    unable to verify the server response; the JS library then
    silently returns undefined.

What this test proves:
    1. With identifiers.client set on the CLIENT and no matching
       identifier on the SERVER (the pre-fix production config),
       ``login_finish`` REJECTS the client's ke3 payload.
    2. Without identifiers.client on either side (the fix
       configuration, matching test_opaque_wire_interop.py), the
       full register + login round-trip succeeds and the two
       session_keys match.

Both cases are exercised against the SAME server_setup and the
SAME OPAQUE library on both sides, so any observed difference is
directly attributable to the identifier parameter — not to a
version skew, a randomness issue, or a normalization bug.

Skips:
    * without the ``vaultai_opaque_server`` pyo3 wheel (Windows dev
      cannot compile it),
    * without ``node`` on PATH (needed to run the WASM client),
    * without ``@serenity-kit/opaque`` in
      ``$VAULTAI_INTEROP_NODE_MODULES/node_modules/``.
    Skips are NOT completion evidence; the Docker builder stage or
    a Linux CI must run this test.
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
    reason="pyo3 wheel unavailable; the Docker builder stage runs this test.",
)


if shutil.which("node") is None:
    pytest.skip("node not on PATH", allow_module_level=True)

_NODE_EXE = shutil.which("node")

_DEFAULT_NPM_DIR = Path.home() / "scratch-opaque-npm"
_NPM_DIR = Path(
    os.environ.get("VAULTAI_INTEROP_NODE_MODULES", str(_DEFAULT_NPM_DIR)),
)
_SERENITY = _NPM_DIR / "node_modules" / "@serenity-kit" / "opaque"
if not _SERENITY.exists():
    pytest.skip(
        f"@serenity-kit/opaque not found under {_SERENITY}",
        allow_module_level=True,
    )


import opaque_server_module  # noqa: E402


PASSWORD = "6284095173"
CRED_ID_STR = "VLT-MISM-ATCH-TEST-0000-0000-0000"


def _b64u_enc(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_dec(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _client_script() -> str:
    """Node script that drives the @serenity-kit/opaque WASM client
    through one register or login stage. The exact identifiers used
    are chosen by the caller so the same script exercises both the
    broken (client-sends-identifiers, server-doesn't) and fixed
    (both-omit-identifiers) configurations.
    """
    return textwrap.dedent(
        f"""
        const opaque = require({str(_SERENITY).replace("\\\\", "/") !r});
        opaque.ready.then(async () => {{
          const {{client}} = opaque;
          const input = JSON.parse(process.env.INPUT || "{{}}");
          const stage = input.stage;
          const withIds = input.withIdentifiers === true;
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
              const params = {{
                password: input.password,
                registrationResponse: input.registrationResponse,
                clientRegistrationState: input.clientRegistrationState,
              }};
              if (withIds) {{
                params.identifiers = {{ client: input.credentialId }};
              }}
              const r = client.finishRegistration(params);
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
              const params = {{
                clientLoginState: input.clientLoginState,
                loginResponse: input.loginResponse,
                password: input.password,
              }};
              if (withIds) {{
                params.identifiers = {{ client: input.credentialId }};
              }}
              const r = client.finishLogin(params);
              if (r === undefined) {{
                out = {{ undefined: true }};
              }} else {{
                out = {{
                  finishLoginRequest: r.finishLoginRequest,
                  sessionKey: r.sessionKey,
                  exportKey: r.exportKey,
                }};
              }}
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


def _client(stage: str, **kwargs) -> dict:
    child_env = dict(os.environ)
    for unsafe_name in ("NODE_OPTIONS", "OPENSSL_CONF", "RANDFILE"):
        child_env.pop(unsafe_name, None)
    child_env["INPUT"] = json.dumps({"stage": stage, **kwargs})
    proc = subprocess.run(
        [_NODE_EXE, "-e", _client_script()],
        env=child_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"node client failed: {proc.stderr}")
    return json.loads(proc.stdout)


def _full_round_trip(monkeypatch, *, with_identifiers: bool) -> dict:
    """Runs one full OPAQUE register + login handshake. Returns a
    dict describing the outcome so the test cases can assert on it.

    with_identifiers=True mirrors the pre-2026-07-22 frontend, which
    passed ``identifiers.client = credentialId`` in finishRegistration
    and finishLogin. The server (opaque_server_module) always uses
    ``ServerLoginParameters::default()`` — this test does NOT vary
    the server side, so the outcome directly measures whether the
    client-only identifier mismatch is fatal.
    """
    setup_bytes = _wheel.server_setup_new()
    monkeypatch.setenv(
        "VAULTAI_OPAQUE_SERVER_SETUP", _b64u_enc(setup_bytes),
    )
    opaque_server_module.clear_setup_cache_for_tests()

    reg_start = _client(
        "register-start", password=PASSWORD, withIdentifiers=with_identifiers,
    )
    reg_req = _b64u_dec(reg_start["registrationRequest"])
    reg_resp = opaque_server_module.registration_start(
        reg_req, CRED_ID_STR.encode("utf-8"),
    )
    reg_finish = _client(
        "register-finish",
        password=PASSWORD,
        registrationResponse=_b64u_enc(reg_resp),
        clientRegistrationState=reg_start["clientRegistrationState"],
        credentialId=CRED_ID_STR,
        withIdentifiers=with_identifiers,
    )
    server_record = opaque_server_module.registration_finish(
        _b64u_dec(reg_finish["registrationRecord"]),
    )

    login_start = _client("login-start", password=PASSWORD)
    cred_req = _b64u_dec(login_start["startLoginRequest"])
    ke2, server_state = opaque_server_module.login_start(
        server_record, cred_req, CRED_ID_STR.encode("utf-8"),
    )
    login_finish = _client(
        "login-finish",
        password=PASSWORD,
        loginResponse=_b64u_enc(ke2),
        clientLoginState=login_start["clientLoginState"],
        credentialId=CRED_ID_STR,
        withIdentifiers=with_identifiers,
    )

    if login_finish.get("undefined") is True:
        return {"client_finish_undefined": True}

    try:
        session_key_server = opaque_server_module.login_finish(
            server_state, _b64u_dec(login_finish["finishLoginRequest"]),
        )
    except Exception as exc:
        return {"server_finish_error": type(exc).__name__ + ": " + str(exc)}
    return {
        "client_finish_undefined": False,
        "session_keys_match": (
            _b64u_enc(session_key_server) == login_finish["sessionKey"]
        ),
        "export_keys_match": (
            reg_finish["exportKey"] == login_finish["exportKey"]
        ),
    }


@pytest.mark.opaque_interop
def test_client_identifiers_without_matching_server_identifiers_fails(
    monkeypatch,
) -> None:
    """The pre-2026-07-22 production configuration.

    Client passes ``identifiers.client = credentialId`` in both
    register and login; server passes ``ServerLoginParameters::
    default()`` (identifiers = None). The OPAQUE AKE transcript
    mismatches; the client's finishLogin returns undefined.

    This test proves the identifier mismatch is fatal, so a
    subsequent fix (see below) cannot regress silently.
    """
    result = _full_round_trip(monkeypatch, with_identifiers=True)
    assert result.get("client_finish_undefined") is True, (
        "expected client.finishLogin to return undefined when the "
        "client sets identifiers.client but the server does not. "
        f"got: {result!r}"
    )


@pytest.mark.opaque_interop
def test_neither_side_sets_identifiers_succeeds(monkeypatch) -> None:
    """The 2026-07-22 fix configuration.

    Client omits ``identifiers``; server omits identifiers (via
    ``ServerLoginParameters::default()``). Both sides agree on
    empty identifiers; the AKE completes.

    A green result here is the definitive proof that the fix
    ships a correctly registering + immediately-loginable account.
    """
    result = _full_round_trip(monkeypatch, with_identifiers=False)
    assert result.get("client_finish_undefined") is False, (
        "expected client.finishLogin to succeed when neither side "
        f"sets identifiers. got: {result!r}"
    )
    assert result["session_keys_match"] is True, (
        "session_keys diverged even without identifiers — the fix "
        "is insufficient. This would mean a second, unrelated cause "
        f"of the login failure. got: {result!r}"
    )
    assert result["export_keys_match"] is True, (
        "export_keys diverged — the client cannot derive the KEK "
        "that unwraps its stored MVK."
    )
