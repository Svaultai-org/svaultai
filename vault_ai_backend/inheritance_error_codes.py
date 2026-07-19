"""Inheritance operator-safe error codes + log redaction.

Two responsibilities live in this small module so the redaction
policy and the error catalog can be reasoned about together:

  1. ``INHERR`` — a small dataclass registry mapping short human
     codes (``INH-CRED-004``) onto a (safe user message, HTTP status)
     pair. Every inheritance endpoint raises through
     ``inheritance_http_error(code, log_details=...)`` which:

       * responds with the user-safe copy the code carries,
       * writes the full ``log_details`` mapping (redacted!) under
         the ``[INH]`` log tag so operators can grep it.

     The wire response NEVER contains stack traces, SQL text, or
     any field value the caller sent us. Only the reference code
     and a fixed user-safe sentence.

  2. ``install_inheritance_redaction()`` — installs a logging Filter
     that replaces the values of any dict entry whose key looks
     like credential material with the constant ``"<redacted>"``.
     Runs against ``record.args`` and ``record.__dict__.get("extra")``,
     so both ``log("...", {"pin": ...})`` and
     ``log("...", extra={"pin": ...})`` are scrubbed.

The filter is intentionally strict: if a value fails to be
JSON-serialized because of a nested type, we fall back to
``repr(type(v))`` rather than str(v).

Import contract
---------------

Backend modules that raise operator-safe inheritance errors do:

    from inheritance_error_codes import inheritance_http_error, INHERR
    inheritance_http_error(INHERR.PAIR_NO_SESSION,
                           log_details={"vault_id_tail": vault_id[-6:]})

The redaction filter is installed exactly once, from ``main.py``
during app boot.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from fastapi import HTTPException


# ---------------------------------------------------------------------
# Error catalog
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class _Code:
    code: str
    status: int
    user_message: str


class _INHERRSpace:
    """Enumeration of operator-safe inheritance codes.

    New entries must:
      * carry a stable 3-part identifier ``INH-<AREA>-<NNN>``,
      * carry a user-safe message that reveals no server internals,
      * pick the least-informative HTTP status that still lets the
        client know whether to retry.
    """

    # Pairing / label finalize
    PAIR_LABEL_FINALIZE_FAILED = _Code(
        "INH-PAIR-004", 409,
        "Could not generate the pairing code. Please try again.",
    )
    PAIR_NO_ACTIVE_VAULT = _Code(
        "INH-PAIR-002", 401,
        "This device is not signed in to a vault.",
    )

    # Credential escrow
    CRED_LINK_NOT_FOUND = _Code(
        "INH-CRED-001", 404,
        "That beneficiary link is not on your account.",
    )
    CRED_BENEFICIARY_NOT_LINKED = _Code(
        "INH-CRED-002", 409,
        "The beneficiary has not linked yet. Ask them to enter "
        "the pairing code first.",
    )
    CRED_BENEFICIARY_NO_ZK_PUBLIC_KEY = _Code(
        "INH-CRED-003", 409,
        "This beneficiary is not on a ZK-enabled vault. Ask them to "
        "unlock their vault at least once before saving credentials.",
    )
    CRED_INVALID_PACKAGE = _Code(
        "INH-CRED-004", 400,
        "The credential package is malformed. Please try again.",
    )
    CRED_ALREADY_SAVED = _Code(
        "INH-CRED-005", 409,
        "Credentials are already saved for this beneficiary. Use "
        "Update credentials instead.",
    )
    CRED_NOT_SAVED = _Code(
        "INH-CRED-006", 404,
        "No credentials are saved for this beneficiary yet.",
    )
    CRED_ACCESS_IN_FLIGHT = _Code(
        "INH-CRED-007", 409,
        "This beneficiary already has an active access request. "
        "Cancel it before changing the credentials.",
    )
    CRED_UNAUTHORIZED = _Code(
        "INH-CRED-401", 403,
        "You are not authorized to view or change these credentials.",
    )


INHERR = _INHERRSpace()

_INHERITANCE_LOG = logging.getLogger("vaultai.inheritance")


def inheritance_http_error(
    code: _Code,
    *,
    log_details: Optional[Mapping[str, Any]] = None,
) -> "HTTPException":
    """Return an HTTPException carrying the user-safe copy for ``code``.

    Also emits an ``[INH]``-tagged warning line whose ``extra`` dict
    is the ``log_details`` mapping — the caller is trusted to pass
    only non-sensitive identifiers (vault-id suffixes, link ids,
    boolean flags). The logging filter installed by
    ``install_inheritance_redaction()`` will scrub any key that
    accidentally matches a credential-material pattern before the
    line reaches a handler.
    """
    _INHERITANCE_LOG.warning(
        "[INH] reference=%s status=%s details=%s",
        code.code, code.status,
        dict(log_details or {}),
    )
    return HTTPException(
        status_code=code.status,
        detail={"code": code.code, "message": code.user_message},
    )


# ---------------------------------------------------------------------
# Log redaction
# ---------------------------------------------------------------------


# Any key matching one of these regex fragments gets its value
# replaced with the redaction sentinel before the log handler sees
# it. The list is intentionally over-broad — a false-positive
# redaction of a benign field is a minor operator inconvenience;
# leaking a credential is not.
_REDACT_KEY_PATTERNS = re.compile(
    r"(?ix)^(?:                    "
    r"    pin                       "
    r"  | password                  "
    r"  | passphrase                "
    r"  | credential                "
    r"  | credentials               "
    r"  | encrypted[_-]?payload     "
    r"  | payload[_-]?nonce         "
    r"  | wrapped[_-]?key           "
    r"  | wrapping[_-]?nonce        "
    r"  | wrapping[_-]?ephemeral[_-]?pk "
    r"  | secret                    "
    r"  | token                     "
    r"  | session[_-]?token         "
    r"  | authorization             "
    r"  | bearer                    "
    r"  | mvk                       "
    r"  | vault[_-]?key             "
    r"  | sk[_-]?vault              "
    r"  | passer[_-]?label          "
    # Match at end-of-key OR at a separator ([_-] or any non-word
    # character). ``\b`` would fail here because underscore counts
    # as a word char in Python's regex engine, so ``credential`` in
    # ``credential_bytes`` would slip through.
    r")(?:$|[_\W-])"
)

_REDACTED = "<redacted>"


def _scrub_mapping(m: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in m.items():
        try:
            if isinstance(k, str) and _REDACT_KEY_PATTERNS.match(k):
                out[k] = _REDACTED
            elif isinstance(v, Mapping):
                out[k] = _scrub_mapping(v)
            else:
                out[k] = v
        except Exception:
            out[k] = f"<{type(v).__name__}>"
    return out


class _InheritanceRedactionFilter(logging.Filter):
    """Replace credential-shaped values in log records with a sentinel.

    Runs early enough that formatters render the redacted view.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, Mapping):
            record.args = _scrub_mapping(args)
        elif isinstance(args, tuple):
            record.args = tuple(
                _scrub_mapping(a) if isinstance(a, Mapping) else a
                for a in args
            )
        extra = getattr(record, "__dict__", {})
        for key, value in list(extra.items()):
            if isinstance(value, Mapping):
                extra[key] = _scrub_mapping(value)
        return True


def install_inheritance_redaction() -> None:
    """Attach the redaction filter to the root logger and to loggers
    likely to render request bodies (uvicorn, fastapi). Idempotent."""
    filt = _InheritanceRedactionFilter()
    seen = getattr(install_inheritance_redaction, "_installed", None)
    if seen is not None:
        return
    for name in ("", "uvicorn", "uvicorn.access", "fastapi", "vaultai"):
        logger = logging.getLogger(name)
        if not any(
            isinstance(f, _InheritanceRedactionFilter)
            for f in logger.filters
        ):
            logger.addFilter(filt)
    install_inheritance_redaction._installed = True  # type: ignore[attr-defined]
