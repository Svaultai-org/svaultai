"""Monero (XMR) scanner architecture — safe by default.

VaultAI is receive-only for XMR out of the box. This module defines
the abstract scanner interface and the safe default adapters so the
scanner-status endpoint can honestly report whether a backend scanner
is available, without ever inventing balance or activity.

Security invariants (enforced by tests, not just documentation):

  1. Backend never receives seed, mnemonic, private spend key, or
     private view key from the client. Adapter methods only accept
     the public wallet address.
  2. Backend never decrypts encryptedWalletSecret.
  3. Backend never signs XMR transactions. canSend stays False in
     every status this module returns.
  4. Status responses carry only closed-set enum strings, booleans,
     and the fixed asset label "XMR". No wallet address, seed
     fragment, or scanner URL leaks into the response body.

Scanner modes (env: VAULTAI_CRYPTO_XMR_SCANNER_MODE):

  "none"             — no scanner. Default. Adapter reports disabled.
  "client_local"     — client scans locally using its own view
                       capability. Backend has no scanner; this
                       endpoint still reports disabled because the
                       endpoint describes the *server* scanner.
  "server_view_only" — future opt-in mode where the user supplies a
                       watch-only view credential to the server. Not
                       implemented in this slice; adapter reports
                       view_key_not_available until user consents.
"""

from __future__ import annotations

from typing import Any


MONERO_SCANNER_STATUS_SCHEMA_V1: str = "monero_scanner_status_v1"

_XMR_ASSET_LABEL: str = "XMR"


SCANNER_STATUS_DISABLED:       str = "disabled"
SCANNER_STATUS_NOT_CONFIGURED: str = "not_configured"
SCANNER_STATUS_CONFIGURED:     str = "configured"
SCANNER_STATUS_SYNCING:        str = "syncing"
SCANNER_STATUS_READY:          str = "ready"
SCANNER_STATUS_ERROR:          str = "error"

_ALLOWED_SCANNER_STATUS: frozenset[str] = frozenset({
    SCANNER_STATUS_DISABLED,
    SCANNER_STATUS_NOT_CONFIGURED,
    SCANNER_STATUS_CONFIGURED,
    SCANNER_STATUS_SYNCING,
    SCANNER_STATUS_READY,
    SCANNER_STATUS_ERROR,
})


REASON_SCANNER_NOT_ENABLED:    str = "scanner_not_enabled"
REASON_SCANNER_NOT_CONFIGURED: str = "scanner_not_configured"
REASON_VIEW_KEY_NOT_AVAILABLE: str = "view_key_not_available"
REASON_SCANNER_UNREACHABLE:    str = "scanner_unreachable"
REASON_SCANNER_SYNCING:        str = "scanner_syncing"
REASON_SCANNER_READY:          str = "scanner_ready"
REASON_SCANNER_ERROR:          str = "scanner_error"


REASON_LOCAL_SCANNER_AVAILABLE: str = "local_scanner_available"


REASON_SCANNER_REQUIRES_DESKTOP: str = "scanner_requires_desktop"

_ALLOWED_SCANNER_REASON: frozenset[str] = frozenset({
    REASON_SCANNER_NOT_ENABLED,
    REASON_SCANNER_NOT_CONFIGURED,
    REASON_VIEW_KEY_NOT_AVAILABLE,
    REASON_SCANNER_UNREACHABLE,
    REASON_SCANNER_SYNCING,
    REASON_SCANNER_READY,
    REASON_SCANNER_ERROR,
    REASON_LOCAL_SCANNER_AVAILABLE,
    REASON_SCANNER_REQUIRES_DESKTOP,
})


SCANNER_MODE_NONE:             str = "none"
SCANNER_MODE_CLIENT_LOCAL:     str = "client_local"
SCANNER_MODE_SERVER_VIEW_ONLY: str = "server_view_only"


CLIENT_PLATFORM_WEB:     str = "web"
CLIENT_PLATFORM_NATIVE:  str = "native"
CLIENT_PLATFORM_UNKNOWN: str = "unknown"

_ALLOWED_CLIENT_PLATFORM: frozenset[str] = frozenset({
    CLIENT_PLATFORM_WEB,
    CLIENT_PLATFORM_NATIVE,
    CLIENT_PLATFORM_UNKNOWN,
})


