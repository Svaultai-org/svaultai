from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import billing
import billing_entitlements as ent
import google_play_billing as google
import routes.provider_billing_routes as provider_routes


ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"
PLAN_ID = google.GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO
FUTURE = datetime(2099, 9, 1, tzinfo=timezone.utc)


class _Publisher:
    def __init__(self, payload):
        self.payload = payload
        self.acknowledged = []

    def get_subscription(self, token):
        assert token == "purchase-token"
        return self.payload

    def acknowledge_subscription(self, product_id, token):
        self.acknowledged.append((product_id, token))


def _line(
    product_id: str,
    *,
    expiry: str | None = "2099-09-01T00:00:00Z",
    auto_renewing: bool = True,
    deferred_product_id: str = "",
    replaced_product_id: str = "",
    replacement_mode: str = "",
):
    line = {
        "productId": product_id,
        "autoRenewingPlan": {"autoRenewEnabled": auto_renewing},
        "offerDetails": {"basePlanId": PLAN_ID},
    }
    if expiry is not None:
        line["expiryTime"] = expiry
    if deferred_product_id:
        line["deferredItemReplacement"] = {"productId": deferred_product_id}
    if replaced_product_id:
        line["itemReplacement"] = {
            "productId": replaced_product_id,
            "basePlanId": PLAN_ID,
            "replacementMode": replacement_mode,
        }
    return line


def _payload(lines, *, state="SUBSCRIPTION_STATE_ACTIVE", linked=""):
    payload = {
        "subscriptionState": state,
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        "startTime": "2026-08-01T00:00:00Z",
        "externalAccountIdentifiers": {
            "obfuscatedExternalAccountId": google.purchase_account_token(ACCOUNT_ID),
        },
        "lineItems": lines,
    }
    if linked:
        payload["linkedPurchaseToken"] = linked
    return payload


def test_immutable_total_capacity_catalog_is_exactly_the_approved_eight_tiers():
    expected = [
        (google.GOOGLE_PLAY_PRODUCT_50GB, 1, "50 GB", 1),
        (google.GOOGLE_PLAY_PRODUCT_100GB, 2, "100 GB", 2),
        (google.GOOGLE_PLAY_PRODUCT_150GB, 3, "150 GB", 3),
        (google.GOOGLE_PLAY_PRODUCT_200GB, 4, "200 GB", 4),
        (google.GOOGLE_PLAY_PRODUCT_250GB, 5, "250 GB", 5),
        (google.GOOGLE_PLAY_PRODUCT_300GB, 6, "300 GB", 6),
        (google.GOOGLE_PLAY_PRODUCT_500GB, 7, "500 GB", 10),
        (google.GOOGLE_PLAY_PRODUCT_1TB, 8, "1 TB", 20),
    ]
    assert len(google.GOOGLE_PLAY_STORAGE_CATALOG) == 8
    for product_id, rank, display, blocks in expected:
        tier = google.GOOGLE_PLAY_STORAGE_CATALOG[(product_id, PLAN_ID)]
        assert tier.product_id == product_id
        assert tier.base_plan_id == PLAN_ID
        assert tier.billing_period == "P1M"
        assert tier.tier_rank == rank
        assert tier.display_capacity == display
        assert tier.storage_bytes == google.STORAGE_BLOCK_BYTES * blocks
    with pytest.raises(TypeError):
        google.GOOGLE_PLAY_STORAGE_CATALOG[("unknown", PLAN_ID)] = object()


@pytest.mark.parametrize(
    ("old_product", "target_product", "expected_blocks"),
    [
        (
            google.GOOGLE_PLAY_PRODUCT_50GB,
            google.GOOGLE_PLAY_PRODUCT_100GB,
            2,
        ),
        (
            google.GOOGLE_PLAY_PRODUCT_100GB,
            google.GOOGLE_PLAY_PRODUCT_250GB,
            5,
        ),
        (
            google.GOOGLE_PLAY_PRODUCT_250GB,
            google.GOOGLE_PLAY_PRODUCT_500GB,
            10,
        ),
    ],
)
def test_immediate_replacement_grants_target_total_not_old_plus_new(
    monkeypatch, old_product, target_product, expected_blocks,
):
    captured = []
    monkeypatch.setattr(
        google,
        "reconcile_google_play_storage_entitlement",
        lambda account_id, update, **kwargs: (
            captured.append((account_id, update, kwargs))
            or ("entitlement-new", "none_to_active")
        ),
    )
    publisher = _Publisher(_payload(
        [_line(
            target_product,
            replaced_product_id=old_product,
            replacement_mode="CHARGE_PRORATED_PRICE",
        )],
        linked="purchase-token-old",
    ))
    google.verify_and_apply_google_subscription(
        account_id=ACCOUNT_ID,
        purchase_token="purchase-token",
        expected_product_id=target_product,
        publisher=publisher,
    )
    _account, update, kwargs = captured[0]
    assert update.entitlement_bytes == google.STORAGE_BLOCK_BYTES * expected_blocks
    assert update.quantity == expected_blocks
    assert kwargs["linked_purchase_id"] == "purchase-token-old"
    assert kwargs["scheduled_replacement"] is None


