from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

import billing
import billing_entitlements as ent
from routes import billing_routes, provider_billing_routes


ACCOUNT_ID = "11111111-1111-1111-1111-111111111111"
FUTURE = datetime.now(timezone.utc) + timedelta(days=30)


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _sql, _params):
        pass

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Connection:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self, **_kwargs):
        return _Cursor(self.rows)

    def close(self):
        pass


def _row(
    provider: str,
    product_id: str,
    quantity: int,
    *,
    display_tier: str,
    plan_id: str = "monthly-auto",
    migration_current: str | None = None,
    migration_target: str | None = None,
    migration_status: str = "none",
    ownership_reason: str | None = None,
):
    storage_bytes = ent.CANONICAL_STORAGE_TIER_LABELS
    reverse = {label: value for value, label in storage_bytes.items()}
    return {
        "entitlement_id": f"entitlement-{provider}-{quantity}",
        "provider": provider,
        "entitlement_family": "storage",
        "external_purchase_id": f"purchase-{provider}-{quantity}",
        "product_id": product_id,
        "plan_id": plan_id,
        "status": "active",
        "quantity": quantity,
        "entitlement_bytes": reverse[display_tier],
        "current_period_end": FUTURE,
        "cancel_at_period_end": False,
        "metadata_jsonb": {
            "billing_period": "P1M",
            "display_capacity": display_tier,
        },
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "ownership_current_provider": migration_current,
        "ownership_target_provider": migration_target,
        "ownership_migration_status": migration_status,
        "ownership_reason_code": ownership_reason,
    }


@pytest.mark.parametrize(
    ("product_id", "quantity", "display_tier"),
    [
        ("svaultai_storage_50gb", 1, "50 GB"),
        ("svaultai_storage_100gb", 2, "100 GB"),
        ("svaultai_storage_250gb", 5, "250 GB"),
        ("svaultai_storage_1tb", 20, "1 TB"),
    ],
)
def test_google_billing_contract_exposes_verified_tier(
    monkeypatch, product_id, quantity, display_tier,
):
    monkeypatch.setattr(
        ent, "get_db", lambda: _Connection([
            _row("google_play", product_id, quantity, display_tier=display_tier),
        ]),
    )
    normalized = ent.get_normalized_account_entitlement(ACCOUNT_ID)
    assert normalized.provider == "google_play"
    assert normalized.product_id == product_id
    assert normalized.base_plan_id == "monthly-auto"
    assert normalized.billing_period == "P1M"
    assert normalized.display_tier == display_tier
    assert normalized.subscription_status == "active"
    assert normalized.entitlement_family == "storage"
    assert normalized.web_card_purchase_allowed is False


@pytest.mark.parametrize(
    ("provider", "product_id", "display_tier", "public_provider"),
    [
        ("apple", "svaultai.storage.100gb.monthly", "100 GB", "apple"),
        ("web_card", "svaultai_web_250gb", "250 GB", "web_card"),
        ("stripe_legacy", "legacy_50gb", "50 GB", "web_card"),
    ],
)
def test_apple_and_web_card_contracts_are_provider_neutral(
    monkeypatch, provider, product_id, display_tier, public_provider,
):
    monkeypatch.setattr(
        ent, "get_db", lambda: _Connection([
            _row(provider, product_id, 2, display_tier=display_tier),
        ]),
    )
    normalized = ent.get_normalized_account_entitlement(ACCOUNT_ID)
    assert normalized.provider == public_provider
    assert normalized.product_id == product_id
    assert normalized.display_tier == display_tier