BALANCE_STATUS_UNAVAILABLE: str = "unavailable"
BALANCE_STATUS_AVAILABLE:   str = "available"

ACTIVITY_STATUS_UNAVAILABLE: str = "unavailable"
ACTIVITY_STATUS_AVAILABLE:   str = "available"


def _build_status_envelope(
    scanner_status: str, reason: str,
) -> dict[str, Any]:

    if scanner_status not in _ALLOWED_SCANNER_STATUS:
        raise ValueError("scanner_status outside closed set")
    if reason not in _ALLOWED_SCANNER_REASON:
        raise ValueError("reason outside closed set")

    return {
        "schema":          MONERO_SCANNER_STATUS_SCHEMA_V1,
        "asset":           _XMR_ASSET_LABEL,
        "scannerStatus":   scanner_status,
        "reason":          reason,
        "canShowBalance":  False,
        "canShowActivity": False,
        "canSend":         False,
    }


def _build_balance_unavailable(reason: str) -> dict[str, Any]:
    return {
        "asset":           _XMR_ASSET_LABEL,
        "balanceStatus":   BALANCE_STATUS_UNAVAILABLE,
        "availableAmount": None,
        "unit":            None,
        "reason":          reason,
    }


def _build_activity_unavailable(reason: str) -> dict[str, Any]:
    return {
        "asset":              _XMR_ASSET_LABEL,
        "transactionsStatus": ACTIVITY_STATUS_UNAVAILABLE,
        "transactions":       [],
        "reason":             reason,
    }


class MoneroScannerAdapter:
    """Abstract scanner interface. Backend-side only. Adapters must
    NEVER print or log seeds, mnemonics, view/spend keys, encrypted
    secrets, or scanner URLs, and must NEVER invent balance or
    activity.
    """


    def get_status(self) -> dict[str, Any]:
        raise NotImplementedError


    def get_balance(self, public_address: str) -> dict[str, Any]:
        raise NotImplementedError


    def get_activity(
        self, public_address: str, limit: int = 20,
    ) -> dict[str, Any]:
        raise NotImplementedError


class DisabledMoneroScannerAdapter(MoneroScannerAdapter):
    """Default. Scanner is off by policy or env."""

    def get_status(self) -> dict[str, Any]:
        return _build_status_envelope(
            SCANNER_STATUS_DISABLED,
            REASON_SCANNER_NOT_ENABLED,
        )

    def get_balance(self, public_address: str) -> dict[str, Any]:
        return _build_balance_unavailable(
            REASON_SCANNER_NOT_ENABLED,
        )

    def get_activity(
        self, public_address: str, limit: int = 20,
    ) -> dict[str, Any]:
        return _build_activity_unavailable(
            REASON_SCANNER_NOT_ENABLED,
        )


class NotConfiguredMoneroScannerAdapter(MoneroScannerAdapter):
    """Env enabled a scanner mode that needs a real backend scanner
    URL, but no URL was supplied."""

    def get_status(self) -> dict[str, Any]:
        return _build_status_envelope(
            SCANNER_STATUS_NOT_CONFIGURED,
            REASON_SCANNER_NOT_CONFIGURED,
        )

    def get_balance(self, public_address: str) -> dict[str, Any]:
        return _build_balance_unavailable(
            REASON_SCANNER_NOT_CONFIGURED,
        )

    def get_activity(
        self, public_address: str, limit: int = 20,
    ) -> dict[str, Any]:
        return _build_activity_unavailable(
            REASON_SCANNER_NOT_CONFIGURED,
        )


class LocalScannerAvailableMoneroScannerAdapter(MoneroScannerAdapter):
    """`client_local` mode.

    A LOCAL, client-side scanner is available. The backend does NOT
    scan (canShowBalance / canShowActivity remain false because
    balance and activity are computed on-device from the client's
    decrypted wallet secret — the backend cannot and will not
    compute them). Reporting this state lets the UI light up the
    client-side "Local scanner available" affordance and the
    restore-height / Start scan controls.

    Security: this adapter NEVER accepts a seed, mnemonic, spend
    key, or view key. get_balance / get_activity refuse to return
    a numeric balance because the backend has no key material to
    scan with. Only the local client can produce that data.
    """

    def get_status(self) -> dict[str, Any]:
        return _build_status_envelope(
            SCANNER_STATUS_CONFIGURED,
            REASON_LOCAL_SCANNER_AVAILABLE,
        )

    def get_balance(self, public_address: str) -> dict[str, Any]:
        return _build_balance_unavailable(
            REASON_LOCAL_SCANNER_AVAILABLE,
        )

    def get_activity(
        self, public_address: str, limit: int = 20,
    ) -> dict[str, Any]:
        return _build_activity_unavailable(
            REASON_LOCAL_SCANNER_AVAILABLE,
        )


