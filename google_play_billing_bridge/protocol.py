"""Authenticated request/response protocol for the Hostinger billing caller."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Mapping


PROTOCOL_VERSION = "v1"
TIMESTAMP_HEADER = "X-SVaultAI-Timestamp"
NONCE_HEADER = "X-SVaultAI-Nonce"
SIGNATURE_HEADER = "X-SVaultAI-Signature"
RESPONSE_SIGNATURE_HEADER = "X-SVaultAI-Response-Signature"
MAX_CLOCK_SKEW_SECONDS = 60
MAX_REQUEST_BYTES = 8192
_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


class AuthenticationError(RuntimeError):
    pass


class ReplayError(AuthenticationError):
    pass


@dataclass(frozen=True)
class AuthenticatedRequest:
    timestamp: str
    nonce: str


class NonceReplayCache:
    """Bounded, concurrency-safe replay cache for a single Cloud Run instance."""

    def __init__(self, *, capacity: int = 10_000):
        self._capacity = capacity
        self._nonces: OrderedDict[str, int] = OrderedDict()
        self._lock = threading.Lock()

    def claim(self, nonce: str, *, now: int) -> None:
        oldest_valid = now - MAX_CLOCK_SKEW_SECONDS
        with self._lock:
            while self._nonces:
                _oldest_nonce, seen_at = next(iter(self._nonces.items()))
                if seen_at >= oldest_valid:
                    break
                self._nonces.popitem(last=False)
            if nonce in self._nonces:
                raise ReplayError("request nonce has already been used")
            self._nonces[nonce] = now
            while len(self._nonces) > self._capacity:
                self._nonces.popitem(last=False)


def canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def request_signature(
    *, secret: bytes, timestamp: str, nonce: str, method: str, path: str,
    body: bytes,
) -> str:
    digest = hashlib.sha256(body).hexdigest()
    canonical = (
        f"{PROTOCOL_VERSION}\n{timestamp}\n{nonce}\n"
        f"{method.upper()}\n{path}\n{digest}"
    ).encode("utf-8")
    return "v1=" + hmac.new(secret, canonical, hashlib.sha256).hexdigest()


def response_signature(
    *, secret: bytes, timestamp: str, nonce: str, status: int, body: bytes,
) -> str:
    digest = hashlib.sha256(body).hexdigest()
    canonical = (
        f"{PROTOCOL_VERSION}\n{timestamp}\n{nonce}\n{status}\n{digest}"
    ).encode("utf-8")
    return "v1=" + hmac.new(secret, canonical, hashlib.sha256).hexdigest()


def authenticate_request(
    *, headers: Mapping[str, str], method: str, path: str, body: bytes,
    secret: bytes, replay_cache: NonceReplayCache, now: int | None = None,
) -> AuthenticatedRequest:
    if len(body) > MAX_REQUEST_BYTES:
        raise AuthenticationError("request body is too large")
    timestamp = str(headers.get(TIMESTAMP_HEADER, ""))
    nonce = str(headers.get(NONCE_HEADER, ""))
    supplied = str(headers.get(SIGNATURE_HEADER, ""))
    if not timestamp or not _NONCE_PATTERN.fullmatch(nonce) or not supplied:
        raise AuthenticationError("request authentication is incomplete")
    try:
        issued_at = int(timestamp)
    except ValueError as exc:
        raise AuthenticationError("request timestamp is invalid") from exc
    current = int(time.time()) if now is None else now
    if abs(current - issued_at) > MAX_CLOCK_SKEW_SECONDS:
        raise AuthenticationError("request timestamp is outside the allowed window")
    expected = request_signature(
        secret=secret,
        timestamp=timestamp,
        nonce=nonce,
        method=method,
        path=path,
        body=body,
    )
    if not hmac.compare_digest(supplied, expected):
        raise AuthenticationError("request signature is invalid")
    replay_cache.claim(nonce, now=current)
    return AuthenticatedRequest(timestamp=timestamp, nonce=nonce)