@pytest.mark.parametrize(
    "providers",
    [
        ("google_play", "apple"),
        ("google_play", "web_card"),
        ("apple", "web_card"),
    ],
)
def test_multiple_provider_conflict_never_sums(monkeypatch, providers):
    first = _row(
        providers[0], f"{providers[0]}.50gb", 1, display_tier="50 GB",
    )
    second = _row(
        providers[1], f"{providers[1]}.250gb", 5, display_tier="250 GB",
    )
    monkeypatch.setattr(ent, "get_db", lambda: _Connection([first, second]))

    normalized = ent.get_normalized_account_entitlement(ACCOUNT_ID)

    assert normalized.provider == ent._public_provider(providers[0])
    assert normalized.storage_bytes == first["entitlement_bytes"]
    assert normalized.purchased_bytes != (
        first["entitlement_bytes"] + second["entitlement_bytes"]
    )
    assert normalized.ownership_status == "conflict"
    assert normalized.conflict_reason_code == (
        "multiple_active_storage_entitlements"
    )
    assert normalized.web_card_purchase_allowed is False


def test_pending_migration_keeps_current_provider_authoritative(monkeypatch):
    google = _row(
        "google_play", "svaultai_storage_50gb", 1,
        display_tier="50 GB", migration_current="apple",
        migration_target="web_card", migration_status="pending",
    )
    apple = _row(
        "apple", "svaultai.storage.250gb.monthly", 5,
        display_tier="250 GB", migration_current="apple",
        migration_target="web_card", migration_status="pending",
    )
    monkeypatch.setattr(ent, "get_db", lambda: _Connection([google, apple]))

    normalized = ent.get_normalized_account_entitlement(ACCOUNT_ID)

    assert normalized.provider == "apple"
    assert normalized.target_provider == "web_card"
    assert normalized.migration_status == "pending"
    assert normalized.web_card_purchase_allowed is False


def test_persisted_conflict_stays_closed_after_one_row_is_terminalized(
    monkeypatch,
):
    web = _row(
        "web_card", "svaultai_web_250gb", 5,
        display_tier="250 GB", migration_current="web_card",
        migration_status="conflict",
        ownership_reason="multiple_active_storage_entitlements",
    )
    monkeypatch.setattr(ent, "get_db", lambda: _Connection([web]))

    normalized = ent.get_normalized_account_entitlement(ACCOUNT_ID)

    assert normalized.ownership_status == "conflict"
    assert normalized.conflict_reason_code == (
        "multiple_active_storage_entitlements"
    )
    assert normalized.web_card_purchase_allowed is False


def test_free_contract_is_explicit_and_one_tb_is_canonical():
    payload = billing_routes._billing_me_safe_default_payload()
    assert payload["provider"] == "free"
    assert payload["display_tier"] == "1 GB"
    assert payload["subscription_status"] == "free"
    assert payload["web_card_purchase_allowed"] is True
    assert ent.canonical_storage_display_tier(1_073_741_824_000) == "1 TB"


def test_verified_store_entitlement_overrides_expired_legacy_admin_grant(
    monkeypatch,
):
    account_row = {
        "account_id": ACCOUNT_ID,
        "account_type": "individual",
        "sales_channel": "self_service",
        "status": "expired",
        "source": "admin_grant",
        "block_count": 0,
        "purchased_bytes": 0,
        "storage_bytes_grant": 0,
        "storage_bytes_grant_expires_at": None,
        "current_period_end": FUTURE,
        "admin_grant_expired": True,
        "cancel_at_period_end": False,
        "used_bytes": 0,
    }
    normalized = ent.NormalizedAccountEntitlement(
        purchased_bytes=268_435_456_000,
        block_count=5,
        status="active",
        source="google_play",
        current_period_end=FUTURE,
        cancel_at_period_end=False,
        has_active_subscription=True,
        provider="google_play",
        product_id="svaultai_storage_250gb",
        base_plan_id="monthly-auto",
        billing_period="P1M",
        storage_bytes=268_435_456_000,
        display_tier="250 GB",
        subscription_status="active",
        ownership_status="owned",
        current_provider="google_play",
        web_card_purchase_allowed=False,
    )
    monkeypatch.setattr(
        billing, "get_db", lambda: _Connection([account_row]),
    )
    monkeypatch.setattr(
        ent, "get_normalized_account_entitlement", lambda _account: normalized,
    )

    resolved = billing.get_entitlement(ACCOUNT_ID)

    assert resolved.provider == "google_play"
    assert resolved.display_tier == "250 GB"
    assert resolved.effective_limit_bytes == 268_435_456_000
    assert resolved.web_card_purchase_allowed is False