class RequiresDesktopMoneroScannerAdapter(MoneroScannerAdapter):
    """`client_local` mode with a web client.

    Real local Monero scanning requires native crypto primitives
    (Ed25519 output derivation, RingCT balance decoding) that are
    not shipped in the current Flutter-web build. This adapter
    reports the honest state so the UI can direct the user to the
    desktop / mobile app instead of pretending the web build can
    scan.

    Security: same as every other adapter — accepts only the public
    address, refuses to invent any balance or activity, keeps
    canSend=False. No key material ever touches this code path.
    """

    def get_status(self) -> dict[str, Any]:
        return _build_status_envelope(
            SCANNER_STATUS_CONFIGURED,
            REASON_SCANNER_REQUIRES_DESKTOP,
        )

    def get_balance(self, public_address: str) -> dict[str, Any]:
        return _build_balance_unavailable(
            REASON_SCANNER_REQUIRES_DESKTOP,
        )

    def get_activity(
        self, public_address: str, limit: int = 20,
    ) -> dict[str, Any]:
        return _build_activity_unavailable(
            REASON_SCANNER_REQUIRES_DESKTOP,
        )


class ViewKeyMissingMoneroScannerAdapter(MoneroScannerAdapter):
    """Server view-only mode configured but the user has not
    explicitly opted in and provided a watch-only credential.

    We do NOT accept view keys from the client in this slice; this
    adapter simply reports the honest "view-only scanning not
    available" state so the UI stops asking for real balance.
    """

    def get_status(self) -> dict[str, Any]:
        return _build_status_envelope(
            SCANNER_STATUS_CONFIGURED,
            REASON_VIEW_KEY_NOT_AVAILABLE,
        )

    def get_balance(self, public_address: str) -> dict[str, Any]:
        return _build_balance_unavailable(
            REASON_VIEW_KEY_NOT_AVAILABLE,
        )

    def get_activity(
        self, public_address: str, limit: int = 20,
    ) -> dict[str, Any]:
        return _build_activity_unavailable(
            REASON_VIEW_KEY_NOT_AVAILABLE,
        )


class SyncingMoneroScannerAdapter(MoneroScannerAdapter):
    """Server scanner is reachable and configured but currently
    still ingesting blocks. Used by tests today; a future
    HTTP-backed adapter will construct one of these when the
    scanner reports partial-height state."""

    def get_status(self) -> dict[str, Any]:
        return _build_status_envelope(
            SCANNER_STATUS_SYNCING,
            REASON_SCANNER_SYNCING,
        )

    def get_balance(self, public_address: str) -> dict[str, Any]:
        return _build_balance_unavailable(REASON_SCANNER_SYNCING)

    def get_activity(
        self, public_address: str, limit: int = 20,
    ) -> dict[str, Any]:
        return _build_activity_unavailable(REASON_SCANNER_SYNCING)


class UnreachableMoneroScannerAdapter(MoneroScannerAdapter):
    """Scanner URL is set but the server did not answer. Used by
    tests today; a real HTTP adapter can wrap a failed request in
    one of these before returning to the route."""

    def get_status(self) -> dict[str, Any]:
        return _build_status_envelope(
            SCANNER_STATUS_ERROR,
            REASON_SCANNER_UNREACHABLE,
        )

    def get_balance(self, public_address: str) -> dict[str, Any]:
        return _build_balance_unavailable(REASON_SCANNER_UNREACHABLE)

    def get_activity(
        self, public_address: str, limit: int = 20,
    ) -> dict[str, Any]:
        return _build_activity_unavailable(REASON_SCANNER_UNREACHABLE)