def test_deferred_500_to_250_retains_500_until_play_reports_effective(monkeypatch):
    captured = []
    monkeypatch.setattr(
        google,
        "reconcile_google_play_storage_entitlement",
        lambda account_id, update, **kwargs: (
            captured.append((account_id, update, kwargs))
            or ("entitlement-new", "none_to_active")
        ),
    )
    payload = _payload([
        _line(
            google.GOOGLE_PLAY_PRODUCT_500GB,
            deferred_product_id=google.GOOGLE_PLAY_PRODUCT_250GB,
            auto_renewing=False,
        ),
        _line(
            google.GOOGLE_PLAY_PRODUCT_250GB,
            expiry=None,
            replaced_product_id=google.GOOGLE_PLAY_PRODUCT_500GB,
            replacement_mode="DEFERRED",
        ),
    ], linked="purchase-token-old")
    result = google.verify_and_apply_google_subscription(
        account_id=ACCOUNT_ID,
        purchase_token="purchase-token",
        # A deferred Purchase can be surfaced with the future product selected.
        expected_product_id=google.GOOGLE_PLAY_PRODUCT_250GB,
        publisher=_Publisher(payload),
    )
    _account, update, kwargs = captured[0]
    scheduled = kwargs["scheduled_replacement"]
    assert update.product_id == google.GOOGLE_PLAY_PRODUCT_500GB
    assert update.entitlement_bytes == google.STORAGE_BLOCK_BYTES * 10
    assert scheduled.product_id == google.GOOGLE_PLAY_PRODUCT_250GB
    assert scheduled.entitlement_bytes == google.STORAGE_BLOCK_BYTES * 5
    assert scheduled.effective_at == FUTURE
    assert result.product_id == google.GOOGLE_PLAY_PRODUCT_500GB
    assert result.scheduled_product_id == google.GOOGLE_PLAY_PRODUCT_250GB


def test_deferred_renewal_activates_only_new_250_tier(monkeypatch):
    captured = []
    monkeypatch.setattr(
        google,
        "reconcile_google_play_storage_entitlement",
        lambda account_id, update, **kwargs: (
            captured.append((account_id, update, kwargs))
            or ("entitlement-new", "unchanged")
        ),
    )
    payload = _payload([
        _line(
            google.GOOGLE_PLAY_PRODUCT_500GB,
            expiry="2026-08-01T00:00:00Z",
            auto_renewing=False,
        ),
        _line(
            google.GOOGLE_PLAY_PRODUCT_250GB,
            replaced_product_id=google.GOOGLE_PLAY_PRODUCT_500GB,
            replacement_mode="DEFERRED",
        ),
    ], linked="purchase-token-old")
    google.verify_and_apply_google_subscription(
        account_id=ACCOUNT_ID,
        purchase_token="purchase-token",
        publisher=_Publisher(payload),
    )
    _account, update, kwargs = captured[0]
    assert update.product_id == google.GOOGLE_PLAY_PRODUCT_250GB
    assert update.entitlement_bytes == google.STORAGE_BLOCK_BYTES * 5
    assert kwargs["scheduled_replacement"] is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda line: line.update(productId="not_allowlisted"),
        lambda line: line["offerDetails"].update(basePlanId="wrong-plan"),
    ],
)
def test_unknown_product_or_wrong_base_plan_fails_before_ledger_write(
    monkeypatch, mutate,
):
    monkeypatch.setattr(
        google,
        "reconcile_google_play_storage_entitlement",
        lambda *_args, **_kwargs: pytest.fail("must not write entitlement"),
    )
    line = _line(google.GOOGLE_PLAY_PRODUCT_50GB)
    mutate(line)
    with pytest.raises(google.GooglePlayVerificationError):
        google.verify_and_apply_google_subscription(
            account_id=ACCOUNT_ID,
            purchase_token="purchase-token",
            publisher=_Publisher(_payload([line])),
        )


