from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "vault_ai_backend"
sys.path.insert(0, str(BACKEND_DIR))

import google_play_billing as host  # noqa: E402

from google_play_billing_bridge import protocol  # noqa: E402


def test_hostinger_and_cloud_run_hmac_contract_is_identical():
    secret = b"contract-test-secret-at-least-32-bytes"
    timestamp = "1700000000"
    nonce = "contract_nonce_123456789012345678"
    path = "/v1/subscriptions:get"
    payload = {"purchase_token": "opaque-token"}
    host_body = host.GooglePlayPublisherClient._canonical_json(payload)
    bridge_body = protocol.canonical_json(payload)
    assert host_body == bridge_body
    assert host.GooglePlayPublisherClient._request_signature(
        secret=secret,
        timestamp=timestamp,
        nonce=nonce,
        path=path,
        body=host_body,
    ) == protocol.request_signature(
        secret=secret,
        timestamp=timestamp,
        nonce=nonce,
        method="POST",
        path=path,
        body=bridge_body,
    )
    response_body = protocol.canonical_json({"subscription": {}})
    assert host.GooglePlayPublisherClient._response_signature(
        secret=secret,
        timestamp=timestamp,
        nonce=nonce,
        status=200,
        body=response_body,
    ) == protocol.response_signature(
        secret=secret,
        timestamp=timestamp,
        nonce=nonce,
        status=200,
        body=response_body,
    )
