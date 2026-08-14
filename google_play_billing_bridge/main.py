"""Minimal keyless Google Play Billing bridge for Cloud Run.

This service has no database and no entitlement-writing endpoint. Hostinger
remains the only component that can validate account binding and change a
billing entitlement.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .protocol import (
    AuthenticationError,
    AuthenticatedRequest,
    NonceReplayCache,
    ReplayError,
    RESPONSE_SIGNATURE_HEADER,
    authenticate_request,
    canonical_json,
    response_signature,
)
from .publisher import (
    PRODUCT_ID,
    PublisherConfigurationError,
    PublisherTransientError,
    PublisherVerificationError,
    PurchaseNotFoundError,
    acknowledge_subscription,
    get_subscription,
    verify_catalog,
)


app = FastAPI(
    title="SVaultAI Google Play Billing Bridge",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
_replay_cache = NonceReplayCache()


def _secret() -> bytes:
    value = os.getenv("VAULTAI_GOOGLE_PLAY_BRIDGE_HMAC_SECRET", "").strip()
    secret = value.encode("utf-8")
    if len(secret) < 32:
        raise PublisherConfigurationError("bridge HMAC secret is not configured")
    return secret


def _signed_response(
    payload: Mapping[str, Any], *, status: int, auth: AuthenticatedRequest,
    secret: bytes,
) -> Response:
    body = canonical_json(payload)
    signature = response_signature(
        secret=secret,
        timestamp=auth.timestamp,
        nonce=auth.nonce,
        status=status,
        body=body,
    )
    return Response(
        content=body,
        media_type="application/json",
        status_code=status,
        headers={RESPONSE_SIGNATURE_HEADER: signature},
    )


def _payload(body: bytes, *, allowed: set[str]) -> dict[str, Any]:
    try:
        decoded = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise PublisherVerificationError("request JSON is invalid") from exc
    if not isinstance(decoded, dict) or set(decoded) - allowed:
        raise PublisherVerificationError("request fields are invalid")
    return decoded


def _purchase_token(payload: Mapping[str, Any]) -> str:
    token = payload.get("purchase_token")
    if not isinstance(token, str) or not token or len(token) > 4096:
        raise PublisherVerificationError("purchase token is invalid")
    return token


async def _authenticated(request: Request) -> tuple[bytes, bytes, AuthenticatedRequest]:
    body = await request.body()
    secret = _secret()
    auth = authenticate_request(
        headers=request.headers,
        method=request.method,
        path=request.url.path,
        body=body,
        secret=secret,
        replay_cache=_replay_cache,
    )
    return body, secret, auth


async def _run(request: Request, operation) -> Response:
    try:
        body, secret, auth = await _authenticated(request)
    except ReplayError:
        secret = _secret()
        auth = AuthenticatedRequest(
            timestamp=str(request.headers.get("X-SVaultAI-Timestamp", "")),
            nonce=str(request.headers.get("X-SVaultAI-Nonce", "")),
        )
        return _signed_response(
            {"error": "request_replayed"},
            status=409,
            auth=auth,
            secret=secret,
        )
    except AuthenticationError:
        return JSONResponse({"error": "authentication_failed"}, status_code=401)
    except PublisherConfigurationError:
        return JSONResponse({"error": "service_unavailable"}, status_code=503)
    try:
        result = await run_in_threadpool(operation, body)
        return _signed_response(result, status=200, auth=auth, secret=secret)
    except PurchaseNotFoundError:
        return _signed_response(
            {"error": "purchase_not_found"},
            status=404,
            auth=auth,
            secret=secret,
        )
    except PublisherConfigurationError:
        return _signed_response(
            {"error": "publisher_auth_unavailable"},
            status=503,
            auth=auth,
            secret=secret,
        )
    except PublisherTransientError:
        return _signed_response(
            {"error": "publisher_temporarily_unavailable"},
            status=503,
            auth=auth,
            secret=secret,
        )
    except PublisherVerificationError:
        return _signed_response(
            {"error": "publisher_request_rejected"},
            status=400,
            auth=auth,
            secret=secret,
        )
    except Exception:
        # Fail closed and keep credential/transport details out of the wire
        # response. Cloud Run logs still retain the request-level 503 signal.
        return _signed_response(
            {"error": "publisher_temporarily_unavailable"},
            status=503,
            auth=auth,
            secret=secret,
        )


@app.get("/v1/health")
def health():
    # Public but deliberately non-operative: it neither resolves ADC nor calls
    # Android Publisher and cannot read or mutate billing state.
    try:
        _secret()
    except PublisherConfigurationError:
        return JSONResponse({"status": "not_ready"}, status_code=503)
    return {"status": "ok"}


@app.post("/v1/subscriptions:get")
async def subscriptions_get(request: Request):
    def operation(body: bytes) -> Mapping[str, Any]:
        payload = _payload(body, allowed={"purchase_token"})
        return {"subscription": get_subscription(_purchase_token(payload))}

    return await _run(request, operation)


@app.post("/v1/subscriptions:acknowledge")
async def subscriptions_acknowledge(request: Request):
    def operation(body: bytes) -> Mapping[str, Any]:
        payload = _payload(body, allowed={"product_id", "purchase_token"})
        if payload.get("product_id") != PRODUCT_ID:
            raise PublisherVerificationError("product is not in the fixed catalog")
        acknowledge_subscription(PRODUCT_ID, _purchase_token(payload))
        return {"acknowledged": True}

    return await _run(request, operation)


@app.post("/v1/catalog:verify")
async def catalog_verify(request: Request):
    def operation(body: bytes) -> Mapping[str, Any]:
        payload = _payload(body, allowed={"product_id"})
        if payload.get("product_id") != PRODUCT_ID:
            raise PublisherVerificationError("product is not in the fixed catalog")
        return verify_catalog()

    return await _run(request, operation)