class _NormalizerCursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _sql, _params):
        pass

    def fetchall(self):
        return self.rows


class _NormalizerConnection:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self, **_kwargs):
        return _NormalizerCursor(self.rows)

    def close(self):
        pass


def _active_row(product_id, blocks):
    return {
        "provider": "google_play",
        "entitlement_family": "storage",
        "external_purchase_id": product_id,
        "status": "active",
        "quantity": blocks,
        "entitlement_bytes": google.STORAGE_BLOCK_BYTES * blocks,
        "current_period_end": FUTURE,
        "cancel_at_period_end": False,
    }


def test_defensive_normalization_never_sums_old_and_new_google_tiers(monkeypatch):
    rows = [
        _active_row(google.GOOGLE_PLAY_PRODUCT_100GB, 2),
        _active_row(google.GOOGLE_PLAY_PRODUCT_50GB, 1),
    ]
    monkeypatch.setattr(ent, "get_db", lambda: _NormalizerConnection(rows))
    normalized = ent.get_normalized_account_entitlement(ACCOUNT_ID)
    assert normalized.purchased_bytes == google.STORAGE_BLOCK_BYTES * 2
    assert normalized.block_count == 2


class _AtomicCursor:
    def __init__(self):
        self.statements = []
        self.kind = ""

    def execute(self, sql, params):
        params = tuple(params or ())
        assert len(re.findall(r"%s", sql)) == len(params)
        normalized = " ".join(sql.lower().split())
        self.statements.append((normalized, params))
        if "select entitlement_id, account_id, status" in normalized:
            self.kind = "existing"
        elif "select entitlement_id, account_id, external_purchase_id" in normalized:
            self.kind = "linked"
        elif "select entitlement_id, external_purchase_id" in normalized:
            self.kind = "active"
        elif "insert into billing_entitlements" in normalized:
            self.kind = "insert"
        else:
            self.kind = "other"

    def fetchone(self):
        if self.kind == "existing":
            return None
        if self.kind == "linked":
            return {
                "entitlement_id": "entitlement-old",
                "account_id": ACCOUNT_ID,
                "external_purchase_id": "purchase-token-old",
                "status": "active",
            }
        if self.kind == "insert":
            return {"entitlement_id": "entitlement-new"}
        raise AssertionError(f"unexpected fetchone for {self.kind}")

    def fetchall(self):
        assert self.kind == "active"
        return [{
            "entitlement_id": "entitlement-old",
            "external_purchase_id": "purchase-token-old",
        }]


class _AtomicConnection:
    def __init__(self):
        self.cursor_value = _AtomicCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, **_kwargs):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def test_linked_upgrade_supersedes_old_and_activates_new_in_one_transaction(
    monkeypatch,
):
    connection = _AtomicConnection()
    monkeypatch.setattr(ent, "get_db", lambda: connection)
    update = ent.VerifiedEntitlementUpdate(
        provider="google_play",
        external_purchase_id="purchase-token",
        product_id=google.GOOGLE_PLAY_PRODUCT_100GB,
        plan_id=PLAN_ID,
        quantity=2,
        entitlement_bytes=google.STORAGE_BLOCK_BYTES * 2,
        status="active",
        provider_status="SUBSCRIPTION_STATE_ACTIVE",
        environment="production",
        auto_renewing=True,
        current_period_end=FUTURE,
        provider_event_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
        provider_event_id="event-1",
    )
    result = ent.reconcile_google_play_storage_entitlement(
        ACCOUNT_ID,
        update,
        linked_purchase_id="purchase-token-old",
    )
    statements = [sql for sql, _params in connection.cursor_value.statements]
    supersede_index = next(
        i for i, sql in enumerate(statements)
        if "superseded_by_purchase_id" in sql and sql.startswith("update")
    )
    insert_index = next(
        i for i, sql in enumerate(statements)
        if sql.startswith("insert into billing_entitlements")
    )
    assert result == ("entitlement-new", "none_to_active")
    assert supersede_index < insert_index
    assert connection.commits == 1
    assert connection.rollbacks == 0