class ReadyMoneroScannerAdapter(MoneroScannerAdapter):
    """Scanner reports ready. get_balance / get_activity in this
    slice still returns 'unavailable' because there is no real
    scanner wired up; a real HTTP adapter would override these
    methods to return actual on-chain data. We NEVER return 0 or
    an empty list as a substitute for a real scan.
    """

    def get_status(self) -> dict[str, Any]:
        return _build_status_envelope(
            SCANNER_STATUS_READY,
            REASON_SCANNER_READY,
        )

    def get_balance(self, public_address: str) -> dict[str, Any]:
        return _build_balance_unavailable(REASON_SCANNER_READY)

    def get_activity(
        self, public_address: str, limit: int = 20,
    ) -> dict[str, Any]:
        return _build_activity_unavailable(REASON_SCANNER_READY)


def _normalize_client_platform(platform: str | None) -> str:
    if not platform:
        return CLIENT_PLATFORM_UNKNOWN
    v = str(platform).strip().lower()
    if v in _ALLOWED_CLIENT_PLATFORM:
        return v
    return CLIENT_PLATFORM_UNKNOWN


def get_monero_scanner_adapter(
    *, client_platform: str | None = None,
) -> MoneroScannerAdapter:
    """Factory: return the correct adapter for the current env
    and the caller's platform.

    This function never touches the network — it inspects env only.
    Real scanner probes (unreachable/syncing/ready) are the job of
    future HTTP-backed adapters that would replace this factory or
    wrap its result.

    `client_platform` is a caller-provided hint (`web`, `native`,
    `unknown`). Anything else is coerced to `unknown`. On web,
    `client_local` mode is honestly reported as
    `scanner_requires_desktop` because the real Monero library
    only runs on native builds.
    """
    from vault_config import (
        monero_enabled, monero_scanner_mode,
    )
    platform = _normalize_client_platform(client_platform)
    if not monero_enabled():
        return DisabledMoneroScannerAdapter()

    mode = monero_scanner_mode()
    if mode == SCANNER_MODE_NONE or not mode:
        return DisabledMoneroScannerAdapter()

    if mode == SCANNER_MODE_CLIENT_LOCAL:


        if platform == CLIENT_PLATFORM_WEB:
            return RequiresDesktopMoneroScannerAdapter()



        return LocalScannerAvailableMoneroScannerAdapter()

    if mode == SCANNER_MODE_SERVER_VIEW_ONLY:
        try:
            from vault_config import (
                monero_scanner_url as _read_scanner_url,
            )
            scanner_url = _read_scanner_url()
        except ImportError:
            scanner_url = ""
        if not scanner_url:
            return NotConfiguredMoneroScannerAdapter()


        return ViewKeyMissingMoneroScannerAdapter()


    return DisabledMoneroScannerAdapter()


__all__ = [
    "MONERO_SCANNER_STATUS_SCHEMA_V1",

    "SCANNER_STATUS_DISABLED",
    "SCANNER_STATUS_NOT_CONFIGURED",
    "SCANNER_STATUS_CONFIGURED",
    "SCANNER_STATUS_SYNCING",
    "SCANNER_STATUS_READY",
    "SCANNER_STATUS_ERROR",

    "REASON_SCANNER_NOT_ENABLED",
    "REASON_SCANNER_NOT_CONFIGURED",
    "REASON_VIEW_KEY_NOT_AVAILABLE",
    "REASON_SCANNER_UNREACHABLE",
    "REASON_SCANNER_SYNCING",
    "REASON_SCANNER_READY",
    "REASON_SCANNER_ERROR",
    "REASON_LOCAL_SCANNER_AVAILABLE",
    "REASON_SCANNER_REQUIRES_DESKTOP",

    "CLIENT_PLATFORM_WEB",
    "CLIENT_PLATFORM_NATIVE",
    "CLIENT_PLATFORM_UNKNOWN",

    "SCANNER_MODE_NONE",
    "SCANNER_MODE_CLIENT_LOCAL",
    "SCANNER_MODE_SERVER_VIEW_ONLY",

    "MoneroScannerAdapter",
    "DisabledMoneroScannerAdapter",
    "NotConfiguredMoneroScannerAdapter",
    "LocalScannerAvailableMoneroScannerAdapter",
    "RequiresDesktopMoneroScannerAdapter",
    "ViewKeyMissingMoneroScannerAdapter",
    "SyncingMoneroScannerAdapter",
    "UnreachableMoneroScannerAdapter",
    "ReadyMoneroScannerAdapter",

    "get_monero_scanner_adapter",
]
