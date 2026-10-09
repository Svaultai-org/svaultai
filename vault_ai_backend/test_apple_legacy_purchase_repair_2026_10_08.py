"""Offline regressions for installed iOS purchase compatibility and recovery.

All signatures/providers/accounts here are synthetic; these tests never call
Apple, open a real database, or make a payment.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import apple_billing as apple
import billing_entitlements as ent
from routes import provider_billing_routes as routes


ACCOUNT = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
PRODUCT = "synthetic.apple.storage.monthly"
NOW = datetime.now(timezone.utc)
FUTURE_MS = int((NOW + timedelta(days=30)).timestamp() * 1000)
PAST_MS = int((NOW - timedelta(days=1)).timestamp() * 1000)


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    monkeypatch.setenv("VAULTAI_APPLE_PRODUCT_MAP_JSON", json.dumps({PRODUCT: {
        "quantity": 1, "entitlement_bytes": 53_687_091_200,
        "plan_id": "monthly", "billing_period": "P1M",
    }}))
    monkeypatch.setenv("VAULTAI_APPLE_ACCEPT_SANDBOX", "false")


def transaction(token=ACCOUNT, **changes):
    fields = dict(
        productId=PRODUCT, transactionId="synthetic-tx",
        originalTransactionId="synthetic-original", appAccountToken=token,
        purchaseDate=PAST_MS, expiresDate=FUTURE_MS,
        signedDate=int(NOW.timestamp() * 1000), revocationDate=None,
    )
    fields.update(changes)
    return SimpleNamespace(**fields)


class Verifier:
    def __init__(self, tx, *, fail=False):
        self.tx = tx
        self.fail = fail
        self.calls = []

    def verify_transaction(self, signed):
        self.calls.append(signed)
        if self.fail:
            raise apple.AppleTransactionVerificationError("synthetic invalid signature")
        return self.tx


@pytest.mark.parametrize("token_kind", ["raw", "uppercase_raw", "compact_raw", "opaque"])
def test_signed_token_accepts_only_the_same_authenticated_uuid(monkeypatch, token_kind):
    token = {
        "raw": ACCOUNT, "uppercase_raw": ACCOUNT.upper(),
        "compact_raw": ACCOUNT.replace("-", ""),
        "opaque": apple.apple_app_account_token(ACCOUNT),
    }[token_kind]
    verifier = Verifier(transaction(token))
    writes = []
    monkeypatch.setattr(apple, "upsert_verified_entitlement", lambda account, update:
                        writes.append((account, update)) or ("synthetic-entitlement", "new"))
    result = apple.verify_and_apply_apple_transaction(
        account_id=ACCOUNT, signed_transaction="synthetic-jws",
        environment="production", verifier=verifier,
    )
    assert result["verified"] is True
    assert writes[0][0] == ACCOUNT
    assert verifier.calls == ["synthetic-jws"]


@pytest.mark.parametrize("token", [
    OTHER, apple.apple_app_account_token(OTHER), "username-not-a-uuid", "account-1",
])
def test_wrong_or_non_uuid_signed_token_cannot_grant(monkeypatch, token):
    monkeypatch.setattr(apple, "upsert_verified_entitlement", lambda *_args:
                        pytest.fail("mismatched token must not write"))
    with pytest.raises(apple.AppleTransactionOwnershipError):
        apple.verify_and_apply_apple_transaction(
            account_id=ACCOUNT, signed_transaction="synthetic-jws",
            environment="production", verifier=Verifier(transaction(token)),
        )


def test_legacy_non_uuid_account_identifier_is_not_an_allowed_token():
    assert not apple.apple_token_matches_account("account-1", "account-1")
    assert apple.apple_token_matches_account(
        apple.apple_app_account_token("account-1"), "account-1",
    )
    assert apple.apple_app_account_token(uuid.UUID(ACCOUNT)) == apple.apple_app_account_token(ACCOUNT)


class AccountConnection:
    def __init__(self, ids):
        self.ids = ids
        self.sql = ""
        self.closed = False

    def cursor(self, *, name):
        assert name == "apple_account_token_lookup"
        return self

    def execute(self, sql):
        self.sql = sql

    def __iter__(self):
        return iter((uuid.UUID(account),) for account in self.ids)

    def close(self):
        self.closed = True


@pytest.mark.parametrize("token", [ACCOUNT, apple.apple_app_account_token(ACCOUNT)])
def test_first_binding_lookup_reads_only_live_account_ids(monkeypatch, token):
    conn = AccountConnection([OTHER, ACCOUNT])
    monkeypatch.setattr(apple, "get_db", lambda: conn)
    assert apple.find_live_account_for_apple_token(token) == ACCOUNT
    assert "SELECT a.account_id" in conn.sql
    assert "WHERE EXISTS" in conn.sql and "v.account_id = a.account_id" in conn.sql
    assert all(word not in conn.sql for word in ("username", "display_name", "ciphertext", "slug"))
    assert conn.closed


def test_unknown_or_deleted_token_is_not_bound(monkeypatch):
    conn = AccountConnection([OTHER])
    monkeypatch.setattr(apple, "get_db", lambda: conn)
    assert apple.find_live_account_for_apple_token(ACCOUNT) is None
    assert conn.closed
    monkeypatch.setattr(apple, "get_db", lambda: pytest.fail("invalid token must not query"))
    assert apple.find_live_account_for_apple_token("a-public-vault-name") is None
    assert apple.find_live_account_for_apple_token(None) is None


def test_ambiguous_legacy_and_opaque_lookup_fails_closed(monkeypatch):
    conn = AccountConnection([OTHER, ACCOUNT])
    monkeypatch.setattr(apple, "get_db", lambda: conn)
    monkeypatch.setattr(apple, "apple_token_matches_account", lambda *_args: True)
    with pytest.raises(apple.AppleTransactionOwnershipError):
        apple.find_live_account_for_apple_token(ACCOUNT)
    assert conn.closed


ENDPOINTS = ["/billing/apple/transactions", "/billing/apple/verify-transaction"]


def api_client(monkeypatch, verifier, *, trusted=True):
    app = FastAPI()
    app.include_router(routes.router)
    if trusted:
        app.dependency_overrides[routes.verify_trusted_device] = lambda: {"vault_id": "synthetic-vault"}
    monkeypatch.setattr(routes, "_account_id", lambda _principal: ACCOUNT)
    monkeypatch.setattr(apple, "AppleSignedDataVerifier", lambda _env: verifier)
    return TestClient(app)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_both_routes_use_the_same_validated_device_and_signature_handler(monkeypatch, endpoint):
    verifier = Verifier(transaction())
    writes = []
    monkeypatch.setattr(apple, "upsert_verified_entitlement", lambda account, update:
                        writes.append((account, update)) or ("synthetic-entitlement", "new"))
    response = api_client(monkeypatch, verifier).post(endpoint, json={
        "signed_transaction": "synthetic-valid-jws", "environment": "production",
    })
    assert response.status_code == 200
    assert response.json()["verified"] is True
    assert len(writes) == 1 and writes[0][0] == ACCOUNT
    assert verifier.calls == ["synthetic-valid-jws"]
    handlers = [route for route in routes.router.routes if route.path in ENDPOINTS]
    assert len(handlers) == 2 and handlers[0].endpoint is handlers[1].endpoint
    assert all(route.dependant.dependencies[0].call is routes.verify_trusted_device for route in handlers)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_both_routes_reject_invalid_signature_without_write(monkeypatch, endpoint):
    monkeypatch.setattr(apple, "upsert_verified_entitlement", lambda *_args: pytest.fail("no write"))
    response = api_client(monkeypatch, Verifier(transaction(), fail=True)).post(
        endpoint, json={"signed_transaction": "synthetic-invalid-jws"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "apple_transaction_invalid"


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_both_routes_reject_another_account_token(monkeypatch, endpoint):
    monkeypatch.setattr(apple, "upsert_verified_entitlement", lambda *_args: pytest.fail("no write"))
    response = api_client(monkeypatch, Verifier(transaction(OTHER))).post(
        endpoint, json={"signed_transaction": "synthetic-valid-jws"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "subscription_bound_to_another_active_account"


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_both_routes_reject_disabled_sandbox_and_unconfigured_product(monkeypatch, endpoint):
    verifier = Verifier(transaction(productId="synthetic-not-configured"))
    client = api_client(monkeypatch, verifier)
    response = client.post(endpoint, json={"signed_transaction": "synthetic-jws", "environment": "sandbox"})
    assert response.status_code == 403 and not verifier.calls
    response = client.post(endpoint, json={"signed_transaction": "synthetic-jws"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "apple_billing_not_configured"


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("status,expiry,expected", [
    ("active", NOW + timedelta(days=40), "active"),
    ("active", NOW - timedelta(days=1), "expired"),
    ("expired", NOW - timedelta(days=1), "expired"),
    ("refunded", NOW + timedelta(days=40), "refunded"),
    ("revoked", NOW + timedelta(days=40), "revoked"),
    ("grace_period", NOW + timedelta(days=1), "grace_period"),
    ("active", None, "pending"),
])
def test_stale_restore_acknowledges_latest_verified_state_without_overwrite(monkeypatch, endpoint, status, expiry, expected):
    def stale(*_args):
        raise ent.StaleProviderEventError("newer signed notification already applied")
    monkeypatch.setattr(apple, "upsert_verified_entitlement", stale)
    conn = SingleRowConnection({
        "entitlement_id": "synthetic-entitlement", "product_id": PRODUCT,
        "status": status, "current_period_end": expiry,
    })
    monkeypatch.setattr(apple, "get_db", lambda: conn)
    response = api_client(monkeypatch, Verifier(transaction())).post(
        endpoint, json={"signed_transaction": "synthetic-old-jws"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == expected
    assert response.json()["transition"] == "ignored_stale"
    assert response.json()["verified"] is True
    assert response.json()["already_recorded"] is True
    assert conn.closed and len(conn.statements) == 1
    sql, params = conn.statements[0]
    assert "provider = 'apple'" in sql and "verification_state = 'verified'" in sql
    assert "account_id = %s" in sql and params[0] == ACCOUNT
    assert params[1:] == ("synthetic-tx", "synthetic-original")
    assert "UPDATE" not in sql and "INSERT" not in sql


class SingleRowConnection:
    def __init__(self, row):
        self.row = row
        self.statements = []
        self.closed = False
        self.rolled_back = False

    def cursor(self, **_kwargs):
        return self

    def execute(self, sql, params):
        self.statements.append((sql, params))

    def fetchone(self):
        return self.row

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_actual_ledger_original_purchase_owner_guard_precedes_stale_ack(monkeypatch):
    # Use the real ledger upsert: the signed token matches OTHER, but the
    # immutable original Apple purchase is already owned by ACCOUNT.
    conn = SingleRowConnection({
        "entitlement_id": "synthetic-entitlement", "account_id": ACCOUNT,
        "status": "refunded", "last_provider_event_at": NOW + timedelta(days=1),
    })
    monkeypatch.setattr(ent, "get_db", lambda: conn)
    monkeypatch.setattr(apple, "get_db", lambda: pytest.fail("must not ack another account's receipt"))
    with pytest.raises(apple.AppleTransactionOwnershipError):
        apple.verify_and_apply_apple_transaction(
            account_id=OTHER, signed_transaction="synthetic-other-account-jws",
            environment="production", verifier=Verifier(transaction(OTHER)),
        )
    assert conn.rolled_back and conn.closed
    assert len(conn.statements) == 1 and "FOR UPDATE" in conn.statements[0][0]


def test_stale_receipt_never_acks_absent_or_unverified_apple_binding(monkeypatch):
    def stale(*_args):
        raise ent.StaleProviderEventError("newer signed notification")
    monkeypatch.setattr(apple, "upsert_verified_entitlement", stale)
    conn = SingleRowConnection(None)
    monkeypatch.setattr(apple, "get_db", lambda: conn)
    with pytest.raises(apple.AppleTransactionVerificationError):
        apple.verify_and_apply_apple_transaction(
            account_id=ACCOUNT, signed_transaction="synthetic-old-jws",
            environment="production", verifier=Verifier(transaction()),
        )
    assert conn.closed


@pytest.mark.parametrize("event,subtype,expiry,revocation,expected", [
    ("TRANSACTION_VERIFIED", "", FUTURE_MS, None, "active"),
    ("TRANSACTION_VERIFIED", "", PAST_MS, None, "expired"),
    ("REFUND", "", FUTURE_MS, PAST_MS, "refunded"),
    ("REVOKE", "", FUTURE_MS, PAST_MS, "revoked"),
    ("DID_FAIL_TO_RENEW", "GRACE_PERIOD", FUTURE_MS, None, "grace_period"),
    ("DID_FAIL_TO_RENEW", "GRACE_PERIOD", PAST_MS, None, "expired"),
    ("GRACE_PERIOD_EXPIRED", "", FUTURE_MS, None, "expired"),
])
def test_signed_status_and_existing_expiry_refund_grace_boundaries(event, subtype, expiry, revocation, expected):
    update = apple._transaction_update(
        transaction(expiresDate=expiry, revocationDate=revocation), environment="production",
        notification_type=event, subtype=subtype,
    )
    assert update.status == expected
    assert update.current_period_end == datetime.fromtimestamp(expiry / 1000, tz=timezone.utc)


class NotificationRequest:
    async def json(self):
        return {"signedPayload": "synthetic-outer-jws"}


def prepare_notification(monkeypatch, tx, *, ledger_account=None, lookup_account=ACCOUNT):
    state = {"outcome": None, "owner": ledger_account, "writes": [], "claims": [], "finishes": []}
    notification = SimpleNamespace(
        notificationUUID="synthetic-event", notificationType="SUBSCRIBED", subtype="INITIAL_BUY",
        data=SimpleNamespace(signedTransactionInfo="synthetic-inner-jws", signedRenewalInfo=None),
    )
    verifier = Verifier(tx)
    monkeypatch.setattr(apple, "decode_verified_apple_notification", lambda _signed:
                        ("production", verifier, notification))
    def claim(**kwargs):
        state["claims"].append(kwargs)
        if state["outcome"] not in (None, "error", "ignored_unbound"):
            return False
        assert kwargs["retry_unbound_apple"] is True
        state["outcome"] = "processing"
        return True
    def finish(**kwargs):
        state["finishes"].append(kwargs)
        state["outcome"] = kwargs["outcome"]
    def upsert(account, update):
        if state["owner"] and state["owner"] != account:
            raise ent.PurchaseAlreadyBoundError("already owned")
        state["owner"] = account
        state["writes"].append((account, update))
        return "synthetic-entitlement", "unchanged"
    monkeypatch.setattr(ent, "claim_provider_event", claim)
    monkeypatch.setattr(ent, "finish_provider_event", finish)
    monkeypatch.setattr(ent, "find_account_for_original_transaction", lambda *_args: state["owner"])
    monkeypatch.setattr(ent, "find_account_for_purchase", lambda *_args: state["owner"])
    monkeypatch.setattr(apple, "find_live_account_for_apple_token", lambda token:
                        lookup_account if token and lookup_account and apple.apple_token_matches_account(token, lookup_account) else None)
    monkeypatch.setattr(ent, "upsert_verified_entitlement", upsert)
    monkeypatch.setattr(apple, "upsert_verified_entitlement", upsert)
    return state, verifier, notification


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [ACCOUNT, apple.apple_app_account_token(ACCOUNT)])
async def test_first_verified_notification_binds_once_then_device_restore_cannot_transfer(monkeypatch, token):
    state, verifier, _notification = prepare_notification(monkeypatch, transaction(token))
    first = await routes.apple_notifications_v2(NotificationRequest())
    duplicate = await routes.apple_notifications_v2(NotificationRequest())
    assert first["outcome"] == "applied" and duplicate == {"outcome": "duplicate"}
    assert len(state["writes"]) == 1 and state["owner"] == ACCOUNT
    restored = apple.verify_and_apply_apple_transaction(
        account_id=ACCOUNT, signed_transaction="synthetic-restore-jws",
        environment="production", verifier=verifier,
    )
    assert restored["verified"] is True and state["owner"] == ACCOUNT
    with pytest.raises(apple.AppleTransactionOwnershipError):
        apple.verify_and_apply_apple_transaction(
            account_id=OTHER, signed_transaction="synthetic-restore-jws",
            environment="production", verifier=verifier,
        )
    assert len(state["writes"]) == 2


@pytest.mark.asyncio
async def test_tokenless_unbound_event_retries_after_authenticated_restore(monkeypatch):
    state, verifier, _notification = prepare_notification(monkeypatch, transaction(None), lookup_account=None)
    with pytest.raises(HTTPException) as pending:
        await routes.apple_notifications_v2(NotificationRequest())
    assert pending.value.status_code == 503
    assert state["outcome"] == "error" and not state["writes"]
    assert state["finishes"][-1]["error_text"] == "AppleAccountBindingPendingError"
    apple.verify_and_apply_apple_transaction(
        account_id=ACCOUNT, signed_transaction="synthetic-restore-jws",
        environment="production", verifier=verifier,
    )
    retry = await routes.apple_notifications_v2(NotificationRequest())
    assert retry["outcome"] == "applied" and state["owner"] == ACCOUNT


@pytest.mark.asyncio
async def test_old_ignored_unbound_can_be_reclaimed_and_applied(monkeypatch):
    state, _verifier, _notification = prepare_notification(monkeypatch, transaction())
    state["outcome"] = "ignored_unbound"
    result = await routes.apple_notifications_v2(NotificationRequest())
    assert result["outcome"] == "applied" and state["owner"] == ACCOUNT


@pytest.mark.asyncio
async def test_unbound_deleted_account_is_retryable_never_guessed(monkeypatch):
    state, _verifier, _notification = prepare_notification(monkeypatch, transaction(), lookup_account=None)
    with pytest.raises(HTTPException) as pending:
        await routes.apple_notifications_v2(NotificationRequest())
    assert pending.value.status_code == 503 and state["outcome"] == "error"
    assert state["owner"] is None and not state["writes"]


@pytest.mark.asyncio
async def test_notification_cannot_transfer_existing_original_purchase(monkeypatch):
    state, _verifier, _notification = prepare_notification(monkeypatch, transaction(OTHER), ledger_account=ACCOUNT, lookup_account=OTHER)
    with pytest.raises(HTTPException) as rejected:
        await routes.apple_notifications_v2(NotificationRequest())
    assert rejected.value.status_code == 503 and not state["writes"]
    assert state["owner"] == ACCOUNT
    assert state["finishes"][-1]["error_text"] == "AppleTransactionOwnershipError"


@pytest.mark.asyncio
async def test_missing_catalog_is_retryable_after_configuration_repair(monkeypatch):
    state, _verifier, _notification = prepare_notification(monkeypatch, transaction())
    configured_catalog = apple.configured_apple_catalog()
    monkeypatch.setenv("VAULTAI_APPLE_PRODUCT_MAP_JSON", "{}")
    with pytest.raises(HTTPException) as unavailable:
        await routes.apple_notifications_v2(NotificationRequest())
    assert unavailable.value.status_code == 503
    assert state["outcome"] == "error" and not state["writes"]
    assert state["finishes"][-1]["error_text"] == "AppleBillingConfigurationError"
    monkeypatch.setenv("VAULTAI_APPLE_PRODUCT_MAP_JSON", json.dumps(configured_catalog))
    assert (await routes.apple_notifications_v2(NotificationRequest()))["outcome"] == "applied"
    assert len(state["writes"]) == 1


@pytest.mark.asyncio
async def test_nested_invalid_jws_never_claims_or_freezes_uuid(monkeypatch):
    state, verifier, _notification = prepare_notification(monkeypatch, transaction())
    verifier.fail = True
    with pytest.raises(HTTPException) as rejected:
        await routes.apple_notifications_v2(NotificationRequest())
    assert rejected.value.status_code == 400
    assert state["claims"] == [] and state["finishes"] == []
    assert not state["writes"]
    verifier.fail = False
    assert (await routes.apple_notifications_v2(NotificationRequest()))["outcome"] == "applied"


@pytest.mark.asyncio
async def test_transient_processing_failure_retries_but_stale_is_terminal(monkeypatch):
    state, _verifier, _notification = prepare_notification(monkeypatch, transaction(), ledger_account=ACCOUNT)
    def transient(*_args):
        raise RuntimeError("synthetic database outage")
    monkeypatch.setattr(ent, "upsert_verified_entitlement", transient)
    with pytest.raises(HTTPException) as unavailable:
        await routes.apple_notifications_v2(NotificationRequest())
    assert unavailable.value.status_code == 503 and state["outcome"] == "error"
    def stale(*_args):
        raise ent.StaleProviderEventError("synthetic newer event")
    monkeypatch.setattr(ent, "upsert_verified_entitlement", stale)
    assert await routes.apple_notifications_v2(NotificationRequest()) == {"outcome": "ignored_stale"}
    assert state["outcome"] == "ignored_stale"
    assert await routes.apple_notifications_v2(NotificationRequest()) == {"outcome": "duplicate"}


class ClaimConnection:
    def __init__(self, previous):
        self.previous = previous
        self.claimed = False
        self.sql = ""
        self.params = None
        self.closed = False

    def cursor(self):
        return self

    def execute(self, sql, params):
        self.sql, self.params = sql, params
        self.claimed = self.previous == "error" or (
            self.previous == "ignored_unbound" and params[-1] is True
        )

    def fetchone(self):
        return ("synthetic-event",) if self.claimed else None

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = True


@pytest.mark.parametrize("source,verified,opt_in,previous,expected", [
    ("apple", True, True, "ignored_unbound", True),
    ("apple", True, False, "ignored_unbound", False),
    ("apple", False, True, "ignored_unbound", False),
    ("google_play", True, True, "ignored_unbound", False),
    ("apple", True, True, "applied", False),
    ("apple", True, True, "ignored_stale", False),
    ("apple", True, True, "verified_no_transaction", False),
    ("apple", True, True, "processing", False),
    ("apple", True, True, "error", True),
])
def test_retry_claim_is_apple_verified_opt_in_only_and_keeps_terminal_idempotency(monkeypatch, source, verified, opt_in, previous, expected):
    conn = ClaimConnection(previous)
    monkeypatch.setattr(ent, "get_db", lambda: conn)
    assert ent.claim_provider_event(
        source=source, event_id="synthetic-event", signature_verified=verified,
        environment="production", sanitized_payload={"notification_type": "SUBSCRIBED"},
        retry_unbound_apple=opt_in,
    ) is expected
    assert "provider_event_log.source = 'apple'" in conn.sql
    assert "provider_event_log.signature_verified = TRUE" in conn.sql
    assert "provider_event_log.outcome = 'ignored_unbound'" in conn.sql
    assert conn.closed