def _active_update(*, token="purchase-token", event_id="event-1"):
    return ent.VerifiedEntitlementUpdate(
        provider="google_play",
        external_purchase_id=token,
        product_id=google.GOOGLE_PLAY_PRODUCT_100GB,
        plan_id=PLAN_ID,
        quantity=2,
        entitlement_bytes=google.STORAGE_BLOCK_BYTES * 2,
        status="active",
        provider_status="SUBSCRIPTION_STATE_ACTIVE",
        environment="production",
        auto_renewing=True,
        current_period_end=FUTURE,
        provider_event_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
        provider_event_id=event_id,
    )


class _ExistingCursor:
    def __init__(self, *, superseded_by=None):
        self.superseded_by = superseded_by
        self.kind = ""
        self.statements = []

    def execute(self, sql, params):
        params = tuple(params or ())
        assert len(re.findall(r"%s", sql)) == len(params)
        normalized = " ".join(sql.lower().split())
        self.statements.append((normalized, params))
        if "select entitlement_id, account_id, status" in normalized:
            self.kind = "existing"
        elif "select entitlement_id, external_purchase_id" in normalized:
            self.kind = "active"
        else:
            self.kind = "other"

    def fetchone(self):
        assert self.kind == "existing"
        return {
            "entitlement_id": "entitlement-current",
            "account_id": ACCOUNT_ID,
            "status": "active" if not self.superseded_by else "canceled",
            "last_provider_event_at": datetime(2026, 8, 18, tzinfo=timezone.utc),
            "superseded_by_purchase_id": self.superseded_by,
        }

    def fetchall(self):
        assert self.kind == "active"
        return [{
            "entitlement_id": "entitlement-current",
            "external_purchase_id": "purchase-token",
        }]


class _ExistingConnection:
    def __init__(self, *, superseded_by=None):
        self.cursor_value = _ExistingCursor(superseded_by=superseded_by)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, **_kwargs):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def test_duplicate_verification_updates_same_row_without_stacking(monkeypatch):
    connection = _ExistingConnection()
    monkeypatch.setattr(ent, "get_db", lambda: connection)
    result = ent.reconcile_google_play_storage_entitlement(
        ACCOUNT_ID,
        _active_update(event_id="duplicate-verification"),
    )
    sql = "\n".join(statement for statement, _ in connection.cursor_value.statements)
    assert result == ("entitlement-current", "unchanged")
    assert "update billing_entitlements" in sql
    assert "insert into billing_entitlements" not in sql
    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_superseded_old_token_replay_cannot_restore_a_grant(monkeypatch):
    connection = _ExistingConnection(superseded_by="purchase-token-new")
    monkeypatch.setattr(ent, "get_db", lambda: connection)
    with pytest.raises(ent.StaleProviderEventError):
        ent.reconcile_google_play_storage_entitlement(
            ACCOUNT_ID,
            _active_update(token="purchase-token", event_id="old-token-replay"),
        )
    assert connection.commits == 0
    assert connection.rollbacks == 1


class _JSONRequest:
    async def json(self):
        return {"message": {}}


@pytest.mark.asyncio
async def test_replacement_rtdn_resolves_unbound_new_token_from_authoritative_link(
    monkeypatch,
):
    notification = {
        "version": "1.0",
        "packageName": google.GOOGLE_PLAY_PACKAGE_NAME,
        "eventTimeMillis": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
        "subscriptionNotification": {
            "version": "1.0",
            "notificationType": 4,
            "purchaseToken": "purchase-token-new",
        },
    }
    authoritative = _payload(
        [_line(
            google.GOOGLE_PLAY_PRODUCT_100GB,
            replaced_product_id=google.GOOGLE_PLAY_PRODUCT_50GB,
            replacement_mode="CHARGE_PRORATED_PRICE",
        )],
        linked="purchase-token-old",
    )
    publisher_calls = []

    class Publisher:
        def get_subscription(self, token):
            publisher_calls.append(token)
            return authoritative

    verified = []
    finishes = []
    monkeypatch.setattr(provider_routes, "_verify_google_pubsub_request", lambda _r: None)
    monkeypatch.setattr(
        provider_routes,
        "_decode_pubsub_message",
        lambda _payload: ("replacement-event", notification),
    )
    monkeypatch.setattr(ent, "claim_provider_event", lambda **_kwargs: True)
    monkeypatch.setattr(
        ent,
        "find_account_for_purchase",
        lambda _provider, token: ACCOUNT_ID if token == "purchase-token-old" else None,
    )
    monkeypatch.setattr(
        ent,
        "finish_provider_event",
        lambda **kwargs: finishes.append(kwargs),
    )
    monkeypatch.setattr(google, "GooglePlayPublisherClient", Publisher)
    monkeypatch.setattr(
        google,
        "verify_and_apply_google_subscription",
        lambda **kwargs: (
            verified.append(kwargs)
            or SimpleNamespace(normalized_status="active")
        ),
    )

    result = await provider_routes.google_play_rtdn(_JSONRequest())

    assert result == {"outcome": "applied", "status": "active"}
    assert publisher_calls == ["purchase-token-new"]
    assert verified[0]["account_id"] == ACCOUNT_ID
    assert verified[0]["authoritative_payload"] is authoritative
    assert verified[0]["publisher"].__class__ is Publisher
    assert finishes[-1]["outcome"] == "applied"


