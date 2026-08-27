"""Fail-closed Apple transaction and Server Notifications V2 boundary.

The shared backend is usable from the future StoreKit 2 client, but no Apple
product identifier is invented here. Products must be explicitly configured
after App Store Connect setup and validated on macOS/Xcode.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from billing_entitlements import (
    PurchaseAlreadyBoundError,
    VerifiedEntitlementUpdate,
    canonical_storage_display_tier,
    normalize_apple_transaction_state,
    upsert_verified_entitlement,
)


class AppleBillingConfigurationError(RuntimeError):
    pass


class AppleTransactionVerificationError(RuntimeError):
    pass


class AppleTransactionOwnershipError(AppleTransactionVerificationError):
    """A valid Apple purchase is bound to a different SVaultAI account."""


def apple_app_account_token(account_id: str) -> str:
    """StoreKit-compatible opaque UUID; it reveals no vault identifier."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"svaultai:billing:{account_id}"))


def configured_apple_catalog() -> dict[str, dict[str, Any]]:
    raw = os.getenv("VAULTAI_APPLE_PRODUCT_MAP_JSON", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AppleBillingConfigurationError("invalid Apple product map") from exc
    if not isinstance(payload, dict):
        raise AppleBillingConfigurationError("invalid Apple product map")
    catalog: dict[str, dict[str, Any]] = {}
    for product_id, config in payload.items():
        if not isinstance(product_id, str) or not isinstance(config, dict):
            raise AppleBillingConfigurationError("invalid Apple product entry")
        try:
            quantity = int(config.get("quantity") or 0)
            entitlement_bytes = int(config.get("entitlement_bytes") or 0)
        except (TypeError, ValueError) as exc:
            raise AppleBillingConfigurationError(
                "invalid Apple entitlement entry"
            ) from exc
        billing_period = str(config.get("billing_period") or "").strip().upper()
        if (
            quantity < 1
            or entitlement_bytes < 1
            or re.fullmatch(r"P[1-9][0-9]*[DWMY]", billing_period) is None
        ):
            raise AppleBillingConfigurationError("invalid Apple entitlement entry")
        catalog[product_id] = {
            "quantity": quantity,
            "entitlement_bytes": entitlement_bytes,
            "plan_id": str(config.get("plan_id") or "monthly"),
            "billing_period": billing_period,
        }
    return catalog


def _milliseconds_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def enum_text(value: Any) -> str:
    """Return an App Store enum's wire value, while accepting plain strings."""
    raw = getattr(value, "value", value)
    return str(raw or "")


class AppleSignedDataVerifier:
    """Small adapter around Apple's official App Store Server library."""

    def __init__(self, environment: str):
        try:
            from appstoreserverlibrary.models.Environment import Environment
            from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier
        except ImportError as exc:
            raise AppleBillingConfigurationError(
                "Apple server verification dependency is unavailable"
            ) from exc
        bundle_id = os.getenv("VAULTAI_APPLE_BUNDLE_ID", "").strip()
        cert_dir = os.getenv("VAULTAI_APPLE_ROOT_CERT_DIR", "").strip()
        if not bundle_id or not cert_dir:
            raise AppleBillingConfigurationError(
                "Apple bundle ID and root certificate directory are required"
            )
        paths = sorted(Path(cert_dir).glob("*.cer"))
        try:
            roots = [path.read_bytes() for path in paths]
        except OSError as exc:
            raise AppleBillingConfigurationError(
                "Apple root certificates are unreadable"
            ) from exc
        if not roots:
            raise AppleBillingConfigurationError("Apple root certificates missing")
        if environment == "production":
            app_id_raw = os.getenv("VAULTAI_APPLE_APP_ID", "").strip()
            if not app_id_raw:
                raise AppleBillingConfigurationError(
                    "Apple numeric app ID is required for production"
                )
            env_value = Environment.PRODUCTION
            try:
                app_id = int(app_id_raw)
            except ValueError as exc:
                raise AppleBillingConfigurationError(
                    "Apple numeric app ID is invalid"
                ) from exc
        elif environment == "sandbox":
            env_value = Environment.SANDBOX
            app_id = None
        else:
            raise AppleBillingConfigurationError("invalid Apple environment")
        self.environment = environment
        self._delegate = SignedDataVerifier(
            roots, True, env_value, bundle_id, app_id,
        )

    def verify_transaction(self, signed_transaction: str):
        try:
            return self._delegate.verify_and_decode_signed_transaction(
                signed_transaction,
            )
        except Exception as exc:
            raise AppleTransactionVerificationError(
                "Apple transaction signature verification failed"
            ) from exc

    def verify_notification(self, signed_payload: str):
        try:
            return self._delegate.verify_and_decode_notification(signed_payload)
        except Exception as exc:
            raise AppleTransactionVerificationError(
                "Apple notification signature verification failed"
            ) from exc

    def verify_renewal_info(self, signed_renewal_info: str):
        try:
            return self._delegate.verify_and_decode_renewal_info(
                signed_renewal_info,
            )
        except Exception as exc:
            raise AppleTransactionVerificationError(
                "Apple renewal signature verification failed"
            ) from exc


def _apple_auto_renew_state(renewal_info: Any) -> str:
    if renewal_info is None:
        return "unknown"
    status = _attr(renewal_info, "autoRenewStatus")
    raw = getattr(status, "value", status)
    text = str("" if raw is None else raw).strip().upper()
    if text in {"1", "ON", "AUTO_RENEW_ENABLED", "TRUE"}:
        return "enabled"
    if text in {"0", "OFF", "AUTO_RENEW_DISABLED", "FALSE"}:
        return "disabled"
    return "unknown"


def _transaction_update(
    transaction: Any,
    *,
    environment: str,
    notification_type: str,
    subtype: str = "",
    event_id: Optional[str] = None,
    renewal_info: Any = None,
) -> VerifiedEntitlementUpdate:
    notification_type = enum_text(notification_type)
    subtype = enum_text(subtype)
    catalog = configured_apple_catalog()
    product_id = str(_attr(transaction, "productId") or "")
    config = catalog.get(product_id)
    if not config:
        raise AppleBillingConfigurationError(
            "Apple product is not configured for an SVaultAI entitlement"
        )
    transaction_id = str(_attr(transaction, "transactionId") or "")
    original_id = str(_attr(transaction, "originalTransactionId") or "")
    if not transaction_id or not original_id:
        raise AppleTransactionVerificationError("Apple transaction identity missing")
    expires = _milliseconds_datetime(_attr(transaction, "expiresDate"))
    purchased = _milliseconds_datetime(_attr(transaction, "purchaseDate"))
    revoked = _attr(transaction, "revocationDate") not in (None, "")
    normalized = normalize_apple_transaction_state(
        notification_type=notification_type,
        subtype=subtype,
        expires_at=expires,
        revoked=revoked,
    )
    renewal_state = _apple_auto_renew_state(renewal_info)
    renewal_product_id = str(
        _attr(renewal_info, "autoRenewProductId") or ""
    )
    if renewal_product_id and renewal_product_id not in catalog:
        raise AppleBillingConfigurationError(
            "Apple renewal product is not configured"
        )
    return VerifiedEntitlementUpdate(
        provider="apple",
        external_purchase_id=transaction_id,
        original_transaction_id=original_id,
        product_id=product_id,
        plan_id=str(config["plan_id"]),
        quantity=int(config["quantity"]),
        entitlement_bytes=int(config["entitlement_bytes"]),
        status=normalized,
        provider_status=(notification_type or "TRANSACTION_VERIFIED").upper(),
        environment=environment,
        auto_renewing=renewal_state == "enabled",
        cancel_at_period_end=renewal_state == "disabled",
        current_period_start=purchased,
        current_period_end=expires,
        provider_event_at=(
            _milliseconds_datetime(_attr(transaction, "signedDate"))
            or purchased
            or datetime.now(timezone.utc)
        ),
        provider_event_id=event_id,
        metadata={
            "subtype": subtype or None,
            "billing_period": str(config["billing_period"]),
            "display_capacity": canonical_storage_display_tier(
                int(config["entitlement_bytes"]),
            ),
            "apple_auto_renew_state": renewal_state,
            "renewal_product_id": renewal_product_id or None,
            "renewal_info_verified": renewal_info is not None,
        },
    )


def verify_and_apply_apple_transaction(
    *,
    account_id: str,
    signed_transaction: str,
    environment: str,
    verifier: Optional[AppleSignedDataVerifier] = None,
) -> dict[str, Any]:
    if not signed_transaction or len(signed_transaction) > 100_000:
        raise AppleTransactionVerificationError("invalid Apple signed transaction")
    verifier = verifier or AppleSignedDataVerifier(environment)
    transaction = verifier.verify_transaction(signed_transaction)
    supplied_account = str(_attr(transaction, "appAccountToken") or "")
    # Restored StoreKit transactions created before an appAccountToken was
    # attached legitimately decode with no token.  Permit that transaction to
    # establish its first authenticated SVaultAI binding; the provider-wide
    # purchase/original-transaction uniqueness checks in
    # upsert_verified_entitlement still prevent rebinding or transfer.  A
    # present token remains mandatory authority and must match exactly.
    if (
        supplied_account
        and supplied_account.lower() != apple_app_account_token(account_id)
    ):
        raise AppleTransactionOwnershipError(
            "Apple purchase is not associated with this SVaultAI account"
        )
    update = _transaction_update(
        transaction,
        environment=environment,
        notification_type="TRANSACTION_VERIFIED",
    )
    try:
        entitlement_id, transition = upsert_verified_entitlement(
            account_id, update,
        )
    except PurchaseAlreadyBoundError as exc:
        raise AppleTransactionOwnershipError(
            "Apple purchase is already bound to another SVaultAI account"
        ) from exc
    return {
        "verified": True,
        "provider": "apple",
        "product_id": update.product_id,
        "status": update.status,
        "entitlement_id": entitlement_id,
        "transition": transition,
    }


def decode_verified_apple_notification(
    signed_payload: str,
    *,
    verifier_factory=AppleSignedDataVerifier,
) -> tuple[str, Any, Any]:
    """Verify strictly in each configured environment; never decode unsigned JWS."""
    errors = []
    configured_environment_count = 0
    environments = ["production"]
    if os.getenv("VAULTAI_APPLE_ACCEPT_SANDBOX", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        environments.append("sandbox")
    for environment in environments:
        try:
            verifier = verifier_factory(environment)
            configured_environment_count += 1
            return environment, verifier, verifier.verify_notification(signed_payload)
        except AppleBillingConfigurationError as exc:
            errors.append(exc)
        except AppleTransactionVerificationError as exc:
            errors.append(exc)
    if configured_environment_count == 0:
        raise AppleBillingConfigurationError(
            "Apple notification verification is not configured"
        ) from (errors[-1] if errors else None)
    raise AppleTransactionVerificationError(
        "Apple notification could not be verified in an enabled environment"
    ) from (errors[-1] if errors else None)
