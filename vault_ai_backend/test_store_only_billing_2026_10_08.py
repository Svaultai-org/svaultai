from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import billing
import billing_entitlements as ent
from routes import billing_routes, provider_billing_routes


ACCOUNT_ID = "11111111-1111-1111-1111-111111111111"
FUTURE = datetime.now(timezone.utc) + timedelta(days=30)
PAST = datetime.now(timezone.utc) - timedelta(days=1)
FREE_BYTES = 1_073_741_824
PAID_BYTES = 53_687_091_200


class _Cursor:
    def __init__(self, rows, statements):
        self.rows = rows
        self.statements = statements

    def execute(self, sql, params):
        self.statements.append((sql, params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Connection:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def cursor(self, **_kwargs):
        return _Cursor(self.rows, self.statements)

    def close(self):
        pass


def _row(provider="apple", *, status="active", expiry=FUTURE, quantity=1):
    return {
        "entitlement_id": f"entitlement-{provider}-{quantity}",
        "provider": provider,
        "entitlement_family": "storage",
        "external_purchase_id": f"purchase-{provider}-{quantity}",
        "product_id": f"{provider}.storage.50gb",
        "plan_id": "monthly-auto",
        "status": status,
        "quantity": quantity,
        "entitlement_bytes": PAID_BYTES * quantity,
        "current_period_end": expiry,
        "cancel_at_period_end": False,
        "metadata_jsonb": {"billing_period": "P1M"},
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "ownership_current_provider": None,
        "ownership_current_entitlement_id": None,
    }


def _resolve(monkeypatch, rows):
    connection = _Connection(rows)
    monkeypatch.setattr(ent, "get_db", lambda: connection)
    return ent.get_normalized_account_entitlement(ACCOUNT_ID), connection


@pytest.mark.parametrize("provider", ["apple", "google_play"])
@pytest.mark.parametrize("status", ["active", "reactivated", "grace_period"])
def test_only_verified_store_with_future_expiry_grants(monkeypatch, provider, status):
    resolved, connection = _resolve(monkeypatch, [_row(provider, status=status)])
    assert resolved.provider == provider
    assert resolved.purchased_bytes == PAID_BYTES
    assert resolved.current_provider == provider
    assert resolved.has_active_subscription is True
    assert resolved.status == ("in_grace" if status == "grace_period" else "active")
    assert resolved.display_tier == "50 GB"
    assert resolved.ownership_status == "owned"
    sql = connection.statements[0][0]
    assert "e.verification_state = 'verified'" in sql
    assert "e.provider IN ('apple', 'google_play')" in sql
    assert "account_subscriptions" not in sql


@pytest.mark.parametrize("provider", ["stripe_legacy", "web_card", "stripe", "paypal"])
def test_retired_provider_records_are_history_only(monkeypatch, provider):
    resolved, _ = _resolve(monkeypatch, [_row(provider)])
    assert resolved is None
    assert ent._public_provider(provider) == "free"


@pytest.mark.parametrize("provider", ["apple", "google_play"])
@pytest.mark.parametrize("expiry,expected", [(None, "pending"), (PAST, "expired")])
def test_missing_or_lapsed_store_expiry_cannot_grant_forever(
    monkeypatch, provider, expiry, expected,
):
    resolved, _ = _resolve(monkeypatch, [_row(provider, expiry=expiry)])
    assert resolved.purchased_bytes == 0
    assert resolved.block_count == 0
    assert resolved.has_active_subscription is False
    assert resolved.provider == resolved.current_provider == "free"
    assert resolved.status == expected
    assert resolved.ownership_status == "free"


@pytest.mark.parametrize("status", ["expired", "revoked", "refunded", "canceled", "pending"])
def test_non_granting_store_returns_free_without_false_payment_failure(monkeypatch, status):
    resolved, _ = _resolve(monkeypatch, [_row(status=status)])
    assert resolved.provider == "free"
    assert resolved.purchased_bytes == 0
    assert resolved.has_active_subscription is False
    assert resolved.status == status
    assert resolved.status != "past_due"


def test_actual_store_delinquency_remains_distinct(monkeypatch):
    resolved, _ = _resolve(monkeypatch, [_row(status="delinquent")])
    assert resolved.status == "past_due"
    assert resolved.purchased_bytes == 0


def test_retired_owner_does_not_block_valid_store_purchase(monkeypatch):
    store = _row("google_play")
    store.update({
        "ownership_current_provider": "web_card",
        "ownership_migration_status": "conflict",
        "ownership_reason_code": "multiple_active_storage_entitlements",
        "ownership_target_provider": "web_card",
    })
    resolved, _ = _resolve(monkeypatch, [_row("stripe_legacy"), store])
    assert resolved.provider == "google_play"
    assert resolved.ownership_status == "owned"
    assert resolved.migration_status == "none"
    assert resolved.conflict_reason_code is None
    assert resolved.target_provider is None


def test_multiple_stores_never_sum_and_keep_exact_live_owner(monkeypatch):
    google = _row("google_play")
    apple = _row("apple", quantity=5)
    for row in (google, apple):
        row["ownership_current_provider"] = "apple"
        row["ownership_current_entitlement_id"] = apple["entitlement_id"]
    resolved, _ = _resolve(monkeypatch, [google, apple])
    assert resolved.provider == "apple"
    assert resolved.purchased_bytes == PAID_BYTES * 5
    assert resolved.purchased_bytes != PAID_BYTES * 6
    assert resolved.ownership_status == "conflict"
    assert resolved.conflict_reason_code == "multiple_active_storage_entitlements"


def test_natural_expiry_releases_stale_conflict_metadata(monkeypatch):
    active = _row("apple")
    expired = _row("google_play", expiry=PAST)
    active.update({
        "ownership_current_provider": "apple",
        "ownership_current_entitlement_id": active["entitlement_id"],
        "ownership_migration_status": "conflict",
        "ownership_reason_code": "multiple_active_storage_entitlements",
    })
    resolved, _ = _resolve(monkeypatch, [active, expired])
    assert resolved.provider == "apple"
    assert resolved.ownership_status == "owned"
    assert resolved.conflict_reason_code is None


def _account_fixture(monkeypatch, *, source="stripe", status="active", grant=0):
    row = {
        "account_id": ACCOUNT_ID, "account_type": "individual",
        "sales_channel": "self_service", "storage_bytes_grant": grant,
        "used_bytes": 20, "source": source, "status": status,
        "block_count": 1, "purchased_bytes": PAID_BYTES,
        "current_period_end": None,
    }
    connection = _Connection([row])
    monkeypatch.setattr(billing, "get_db", lambda: connection)
    monkeypatch.setattr(billing, "included_bytes", lambda: FREE_BYTES)
    monkeypatch.setattr(billing, "block_bytes", lambda: PAID_BYTES)
    monkeypatch.setattr(billing, "block_price_cents_usd", lambda: 2500)
    monkeypatch.setattr(billing, "self_service_max_blocks", lambda: 100)
    return connection


@pytest.mark.parametrize("source", ["stripe", "apple", "admin_grant", "none"])
@pytest.mark.parametrize("status", ["active", "past_due", "in_grace", "expired"])
def test_legacy_subscription_never_grants_or_locks_free_web(monkeypatch, source, status):
    _account_fixture(monkeypatch, source=source, status=status)
    monkeypatch.setattr(ent, "get_normalized_account_entitlement", lambda _account: None)
    resolved = billing.get_entitlement(ACCOUNT_ID)
    assert resolved.provider == "free"
    assert resolved.purchased_bytes == 0
    assert resolved.effective_limit_bytes == FREE_BYTES
    assert resolved.has_active_subscription is False
    assert resolved.status == "none"


def test_store_ledger_outage_never_revives_legacy_paid_storage(monkeypatch):
    _account_fixture(monkeypatch)

    def unavailable(_account):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(ent, "get_normalized_account_entitlement", unavailable)
    resolved = billing.get_entitlement(ACCOUNT_ID)
    assert resolved.provider == "free"
    assert resolved.purchased_bytes == 0
    assert resolved.effective_limit_bytes == FREE_BYTES
    assert resolved.status == "none"


def test_verified_store_overrides_legacy_history(monkeypatch):
    normalized, _ = _resolve(monkeypatch, [_row("google_play", quantity=5)])
    _account_fixture(monkeypatch, status="past_due")
    monkeypatch.setattr(ent, "get_normalized_account_entitlement", lambda _account: normalized)
    resolved = billing.get_entitlement(ACCOUNT_ID)
    assert resolved.provider == "google_play"
    assert resolved.purchased_bytes == PAID_BYTES * 5
    assert resolved.effective_limit_bytes == PAID_BYTES * 5
    assert resolved.has_active_subscription is True


def test_separate_non_billing_grant_and_used_data_are_preserved(monkeypatch):
    connection = _account_fixture(monkeypatch, grant=1234)
    monkeypatch.setattr(ent, "get_normalized_account_entitlement", lambda _account: None)
    resolved = billing.get_entitlement(ACCOUNT_ID)
    assert resolved.effective_limit_bytes == FREE_BYTES + 1234
    assert resolved.used_bytes == 20
    sql = connection.statements[0][0]
    assert "s.storage_bytes_grant_expires_at > NOW()" in sql
    assert "s.purchased_bytes" not in sql
    assert "s.status" not in sql


@pytest.mark.asyncio
async def test_public_provider_catalog_is_stores_only(monkeypatch):
    import apple_billing

    monkeypatch.setattr(provider_billing_routes, "_account_id", lambda _principal: ACCOUNT_ID)
    monkeypatch.setattr(apple_billing, "configured_apple_catalog", lambda: {})
    catalog = await provider_billing_routes.billing_providers(principal={"vault_id": "fixture"})
    assert set(catalog) == {"apple", "google_play"}
    paths = {route.path for route in provider_billing_routes.router.routes}
    assert "/billing/apple/verify-transaction" in paths
    assert "/billing/google-play/verify" in paths
    assert not any("checkout" in path or "stripe" in path or "paypal" in path for path in paths)


def test_free_contract_has_no_card_checkout_flag():
    payload = billing_routes._billing_me_safe_default_payload()
    assert payload["provider"] == "free"
    assert payload["display_tier"] == "1 GB"
    assert "web_card_purchase_allowed" not in payload
    assert "web_card_purchase_allowed" not in billing.StorageEntitlement.__dataclass_fields__
    assert ent.canonical_storage_display_tier(1_073_741_824_000) == "1 TB"


@pytest.mark.parametrize("provider", ["stripe_legacy", "web_card", "stripe", "paypal"])
def test_runtime_cannot_accept_retired_provider_proof(provider):
    update = ent.VerifiedEntitlementUpdate(
        provider=provider, external_purchase_id="purchase", product_id="product",
        quantity=1, entitlement_bytes=PAID_BYTES, status="active",
        provider_status="ACTIVE", environment="production", current_period_end=FUTURE,
    )
    with pytest.raises(ValueError, match="unsupported billing provider"):
        update.validate()


@pytest.mark.parametrize("old_expiry,expected_status", [(None, "pending"), (PAST, "expired")])
def test_google_new_purchase_releases_lapsed_unique_index_without_deleting_history(
    monkeypatch, old_expiry, expected_status,
):
    class Cursor:
        def __init__(self):
            self.statements = []
            self.old_status = "active"
            self.kind = ""

        def execute(self, sql, params):
            normalized = " ".join(sql.lower().split())
            self.statements.append(normalized)
            if "select entitlement_id, account_id, status" in normalized:
                self.kind = "existing"
            elif "set status = case when current_period_end is null" in normalized:
                assert "current_period_end is null or current_period_end <= now()" in normalized
                self.old_status = "pending" if old_expiry is None else "expired"
                self.kind = "other"
            elif "select entitlement_id, external_purchase_id" in normalized:
                assert "current_period_end > now()" in normalized
                self.kind = "active"
            elif "insert into billing_entitlements" in normalized:
                # Model the partial unique index: only retiring the stale
                # active status permits the new one-of-N purchase insert.
                assert self.old_status not in ent.GRANTING_STATUSES
                self.kind = "insert"
            else:
                self.kind = "other"

        def fetchone(self):
            if self.kind == "existing":
                return None
            assert self.kind == "insert"
            return {"entitlement_id": "new-store-entitlement"}

        def fetchall(self):
            assert self.kind == "active"
            return []

    class Connection:
        def __init__(self):
            self.value = Cursor()
            self.committed = False

        def cursor(self, **_kwargs):
            return self.value

        def commit(self):
            self.committed = True

        def rollback(self):
            raise AssertionError("unexpected rollback")

        def close(self):
            pass

    connection = Connection()
    monkeypatch.setattr(ent, "get_db", lambda: connection)
    update = ent.VerifiedEntitlementUpdate(
        provider="google_play", external_purchase_id="new-token",
        product_id="svaultai_storage_50gb", plan_id="monthly-auto", quantity=1,
        entitlement_bytes=PAID_BYTES, status="active", provider_status="ACTIVE",
        environment="production", current_period_end=FUTURE,
    )
    result = ent.reconcile_google_play_storage_entitlement(ACCOUNT_ID, update)
    assert result == ("new-store-entitlement", "none_to_active")
    assert connection.committed is True
    assert connection.value.old_status == expected_status
    assert not any("delete from" in sql for sql in connection.value.statements)


def test_retirement_migration_keeps_history_and_enforces_one_future_store_owner():
    root = Path(__file__).parent
    migration = (root / "migrations/versions/0046_store_only_billing.py").read_text()
    assert 'down_revision = "0045_private_vault_identifiers"' in migration
    assert "DROP TRIGGER IF EXISTS account_subscriptions_one_storage_owner" in migration
    assert "DROP FUNCTION IF EXISTS enforce_legacy_storage_billing_owner" in migration
    assert "pg_advisory_xact_lock" in migration
    assert "e.provider IN ('apple', 'google_play')" in migration
    assert "e.current_period_end > NOW()" in migration
    assert "NEW.current_period_end > NOW()" in migration
    assert "NEW.current_period_end IS NOT NULL" in migration
    assert "OLD.current_period_end IS NOT NULL" in migration
    assert "OLD.original_transaction_id <> ''" in migration
    assert "NEW.original_transaction_id" in migration
    assert "OLD.entitlement_id = NEW.entitlement_id" in migration
    assert "same_live_purchase" in migration
    assert "one_active_storage_billing_owner" in migration
    assert "storage_owner_no_legacy_connection" in migration
    assert "DELETE FROM" not in migration
    assert "DROP TABLE" not in migration
    assert "UPDATE account_subscriptions" not in migration
    assert "UPDATE billing_entitlements" not in migration
    assert "vaults" not in migration
    assert "data-preserving" in migration


def test_database_owner_constraint_has_safe_domain_error():
    class Diagnostic:
        constraint_name = "one_active_storage_billing_owner"

    class ConstraintViolation(Exception):
        diag = Diagnostic()

    with pytest.raises(ent.StorageBillingOwnerConflictError, match="active_storage_billing_owner"):
        ent._raise_storage_owner_conflict(ConstraintViolation())