@pytest.mark.asyncio
async def test_billing_me_exposes_lossless_owner_contract(monkeypatch):
    fixture = billing.StorageEntitlement(
        account_id=ACCOUNT_ID,
        account_type="individual",
        sales_channel="self_service",
        included_bytes=1_073_741_824,
        purchased_bytes=268_435_456_000,
        storage_bytes_grant=0,
        effective_limit_bytes=268_435_456_000,
        used_bytes=0,
        percent_used=0.0,
        block_count=5,
        self_service_max_blocks=20,
        status="active",
        source="google_play",
        current_period_end=FUTURE.isoformat(),
        cancel_at_period_end=False,
        block_price_cents_usd=2500,
        block_bytes=53_687_091_200,
        has_active_subscription=True,
        provider="google_play",
        product_id="svaultai_storage_250gb",
        base_plan_id="monthly-auto",
        billing_period="P1M",
        storage_bytes=268_435_456_000,
        display_tier="250 GB",
        subscription_status="active",
        entitlement_family="storage",
        ownership_status="owned",
        current_provider="google_play",
        web_card_purchase_allowed=False,
    )
    monkeypatch.setattr(billing, "ensure_account_for_vault", lambda _vault: ACCOUNT_ID)
    monkeypatch.setattr(billing, "get_entitlement", lambda _account: fixture)
    monkeypatch.setattr(billing_routes, "_read_last_webhook_event", lambda _account: None)
    monkeypatch.setattr(billing_routes, "_count_recent_global_webhooks", lambda: 0)

    payload = await billing_routes.billing_me(principal={"vault_id": "fixture"})

    assert payload["provider"] == "google_play"
    assert payload["product_id"] == "svaultai_storage_250gb"
    assert payload["base_plan_id"] == "monthly-auto"
    assert payload["billing_period"] == "P1M"
    assert payload["storage_bytes"] == 268_435_456_000
    assert payload["display_tier"] == "250 GB"
    assert payload["subscription_status"] == "active"
    assert payload["entitlement_family"] == "storage"
    assert payload["web_card_purchase_allowed"] is False


def test_migration_defines_owner_and_pending_provider_state():
    migration = Path(
        "migrations/versions/0044_storage_billing_ownership.py"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE billing_provider_ownership" in migration
    assert "current_provider" in migration
    assert "target_provider" in migration
    assert "migration_status" in migration
    assert "one_active_storage_billing_owner" in migration
    assert "multiple_active_storage_entitlements" in migration


def test_database_owner_constraint_has_operator_safe_domain_error():
    class _Diagnostic:
        constraint_name = "one_active_storage_billing_owner"

    class _ConstraintViolation(Exception):
        diag = _Diagnostic()

    with pytest.raises(
        ent.StorageBillingOwnerConflictError,
        match="active_storage_billing_owner",
    ):
        ent._raise_storage_owner_conflict(_ConstraintViolation())


@pytest.mark.asyncio
async def test_web_checkout_is_provider_blocked_before_global_tombstone(
    monkeypatch,
):
    monkeypatch.setattr(
        provider_billing_routes, "_account_id", lambda _principal: ACCOUNT_ID,
    )
    monkeypatch.setattr(
        ent, "web_card_purchase_allowed_for_account", lambda _account: False,
    )
    with pytest.raises(HTTPException) as blocked:
        await provider_billing_routes.web_checkout_disabled(
            principal={"vault_id": "fixture"},
        )
    assert blocked.value.status_code == 409
    assert blocked.value.detail["code"] == "active_store_billing_owner"
