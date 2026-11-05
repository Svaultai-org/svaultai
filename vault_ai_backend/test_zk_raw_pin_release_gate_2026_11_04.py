"""Release gate: the ZK web client must stop constructing raw-PIN API bodies.

Only the explicitly opt-in legacy migration login may retain a PIN body.
The scan names every current sink, rather than asserting a brittle baseline
count. It intentionally fails until the complete ZK API cutover is built.
"""

from __future__ import annotations

import re
from pathlib import Path


_FRONTEND = Path(__file__).resolve().parents[1] / "vault_ai_frontend" / "lib"
_HTTP_CLIENT = _FRONTEND / "api_client.dart"
_APP = _FRONTEND / "main.dart"

_METHOD = re.compile(
    r"^(?:  )?(?:Future(?:<[^)]*>)?|Map<[^)]*>|void|String|bool|int)"
    r"\s+([A-Za-z_]\w*)\s*\("
)
_JSON_PIN_KEY = re.compile(r"['\"]pin['\"]\s*:\s*pin\b")
_FORM_PIN_KEY = re.compile(r"\.fields\[['\"]pin['\"]\]\s*=\s*pin\b")


def _pin_request_sinks() -> list[tuple[int, str]]:
    method = "<top-level>"
    sinks: list[tuple[int, str]] = []
    for line_number, line in enumerate(_HTTP_CLIENT.read_text().splitlines(), 1):
        found = _METHOD.match(line)
        if found:
            method = found.group(1)
        if _JSON_PIN_KEY.search(line) or _FORM_PIN_KEY.search(line):
            sinks.append((line_number, method))
    return sinks


def test_zk_client_has_no_raw_pin_api_sink_outside_legacy_migration():
    assert _HTTP_CLIENT.exists(), "API client source missing; gate cannot run"
    sinks = _pin_request_sinks()
    unapproved = [(line, method) for line, method in sinks
                  if method != "authLogin"]
    core = {"buildChatRequestBody", "uploadVaultFile", "listVaultFiles",
            "downloadVaultFile", "getDownloadManifest", "initChunkedUpload",
            "finalizeChunkedUpload", "getVaultSecureItem"}
    pending_device = {"requestSelfApproval", "finalizeSelfApproval"}
    core_blockers = sorted({method for _, method in unapproved if method in core})
    device_blockers = sorted({method for _, method in unapproved
                             if method in pending_device})
    detail = ", ".join(f"{method}@{line}" for line, method in unapproved)
    assert not unapproved, (
        f"{len(unapproved)} raw-PIN HTTP request construction sites remain "
        f"outside the opt-in legacy login. Verifier-free signup would break "
        f"core flows: {core_blockers}; pending-device self-approval still "
        f"depends on raw PIN and cannot use trusted-device-only OPAQUE "
        f"reverify: {device_blockers}. All sinks: {detail}"
    )


def test_legacy_login_is_opt_in_and_disabled_by_default():
    assert _APP.exists(), "app source missing; gate cannot run"
    source = _APP.read_text()
    assert "VAULTAI_ENABLE_LEGACY_AUTH_FALLBACK" in source, (
        "Legacy raw-PIN login must be guarded by an explicit compile-time flag"
    )
    assert re.search(
        r"const\s+bool\s+\w+\s*=\s*bool\.fromEnvironment\(\s*"
        r"['\"]VAULTAI_ENABLE_LEGACY_AUTH_FALLBACK['\"]\s*,\s*"
        r"defaultValue:\s*false",
        source,
    ), "Legacy login must be disabled in a default build"