@pytest.mark.asyncio
async def test_duplicate_subscription_rtdn_reconciles_only_once(monkeypatch):
    notification = {
        "version": "1.0",
        "packageName": google.GOOGLE_PLAY_PACKAGE_NAME,
        "eventTimeMillis": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
        "subscriptionNotification": {
            "version": "1.0",
            "notificationType": 2,
            "purchaseToken": "purchase-token",
        },
    }
    claims = iter((True, False))
    verified = []
    monkeypatch.setattr(provider_routes, "_verify_google_pubsub_request", lambda _r: None)
    monkeypatch.setattr(
        provider_routes,
        "_decode_pubsub_message",
        lambda _payload: ("duplicate-event", notification),
    )
    monkeypatch.setattr(ent, "claim_provider_event", lambda **_kwargs: next(claims))
    monkeypatch.setattr(
        ent, "find_account_for_purchase", lambda *_args: ACCOUNT_ID,
    )
    monkeypatch.setattr(ent, "finish_provider_event", lambda **_kwargs: None)
    monkeypatch.setattr(
        google,
        "verify_and_apply_google_subscription",
        lambda **kwargs: (
            verified.append(kwargs)
            or SimpleNamespace(normalized_status="active")
        ),
    )

    first = await provider_routes.google_play_rtdn(_JSONRequest())
    second = await provider_routes.google_play_rtdn(_JSONRequest())

    assert first == {"outcome": "applied", "status": "active"}
    assert second == {"outcome": "duplicate"}
    assert len(verified) == 1


def test_schema_enforces_one_grant_and_preserves_data_on_rollback():
    migration = (
        Path(__file__).parent
        / "migrations/versions/0043_google_play_storage_tiers.py"
    ).read_text()
    lowered = migration.lower()
    assert "billing_entitlements_one_google_storage_grant_uniq" in lowered
    assert "entitlement_family = 'storage'" in lowered
    assert "scheduled_product_id" in lowered
    assert "scheduled_effective_at" in lowered
    assert "superseded_by_purchase_id" in lowered
    assert "delete from" not in lowered
    assert "drop table" not in lowered
    assert "def downgrade()" in lowered
    assert "pass" in lowered[lowered.index("def downgrade()") :]


def test_over_quota_downgrade_policy_keeps_reads_and_deletes_out_of_reconciler():
    root = Path(__file__).parent
    reconciler = (root / "billing_entitlements.py").read_text().lower()
    main_source = (root / "main.py").read_text().lower()
    chunked_source = (root / "routes/chunked_upload_routes.py").read_text().lower()
    function = reconciler[
        reconciler.index("def reconcile_google_play_storage_entitlement") :
        reconciler.index("def revoke_verified_purchase_entitlement")
    ]
    assert "delete from" not in function
    assert "projected_total > _billing_limit" in main_source
    assert "projected > _billing_limit" in chunked_source


def test_free_and_google_lifecycle_status_policy_is_preserved():
    past = datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert ent.normalize_google_subscription_state(
        "SUBSCRIPTION_STATE_ACTIVE", expiry_time=FUTURE,
    ) == "active"
    assert ent.normalize_google_subscription_state(
        "SUBSCRIPTION_STATE_IN_GRACE_PERIOD", expiry_time=FUTURE,
    ) == "grace_period"
    assert ent.normalize_google_subscription_state(
        "SUBSCRIPTION_STATE_CANCELED", expiry_time=FUTURE,
    ) == "active"
    assert ent.normalize_google_subscription_state(
        "SUBSCRIPTION_STATE_ON_HOLD", expiry_time=FUTURE,
    ) == "delinquent"
    assert ent.normalize_google_subscription_state(
        "SUBSCRIPTION_STATE_EXPIRED", expiry_time=past,
    ) == "expired"
    assert billing.get_effective_storage_limit(None) == 1_073_741_824
