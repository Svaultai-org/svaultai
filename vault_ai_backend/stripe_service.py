

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import stripe
from psycopg2 import errors as pg_errors
from psycopg2.extras import RealDictCursor, Json

from billing import (
    block_bytes,
    block_price_cents_usd,
    blocks_to_bytes,
    is_within_self_service_ceiling,
)
from vault_core import get_db


logger = logging.getLogger(__name__)


def _get_env(name: str, *, required: bool) -> Optional[str]:
    val = os.getenv(name, "").strip()
    if not val:
        if required:
            return None
        return None
    return val


def get_stripe_api_key() -> Optional[str]:
    return _get_env("STRIPE_API_KEY", required=True)


def get_stripe_webhook_secret() -> Optional[str]:
    return _get_env("STRIPE_WEBHOOK_SECRET", required=True)


def get_stripe_block_price_id() -> Optional[str]:
    return _get_env("STRIPE_STORAGE_BLOCK_PRICE_ID", required=True)


def get_checkout_success_url() -> str:


    return _get_env("STRIPE_CHECKOUT_SUCCESS_URL", required=False) \
        or "https://app.vaultai.example/storage?checkout=success"


def get_checkout_cancel_url() -> str:
    return _get_env("STRIPE_CHECKOUT_CANCEL_URL", required=False) \
        or "https://app.vaultai.example/storage?checkout=cancel"


def get_portal_return_url() -> str:
    return _get_env("STRIPE_PORTAL_RETURN_URL", required=False) \
        or "https://app.vaultai.example/storage"


BILLING_ADMIN_HEALTH_SCHEMA: str = "billing_admin_health_v1"


def redact_stripe_id(raw: Optional[str], *, keep: int = 8) -> str:
    if not isinstance(raw, str) or not raw:
        return ""
    trimmed = raw.strip()
    if len(trimmed) <= keep:
        return trimmed
    return trimmed[:keep] + "..."


def _stripe_mode_label() -> str:
    api = os.getenv("STRIPE_API_KEY", "").strip()
    if not api:
        return "unconfigured"
    if api.startswith("sk_live_") or api.startswith("rk_live_"):
        return "live"
    if api.startswith("sk_test_") or api.startswith("rk_test_"):
        return "test"
    return "unknown"


def stripe_mode_label() -> str:
    return _stripe_mode_label()


def _allowed_redirect_origins() -> set[str]:


    raw = _get_env("VAULTAI_ALLOWED_REDIRECT_ORIGINS", required=False) or ""
    return {o.strip().rstrip("/") for o in raw.split(",") if o.strip()}


_ALLOWED_REDIRECT_PATH = "/storage"


def is_safe_redirect_url(url: Optional[str]) -> bool:


    if not url:
        return False
    try:
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.netloc:
        return False
                                             
    if parsed.username or parsed.password:
        return False
    if parsed.path != _ALLOWED_REDIRECT_PATH:
        return False

    host = (parsed.hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        return True

    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    return origin in _allowed_redirect_origins()


def resolve_redirect_url(
    *,
    provided: Optional[str],
    fallback: str,
    purpose: str,
) -> str:


    if provided and is_safe_redirect_url(provided):
        print(
            f"[STRIPE] redirect_url.use_frontend purpose={purpose} "
            f"url={provided!r}",
            flush=True,
        )
        return provided
    if provided:
        print(
            f"[STRIPE] redirect_url.rejected purpose={purpose} "
            f"url={provided!r} reason=not_allowlisted_or_wrong_path",
            flush=True,
        )
    print(
        f"[STRIPE] redirect_url.use_fallback purpose={purpose} "
        f"url={fallback!r}",
        flush=True,
    )
    return fallback


_stripe_http_client_configured = False


def _ensure_stripe_http_client_with_timeout() -> None:


    global _stripe_http_client_configured
    if _stripe_http_client_configured:
        return
    try:
        from stripe._http_client import RequestsClient
        stripe.default_http_client = RequestsClient(timeout=10)
                                                                      
                                                              
        stripe.max_network_retries = 0
        _stripe_http_client_configured = True
    except Exception as exc:
                                                                    
                                                                   
        print(
            f"[STRIPE] WARNING could not install timeout-bounded "
            f"HTTP client: {type(exc).__name__}: {exc}",
            flush=True,
        )


def _stripe_initialized() -> bool:


    key = get_stripe_api_key()
    if not key:
        return False
                                                                 
    stripe.api_key = key
    _ensure_stripe_http_client_with_timeout()
    return True


class StripeUnconfiguredError(Exception):
    pass


class StripeCeilingExceededError(Exception):


    def __init__(self, *, requested_blocks: int, max_blocks: int):
        super().__init__("enterprise_required")
        self.requested_blocks = requested_blocks
        self.max_blocks = max_blocks


class StripeSubscriptionAlreadyAtQuantityError(Exception):


    def __init__(self, *, current_blocks: int, requested_blocks: int):
        super().__init__("no_change")
        self.current_blocks = current_blocks
        self.requested_blocks = requested_blocks


class StripeSubscriptionDowngradeUnsupportedError(Exception):


    def __init__(self, *, current_blocks: int, requested_blocks: int):
        super().__init__("downgrade_not_supported")
        self.current_blocks = current_blocks
        self.requested_blocks = requested_blocks


class StripeCheckoutRejectedError(Exception):


    def __init__(
        self,
        *,
        stripe_type: str,
        stripe_code: Optional[str],
        stripe_message: str,
        param: Optional[str] = None,
    ):
        super().__init__(stripe_message)
        self.stripe_type = stripe_type
        self.stripe_code = stripe_code
        self.stripe_message = stripe_message
        self.param = param


def _safe_stripe_error_fields(exc: BaseException) -> dict:


    body = {}
    err = getattr(exc, "user_message", None) or str(exc)
    body["stripe_message"] = err
    body["stripe_type"] = type(exc).__name__
    body["stripe_code"] = getattr(exc, "code", None)
    body["stripe_param"] = getattr(exc, "param", None)
    body["stripe_http_status"] = getattr(exc, "http_status", None)
    body["stripe_request_id"] = getattr(exc, "request_id", None)
    return body


def get_stripe_customer_id_for_account(account_id: str) -> Optional[str]:
    if not account_id:
        return None
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT stripe_customer_id FROM stripe_customers "
            "WHERE account_id = %s;",
            (account_id,),
        )
        row = cur.fetchone()
        return str(row[0]) if row else None
    finally:
        conn.close()


def upsert_stripe_customer(
    *, account_id: str, stripe_customer_id: str, livemode: bool,
) -> None:


    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO stripe_customers (
                account_id, stripe_customer_id, livemode
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (account_id) DO UPDATE
              SET stripe_customer_id = EXCLUDED.stripe_customer_id,
                  livemode           = EXCLUDED.livemode,
                  updated_at         = NOW();
            """,
            (account_id, stripe_customer_id, livemode),
        )
        conn.commit()
    finally:
        conn.close()


@dataclass(frozen=True)
class CheckoutSession:
    checkout_url: str
    session_id: str


_ACTIVE_SUBSCRIPTION_STATUSES = ("active", "in_grace", "canceled_pending")


@dataclass(frozen=True)
class ActiveStorageSubscription:


    account_id: str
    stripe_subscription_id: str
    stripe_subscription_item_id: Optional[str]
    block_count: int
    status: str


def get_active_storage_subscription(
    account_id: str,
) -> Optional[ActiveStorageSubscription]:


    if not account_id:
        return None
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT account_id,
                   source_subscription_id,
                   stripe_subscription_item_id,
                   block_count,
                   status,
                   source
              FROM account_subscriptions
             WHERE account_id = %s;
            """,
            (account_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    if (row.get("source") or "").lower() != "stripe":
        return None
    if (row.get("status") or "") not in _ACTIVE_SUBSCRIPTION_STATUSES:
        return None
    sub_id = row.get("source_subscription_id")
    if not sub_id:
        return None
    return ActiveStorageSubscription(
        account_id=str(row["account_id"]),
        stripe_subscription_id=str(sub_id),
        stripe_subscription_item_id=(
            str(row["stripe_subscription_item_id"])
            if row.get("stripe_subscription_item_id") else None
        ),
        block_count=int(row.get("block_count") or 0),
        status=str(row.get("status") or ""),
    )


@dataclass(frozen=True)
class SubscriptionQuantityUpdate:


    stripe_subscription_id: str
    stripe_subscription_item_id: str
    previous_block_count: int
    new_block_count: int


def backfill_subscription_item_id_from_stripe(
    active: ActiveStorageSubscription,
) -> ActiveStorageSubscription:


    if active.stripe_subscription_item_id:
        return active
    if not active.stripe_subscription_id:
        return active
    if not _stripe_initialized():
        raise StripeUnconfiguredError("STRIPE_API_KEY not configured")

    print(
        "[STRIPE] backfill START "
        f"account_id={active.account_id!r} "
        f"sub_id={active.stripe_subscription_id!r}",
        flush=True,
    )

                                                                       
    print(
        "[STRIPE] backfill step=retrieve.before "
        f"account_id={active.account_id!r} "
        f"sub_id={active.stripe_subscription_id!r}",
        flush=True,
    )
    try:
        sub = stripe.Subscription.retrieve(active.stripe_subscription_id)
    except stripe.StripeError as exc:
        fields = _safe_stripe_error_fields(exc)
        print(
            "[STRIPE] backfill step=retrieve.FAILED (stripe error)",
            {
                "account_id": active.account_id,
                "sub_id":     active.stripe_subscription_id,
                **fields,
            },
            flush=True,
        )
        return active
    except Exception as exc:
                                                                        
                                                                     
        print(
            "[STRIPE] backfill step=retrieve.FAILED (other) "
            f"account_id={active.account_id!r} "
            f"sub_id={active.stripe_subscription_id!r} "
            f"error_type={type(exc).__name__} "
            f"error={exc!s}",
            flush=True,
        )
        return active
    print(
        "[STRIPE] backfill step=retrieve.ok "
        f"account_id={active.account_id!r} "
        f"sub_id={active.stripe_subscription_id!r} "
        f"sub_object_id={getattr(sub, 'id', None)!r} "
        f"status={getattr(sub, 'status', None)!r}",
        flush=True,
    )

                                                                       
    try:
        item_id = _extract_subscription_item_id(sub)
    except Exception as exc:
        print(
            "[STRIPE] backfill step=extract.FAILED "
            f"account_id={active.account_id!r} "
            f"sub_id={active.stripe_subscription_id!r} "
            f"error_type={type(exc).__name__} "
            f"error={exc!s}",
            flush=True,
        )
        return active
    if not item_id:
        print(
            "[STRIPE] backfill step=extract.FAILED — no items.data[0].id "
            f"account_id={active.account_id!r} "
            f"sub_id={active.stripe_subscription_id!r}",
            flush=True,
        )
        return active
    print(
        "[STRIPE] backfill step=extract.ok "
        f"account_id={active.account_id!r} "
        f"item_id={item_id!r}",
        flush=True,
    )

                                                                       
    print(
        "[STRIPE] backfill step=db.update.before "
        f"account_id={active.account_id!r} "
        f"sub_id={active.stripe_subscription_id!r} "
        f"item_id={item_id!r}",
        flush=True,
    )
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE account_subscriptions
               SET stripe_subscription_item_id = %s,
                   updated_at                  = NOW()
             WHERE account_id                  = %s
               AND source_subscription_id      = %s
               AND stripe_subscription_item_id IS NULL;
            """,
            (item_id, active.account_id, active.stripe_subscription_id),
        )
        rowcount = cur.rowcount
        conn.commit()
        print(
            "[STRIPE] backfill step=db.update.committed "
            f"account_id={active.account_id!r} "
            f"rowcount={rowcount}",
            flush=True,
        )
    except Exception as exc:
                                                                  
                                                                     
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        print(
            "[STRIPE] backfill step=db.update.FAILED "
            f"account_id={active.account_id!r} "
            f"sub_id={active.stripe_subscription_id!r} "
            f"item_id={item_id!r} "
            f"error_type={type(exc).__name__} "
            f"error={exc!s}",
            flush=True,
        )
        return active
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

                                                                        
    print(
        "[STRIPE] backfill step=return.refreshed "
        f"account_id={active.account_id!r} "
        f"sub_id={active.stripe_subscription_id!r} "
        f"item_id={item_id!r} "
        f"block_count={active.block_count} "
        f"status={active.status!r}",
        flush=True,
    )
    return ActiveStorageSubscription(
        account_id=active.account_id,
        stripe_subscription_id=active.stripe_subscription_id,
        stripe_subscription_item_id=item_id,
        block_count=active.block_count,
        status=active.status,
    )


def modify_existing_subscription_quantity(
    *,
    active: ActiveStorageSubscription,
    new_block_count: int,
) -> SubscriptionQuantityUpdate:


    if new_block_count < 1:
        raise ValueError("new_block_count must be >= 1")
    if not is_within_self_service_ceiling(new_block_count):
        from billing import self_service_max_blocks
        raise StripeCeilingExceededError(
            requested_blocks=new_block_count,
            max_blocks=self_service_max_blocks(),
        )
    if new_block_count == active.block_count:
        raise StripeSubscriptionAlreadyAtQuantityError(
            current_blocks=active.block_count,
            requested_blocks=new_block_count,
        )
    if new_block_count < active.block_count:
        raise StripeSubscriptionDowngradeUnsupportedError(
            current_blocks=active.block_count,
            requested_blocks=new_block_count,
        )
    if not active.stripe_subscription_item_id:
                                                                      
                                                                     
        raise StripeCheckoutRejectedError(
            stripe_type="MissingSubscriptionItemId",
            stripe_code="missing_subscription_item_id",
            stripe_message=(
                "This account has a Stripe subscription on record but "
                "the subscription_item_id was not captured. Open a new "
                "Checkout to re-establish the link."
            ),
        )

    if not _stripe_initialized():
        raise StripeUnconfiguredError("STRIPE_API_KEY not configured")

    print(
        "[STRIPE] subscription_item.modify request "
        f"account_id={active.account_id!r} "
        f"sub_id={active.stripe_subscription_id!r} "
        f"item_id={active.stripe_subscription_item_id!r} "
        f"from_blocks={active.block_count} "
        f"to_blocks={new_block_count}",
        flush=True,
    )

    try:
        item = stripe.SubscriptionItem.modify(
            active.stripe_subscription_item_id,
            quantity=new_block_count,
                                                                       
                                                                    
            proration_behavior="always_invoice",
        )
    except stripe.StripeError as exc:
        fields = _safe_stripe_error_fields(exc)
        print(
            "[STRIPE] subscription_item.modify FAILED",
            {
                "account_id": active.account_id,
                "sub_id":     active.stripe_subscription_id,
                "item_id":    active.stripe_subscription_item_id,
                "from_blocks": active.block_count,
                "to_blocks":   new_block_count,
                **fields,
            },
            flush=True,
        )
        raise StripeCheckoutRejectedError(
            stripe_type=fields["stripe_type"],
            stripe_code=fields["stripe_code"],
            stripe_message=fields["stripe_message"],
            param=fields["stripe_param"],
        )

    new_qty = int(getattr(item, "quantity", new_block_count) or new_block_count)
    print(
        "[STRIPE] subscription_item.modify ok "
        f"account_id={active.account_id!r} "
        f"sub_id={active.stripe_subscription_id!r} "
        f"item_id={active.stripe_subscription_item_id!r} "
        f"from_blocks={active.block_count} "
        f"to_blocks={new_qty} "
        f"proration_behavior='always_invoice'",
        flush=True,
    )
    return SubscriptionQuantityUpdate(
        stripe_subscription_id=active.stripe_subscription_id,
        stripe_subscription_item_id=active.stripe_subscription_item_id,
        previous_block_count=active.block_count,
        new_block_count=new_qty,
    )


def cancel_duplicate_storage_subscriptions(
    *, account_id: str, customer_id: str, keep_subscription_id: str,
) -> dict:


    if not _stripe_initialized():
        raise StripeUnconfiguredError("STRIPE_API_KEY not configured")

    canceled_ids: list[str] = []
    failed: list[dict] = []

                                                                      
    subs = stripe.Subscription.list(customer=customer_id, status="all", limit=100)
    for sub in subs.auto_paging_iter():
        sub_id = str(getattr(sub, "id", "") or "")
        status = str(getattr(sub, "status", "") or "").lower()
        if sub_id == keep_subscription_id:
            continue
                                                                        
                                                                      
        if status not in ("active", "trialing", "past_due", "unpaid", "incomplete"):
            continue
        try:
            canceled = stripe.Subscription.cancel(
                sub_id,
                invoice_now=False,
                prorate=True,
            )
            canceled_ids.append(str(getattr(canceled, "id", sub_id)))
        except stripe.StripeError as exc:
            failed.append({
                "subscription_id": sub_id,
                **_safe_stripe_error_fields(exc),
            })

    print(
        "[STRIPE] cleanup_duplicate_subs "
        f"account_id={account_id!r} "
        f"customer_id={customer_id!r} "
        f"keep={keep_subscription_id!r} "
        f"canceled={canceled_ids} "
        f"failed_count={len(failed)}",
        flush=True,
    )
    return {
        "account_id":          account_id,
        "customer_id":         customer_id,
        "kept_subscription_id": keep_subscription_id,
        "canceled_subscription_ids": canceled_ids,
        "canceled_count":       len(canceled_ids),
        "failed":               failed,
    }


def create_checkout_session(
    *,
    account_id: str,
    vault_id: str,
    block_count: int,
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
) -> CheckoutSession:


    if block_count < 1:
        raise ValueError("block_count must be >= 1")
    if not is_within_self_service_ceiling(block_count):
        from billing import self_service_max_blocks
        raise StripeCeilingExceededError(
            requested_blocks=block_count,
            max_blocks=self_service_max_blocks(),
        )

    if not _stripe_initialized():
        raise StripeUnconfiguredError("STRIPE_API_KEY not configured")

    price_id = get_stripe_block_price_id()
    if not price_id:
        raise StripeUnconfiguredError(
            "STRIPE_STORAGE_BLOCK_PRICE_ID not configured",
        )

                                                                   
    existing_customer_id = get_stripe_customer_id_for_account(account_id)

    resolved_success_url = resolve_redirect_url(
        provided=success_url,
        fallback=get_checkout_success_url(),
        purpose="checkout_success",
    )
    resolved_cancel_url = resolve_redirect_url(
        provided=cancel_url,
        fallback=get_checkout_cancel_url(),
        purpose="checkout_cancel",
    )

    session_kwargs: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": block_count}],
        "success_url": resolved_success_url,
        "cancel_url":  resolved_cancel_url,
        "client_reference_id": account_id,
        "metadata": {
            "account_id": account_id,
            "vault_id": vault_id,
            "block_count": str(block_count),
        },
        "subscription_data": {
            "metadata": {
                "account_id": account_id,
                "block_count": str(block_count),
            },
        },
    }
    if existing_customer_id:
        session_kwargs["customer"] = existing_customer_id
                                                                    
                                                                       
    print(
        "[STRIPE] checkout_session.create request",
        {
            "account_id": account_id,
            "vault_id_tail": vault_id[-6:] if vault_id else None,
            "block_count": block_count,
            "quantity": block_count,
            "price_id": price_id,
            "mode": "subscription",
            "success_url": resolved_success_url,
            "cancel_url": resolved_cancel_url,
            "has_existing_customer": existing_customer_id is not None,
        },
        flush=True,
    )

    try:
        session = stripe.checkout.Session.create(**session_kwargs)
    except stripe.StripeError as exc:
                                                                       
                                                                     
        fields = _safe_stripe_error_fields(exc)
        print(
            "[STRIPE] checkout_session.create FAILED",
            {
                "account_id": account_id,
                "block_count": block_count,
                "price_id": price_id,
                **fields,
            },
            flush=True,
        )
        raise StripeCheckoutRejectedError(
            stripe_type=fields["stripe_type"],
            stripe_code=fields["stripe_code"],
            stripe_message=fields["stripe_message"],
            param=fields["stripe_param"],
        )

    print(
        "[STRIPE] checkout_session.create ok",
        {
            "account_id": account_id,
            "session_id": str(session.id),
            "url_set": bool(session.url),
        },
        flush=True,
    )
    return CheckoutSession(
        checkout_url=str(session.url),
        session_id=str(session.id),
    )


@dataclass(frozen=True)
class PortalSession:
    portal_url: str


def create_portal_session(
    *,
    account_id: str,
    return_url: Optional[str] = None,
) -> PortalSession:
    if not _stripe_initialized():
        raise StripeUnconfiguredError("STRIPE_API_KEY not configured")

    customer_id = get_stripe_customer_id_for_account(account_id)
    if not customer_id:
                                                      
        raise LookupError("no_stripe_customer_for_account")

    resolved_return_url = resolve_redirect_url(
        provided=return_url,
        fallback=get_portal_return_url(),
        purpose="portal_return",
    )
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=resolved_return_url,
    )
    return PortalSession(portal_url=str(session.url))


class StripeSignatureError(Exception):


    def __init__(self, reason: str, underlying: BaseException):
        super().__init__(reason)
        self.reason = reason
        self.underlying = underlying


class StripeEventDecodeError(Exception):


    def __init__(self, reason: str, underlying: BaseException):
        super().__init__(reason)
        self.reason = reason
        self.underlying = underlying


def _stripe_event_to_plain_dict(event: Any, *, raw_payload: bytes) -> dict:


    return json.loads(raw_payload.decode("utf-8"))


def verify_webhook_signature(
    *, payload: bytes, signature_header: str,
) -> dict:


    secret = get_stripe_webhook_secret()
    if not secret:
        raise StripeUnconfiguredError("STRIPE_WEBHOOK_SECRET not configured")

                                                                     
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=signature_header,
            secret=secret,
        )
    except stripe.error.SignatureVerificationError as exc:
                                                                      
                                                                   
        reason = getattr(exc, "user_message", None) or "signature_mismatch"
        raise StripeSignatureError(reason=reason, underlying=exc)

                                                                  
    try:
        return _stripe_event_to_plain_dict(event, raw_payload=payload)
    except Exception as exc:
                                        
                                                     
        raise StripeEventDecodeError(
            reason=f"{type(exc).__name__}: {exc}",
            underlying=exc,
        )


@dataclass
class WebhookDispatchResult:
    outcome: str                                                                                
    event_id: str
    event_type: str
    account_id: Optional[str] = None
    error_text: Optional[str] = None


class _NoAccountSubscriptionRowError(RuntimeError):
    pass


def dispatch_webhook_event(event: dict) -> WebhookDispatchResult:


    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "")
    livemode = bool(event.get("livemode", False))
    environment = "production" if livemode else "sandbox"

    print(
        "[STRIPE] webhook dispatch "
        f"event_id={event_id!r} "
        f"type={event_type!r} "
        f"environment={environment!r}",
        flush=True,
    )

    if not event_id or not event_type:
        return WebhookDispatchResult(
            outcome="error",
            event_id=event_id,
            event_type=event_type,
            error_text="missing_event_id_or_type",
        )

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
                                                                
                                                                 
        try:
            cur.execute(
                """
                INSERT INTO provider_event_log (
                    source, source_event_id, signature_verified,
                    environment, raw_payload_jsonb
                ) VALUES (
                    'stripe', %s, TRUE, %s, %s
                );
                """,
                (event_id, environment, Json(event)),
            )
            conn.commit()
        except pg_errors.UniqueViolation:
            conn.rollback()
            logger.info(
                "stripe webhook duplicate event id=%s type=%s — no-op",
                event_id, event_type,
            )
            return WebhookDispatchResult(
                outcome="ignored_duplicate",
                event_id=event_id,
                event_type=event_type,
            )

                   
        handler = _HANDLERS.get(event_type)
        if handler is None:
                                                                        
            cur.execute(
                """
                UPDATE provider_event_log
                   SET processed_at = NOW(),
                       outcome      = 'ignored_unhandled'
                 WHERE source = 'stripe' AND source_event_id = %s;
                """,
                (event_id,),
            )
            conn.commit()
            return WebhookDispatchResult(
                outcome="ignored_unhandled",
                event_id=event_id,
                event_type=event_type,
            )

        try:
            account_id = handler(event, cur)
            cur.execute(
                """
                UPDATE provider_event_log
                   SET processed_at = NOW(),
                       outcome      = 'applied'
                 WHERE source = 'stripe' AND source_event_id = %s;
                """,
                (event_id,),
            )
            conn.commit()
            return WebhookDispatchResult(
                outcome="applied",
                event_id=event_id,
                event_type=event_type,
                account_id=account_id,
            )
        except Exception as exc:
            conn.rollback()
            cur.execute(
                """
                UPDATE provider_event_log
                   SET processed_at = NOW(),
                       outcome      = 'error',
                       error_text   = %s
                 WHERE source = 'stripe' AND source_event_id = %s;
                """,
                (f"{type(exc).__name__}: {exc}", event_id),
            )
            conn.commit()
            logger.exception(
                "stripe webhook handler failed id=%s type=%s",
                event_id, event_type,
            )
            return WebhookDispatchResult(
                outcome="error",
                event_id=event_id,
                event_type=event_type,
                error_text=f"{type(exc).__name__}: {exc}",
            )
    finally:
        conn.close()


def _resolve_account_id_from_subscription(sub: dict, cur) -> Optional[str]:


    md = sub.get("metadata") or {}
    if isinstance(md, dict) and md.get("account_id"):
        return str(md["account_id"])
    customer_id = sub.get("customer")
    if not customer_id:
        return None
    cur.execute(
        "SELECT account_id FROM stripe_customers "
        "WHERE stripe_customer_id = %s;",
        (str(customer_id),),
    )
    row = cur.fetchone()
    if not row:
        return None
    return str(row["account_id"])


def _safe_get(obj, key):


    if obj is None:
        return None
    try:
        return obj[key]
    except (KeyError, TypeError, IndexError):
        return None


def _is_mapping_like(value) -> bool:


    if isinstance(value, dict):
        return True
    return hasattr(value, "__getitem__") and not isinstance(
        value, (str, bytes, list, tuple)
    )


def _extract_block_count(sub) -> int:


    items = _safe_get(sub, "items")
    if not _is_mapping_like(items):
        return 0
    data = _safe_get(items, "data")
    if not isinstance(data, list) or not data:
        return 0
    first = data[0]
    if not _is_mapping_like(first):
        return 0
    qty = _safe_get(first, "quantity")
    try:
        return max(0, int(qty)) if qty is not None else 0
    except (TypeError, ValueError):
        return 0


def _extract_subscription_item_id(sub) -> Optional[str]:


    items = _safe_get(sub, "items")
    if not _is_mapping_like(items):
        return None
    data = _safe_get(items, "data")
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    if not _is_mapping_like(first):
        return None
    item_id = _safe_get(first, "id")
    if not item_id or not isinstance(item_id, str):
        return None
    return item_id


def _iso_or_none(ts: Optional[int]) -> Optional[datetime]:


    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _apply_subscription_state(
    sub: dict, cur, *, default_status: str,
) -> Optional[str]:


    account_id = _resolve_account_id_from_subscription(sub, cur)
    sub_id = str(sub.get("id") or "")
    sub_item_id = _extract_subscription_item_id(sub)
    stripe_status = str(sub.get("status") or "").lower()
    block_count = _extract_block_count(sub)
    purchased = blocks_to_bytes(block_count)
    status = _STRIPE_STATUS_MAP.get(stripe_status, default_status)
    period_start = _iso_or_none(sub.get("current_period_start"))
    period_end = _iso_or_none(sub.get("current_period_end"))
    cancel_at_period_end = bool(sub.get("cancel_at_period_end"))

    print(
        "[STRIPE] subscription apply attempt "
        f"event_kind={default_status!r} "
        f"sub_id={sub_id!r} "
        f"stripe_status={stripe_status!r} "
        f"resolved_account_id={account_id!r} "
        f"block_count={block_count} "
        f"status={status!r}",
        flush=True,
    )

    if not account_id:
                                                                      
                                                                  
        raise RuntimeError("could_not_resolve_account_id")

                                                                   
    cur.execute(
        """
        SELECT block_count, purchased_bytes
          FROM account_subscriptions
         WHERE account_id = %s
         FOR UPDATE;
        """,
        (account_id,),
    )
    prior = cur.fetchone()
    from_blocks = int(prior["block_count"]) if prior else 0
    from_purchased = int(prior["purchased_bytes"]) if prior else 0

    cur.execute(
        """
        UPDATE account_subscriptions
           SET status                      = %s,
               source                      = 'stripe',
               source_subscription_id      = %s,
               stripe_subscription_item_id = %s,
               billing_period              = 'monthly',
               block_count                 = %s,
               purchased_bytes             = %s,
               current_period_start        = %s,
               current_period_end          = %s,
               cancel_at_period_end        = %s,
               updated_at                  = NOW()
         WHERE account_id = %s;
        """,
        (
            status,
            sub_id,
            sub_item_id,
            block_count,
            purchased,
            period_start,
            period_end,
            cancel_at_period_end,
            account_id,
        ),
    )

                                                                     
    if cur.rowcount == 0:
        logger.warning(
            "stripe webhook: self-heal INSERT account_subscriptions "
            "row missing for account=%s sub_id_prefix=%s",
            (account_id or "")[:8], (sub_id or "")[:14],
        )
        cur.execute(
            """
            INSERT INTO account_subscriptions (
                account_id, status, source, source_subscription_id,
                stripe_subscription_item_id, billing_period,
                block_count, purchased_bytes, storage_bytes_grant,
                current_period_start, current_period_end,
                cancel_at_period_end, updated_at
            )
            VALUES (
                %s, %s, 'stripe', %s, %s, 'monthly',
                %s, %s, 0,
                %s, %s, %s, NOW()
            )
            ON CONFLICT (account_id) DO UPDATE
              SET status                      = EXCLUDED.status,
                  source                      = EXCLUDED.source,
                  source_subscription_id      = EXCLUDED.source_subscription_id,
                  stripe_subscription_item_id = EXCLUDED.stripe_subscription_item_id,
                  billing_period              = EXCLUDED.billing_period,
                  block_count                 = EXCLUDED.block_count,
                  purchased_bytes             = EXCLUDED.purchased_bytes,
                  current_period_start        = EXCLUDED.current_period_start,
                  current_period_end          = EXCLUDED.current_period_end,
                  cancel_at_period_end        = EXCLUDED.cancel_at_period_end,
                  updated_at                  = NOW();
            """,
            (
                account_id,
                status,
                sub_id,
                sub_item_id,
                block_count,
                purchased,
                period_start,
                period_end,
                cancel_at_period_end,
            ),
        )

    cur.execute(
        """
        INSERT INTO subscription_events (
            account_id, event_type, source, source_event_id,
            sales_channel, from_block_count, to_block_count,
            from_purchased_bytes, to_purchased_bytes,
            occurred_at, payload_jsonb
        )
        VALUES (
            %s, %s, 'stripe', %s, 'self_service',
            %s, %s, %s, %s,
            NOW(), %s
        );
        """,
        (
            account_id,
            'created' if default_status == 'active' else 'renewed',
            str(sub.get("id") or ""),
            from_blocks,
            block_count,
            from_purchased,
            purchased,
            Json({
                "stripe_status": stripe_status,
                "status": status,
                "cancel_at_period_end": cancel_at_period_end,
                "block_count": block_count,
            }),
        ),
    )

    print(
        "[STRIPE] subscription applied "
        f"event_kind={default_status!r} "
        f"account_id={account_id!r} "
        f"sub_id={sub_id!r} "
        f"from_blocks={from_blocks} to_blocks={block_count} "
        f"from_purchased_bytes={from_purchased} "
        f"to_purchased_bytes={purchased} "
        f"status={status!r}",
        flush=True,
    )

    return account_id


def _handle_subscription_created(event: dict, cur) -> Optional[str]:
    sub = (event.get("data") or {}).get("object") or {}
    return _apply_subscription_state(sub, cur, default_status="active")


def _handle_subscription_updated(event: dict, cur) -> Optional[str]:
    sub = (event.get("data") or {}).get("object") or {}
    return _apply_subscription_state(sub, cur, default_status="active")


def _handle_subscription_deleted(event: dict, cur) -> Optional[str]:


    sub = (event.get("data") or {}).get("object") or {}
    account_id = _resolve_account_id_from_subscription(sub, cur)
    if not account_id:
        raise RuntimeError("could_not_resolve_account_id")

    cur.execute(
        """
        SELECT block_count, purchased_bytes
          FROM account_subscriptions
         WHERE account_id = %s
         FOR UPDATE;
        """,
        (account_id,),
    )
    prior = cur.fetchone()
    from_blocks = int(prior["block_count"]) if prior else 0
    from_purchased = int(prior["purchased_bytes"]) if prior else 0

                                                                  
    cur.execute(
        """
        WITH
        included AS (
            SELECT COALESCE((SELECT value FROM storage_pricing
                              WHERE key='included_bytes'), 1073741824) AS v
        ),
        used AS (
            SELECT COALESCE(encrypted_bytes, 0) AS v
              FROM account_storage_totals
             WHERE account_id = %s
        )
        UPDATE account_subscriptions s
           SET status                 = CASE
                   WHEN COALESCE((SELECT v FROM used), 0)
                        > (SELECT v FROM included)
                        + COALESCE(s.storage_bytes_grant, 0)
                   THEN 'over_quota_grace'
                   ELSE 'expired'
               END,
               block_count            = 0,
               purchased_bytes        = 0,
               cancel_at_period_end   = FALSE,
               over_quota_grace_ends_at = CASE
                   WHEN COALESCE((SELECT v FROM used), 0)
                        > (SELECT v FROM included)
                        + COALESCE(s.storage_bytes_grant, 0)
                   THEN NOW() + INTERVAL '30 days'
                   ELSE NULL
               END,
               updated_at             = NOW()
         WHERE s.account_id = %s;
        """,
        (account_id, account_id),
    )

    cur.execute(
        """
        INSERT INTO subscription_events (
            account_id, event_type, source, source_event_id,
            sales_channel, from_block_count, to_block_count,
            from_purchased_bytes, to_purchased_bytes,
            occurred_at, payload_jsonb
        )
        VALUES (%s, 'canceled_by_provider', 'stripe', %s,
                'self_service', %s, 0, %s, 0,
                NOW(), %s);
        """,
        (
            account_id,
            str(sub.get("id") or ""),
            from_blocks,
            from_purchased,
            Json({"stripe_status": sub.get("status"), "reason": "subscription_deleted"}),
        ),
    )

    # 2026-07-30 billing notifications. Best-effort — the webhook
    # write above is authoritative and must not be blocked by a
    # notification failure. Detect the over-quota branch by
    # re-reading the row we just updated so the banner copy matches
    # the real state.
    try:
        cur.execute(
            "SELECT status, over_quota_grace_ends_at "
            "  FROM account_subscriptions "
            " WHERE account_id = %s LIMIT 1;",
            (account_id,),
        )
        _post_row = cur.fetchone()
        _post_status = str((_post_row or {}).get("status") or "")
        _over_quota = _post_status == "over_quota_grace"
        _oq_iso = None
        if _over_quota and _post_row.get("over_quota_grace_ends_at"):
            try:
                _oq_iso = _post_row["over_quota_grace_ends_at"].isoformat()
            except Exception:
                _oq_iso = None
    except Exception:
        _over_quota = False
        _oq_iso = None
    try:
        from vault_billing_notifications import (
            notify_subscription_cancelled,
        )
        notify_subscription_cancelled(
            account_id,
            over_quota=_over_quota,
            over_quota_grace_ends_at_iso=_oq_iso,
            subscription_id=str(sub.get("id") or "") or None,
        )
    except Exception:
        logger.exception(
            "[BILLING-NOTIFY] subscription_cancelled dispatch failed "
            "account=%s", (account_id or "")[:8],
        )
    return account_id


def _handle_invoice_payment_failed(event: dict, cur) -> Optional[str]:


    invoice = (event.get("data") or {}).get("object") or {}
    customer_id = invoice.get("customer")
    if not customer_id:
        return None
    cur.execute(
        "SELECT account_id FROM stripe_customers "
        "WHERE stripe_customer_id = %s;",
        (str(customer_id),),
    )
    row = cur.fetchone()
    if not row:
        return None
    account_id = str(row["account_id"])

    cur.execute(
        """
        UPDATE account_subscriptions
           SET status               = 'in_grace',
               grace_period_ends_at = COALESCE(current_period_end,
                                               NOW() + INTERVAL '3 days'),
               updated_at           = NOW()
         WHERE account_id = %s
           AND status IN ('active', 'in_grace');
        """,
        (account_id,),
    )
    cur.execute(
        """
        INSERT INTO subscription_events (
            account_id, event_type, source, source_event_id,
            sales_channel, occurred_at, payload_jsonb
        )
        VALUES (%s, 'grace_started', 'stripe', %s,
                'self_service', NOW(), %s);
        """,
        (
            account_id,
            str(invoice.get("id") or ""),
            Json({"reason": "invoice_payment_failed",
                  "amount_due": invoice.get("amount_due")}),
        ),
    )

    # 2026-07-30 billing notifications. Best-effort — never blocks
    # the webhook write. Users receive an in-app banner per vault and
    # (once the email pipeline lands) an email describing what
    # happened and reassuring them their data stays intact during
    # Stripe's dunning retries.
    try:
        cur.execute(
            "SELECT grace_period_ends_at FROM account_subscriptions "
            "WHERE account_id = %s LIMIT 1;",
            (account_id,),
        )
        _grace_row = cur.fetchone()
        _grace_iso = None
        if _grace_row and _grace_row.get("grace_period_ends_at"):
            try:
                _grace_iso = _grace_row["grace_period_ends_at"].isoformat()
            except Exception:
                _grace_iso = None
    except Exception:
        _grace_iso = None
    try:
        from vault_billing_notifications import notify_payment_failed
        notify_payment_failed(
            account_id,
            invoice_id=str(invoice.get("id") or "") or None,
            amount_due_cents=invoice.get("amount_due"),
            grace_period_ends_at_iso=_grace_iso,
        )
    except Exception:
        logger.exception(
            "[BILLING-NOTIFY] payment_failed dispatch failed "
            "account=%s", (account_id or "")[:8],
        )
    return account_id


def _extract_block_quantity_from_invoice(invoice: dict) -> Optional[int]:
    """2026-07-30 recovery-bug fix — pull the storage-block quantity
    from a paid invoice so ``_handle_invoice_payment_succeeded`` can
    restore ``block_count`` / ``purchased_bytes`` when transitioning a
    user out of ``expired`` / ``over_quota_grace``.

    Scans ``invoice.lines.data[]`` for a line whose ``price.id``
    matches the configured storage-block price. Returns the
    non-negative integer quantity, or ``None`` when the invoice has
    no matching line (which means the invoice was for something else
    — e.g. a one-time charge or a metered add-on — and we must NOT
    infer a subscription quantity from it).

    Idempotent + defensive: any unexpected shape returns ``None``
    rather than raising. Never touches Stripe over the network.
    """
    try:
        block_price = (get_stripe_block_price_id() or "").strip()
    except Exception:
        block_price = ""
    if not block_price:
        return None
    lines = ((invoice.get("lines") or {}).get("data")) or []
    if not isinstance(lines, list):
        return None
    for line in lines:
        if not isinstance(line, dict):
            continue
        price = line.get("price") or {}
        price_id = ""
        if isinstance(price, dict):
            price_id = str(price.get("id") or "")
        else:
            price_id = str(getattr(price, "id", "") or "")
        if not price_id or price_id != block_price:
            continue
        raw_qty = line.get("quantity")
        try:
            qty = int(raw_qty)
        except (TypeError, ValueError):
            continue
        if qty < 0:
            continue
        return qty
    return None


def _handle_invoice_payment_succeeded(event: dict, cur) -> Optional[str]:


    invoice = (event.get("data") or {}).get("object") or {}
    customer_id = invoice.get("customer")
    if not customer_id:
        return None
    cur.execute(
        "SELECT account_id FROM stripe_customers "
        "WHERE stripe_customer_id = %s;",
        (str(customer_id),),
    )
    row = cur.fetchone()
    if not row:
        return None
    account_id = str(row["account_id"])

    period_start = _iso_or_none(invoice.get("period_start"))
    period_end = _iso_or_none(invoice.get("period_end"))

    # 2026-07-30 recovery-bug fix.
    # Read the pre-update status + block_count so we can detect
    # transitions that require restoring purchased_bytes. The audit
    # found that the prior handler only flipped `in_grace -> active`
    # — a user whose subscription had already reached `expired` or
    # `over_quota_grace` stayed on the free tier after paying again,
    # requiring manual support intervention. That is now fixed:
    # when the invoice carries a storage-block line item, we
    # restore block_count + purchased_bytes from its quantity
    # regardless of the prior status.
    cur.execute(
        """
        SELECT status, block_count, purchased_bytes
          FROM account_subscriptions
         WHERE account_id = %s
         FOR UPDATE;
        """,
        (account_id,),
    )
    prior = cur.fetchone()
    prior_status = str((prior or {}).get("status") or "")
    prior_blocks = int((prior or {}).get("block_count") or 0)

    invoice_blocks = _extract_block_quantity_from_invoice(invoice)
    try:
        block_bytes_val = int(block_bytes())
    except Exception:
        block_bytes_val = 53_687_091_200
    restore_needed = (
        prior_status in ("expired", "over_quota_grace",
                         "over_quota_locked", "past_due", "paused",
                         "refunded")
        and invoice_blocks is not None
        and invoice_blocks > 0
    )

    if restore_needed:
        # Full restore: status back to active, block_count +
        # purchased_bytes rebuilt from the invoice, over-quota grace
        # window cleared, grace_period_ends_at cleared.
        cur.execute(
            """
            UPDATE account_subscriptions
               SET status                   = 'active',
                   block_count              = %s,
                   purchased_bytes          = %s,
                   cancel_at_period_end     = FALSE,
                   grace_period_ends_at     = NULL,
                   over_quota_grace_ends_at = NULL,
                   current_period_start     = COALESCE(%s, current_period_start),
                   current_period_end       = COALESCE(%s, current_period_end),
                   updated_at               = NOW()
             WHERE account_id = %s;
            """,
            (
                int(invoice_blocks),
                int(invoice_blocks) * block_bytes_val,
                period_start, period_end, account_id,
            ),
        )
    else:
        # Simple recovery (was `in_grace` or `active`): flip to
        # `active` and clear the grace timer. Unchanged from the
        # pre-fix behavior for these cases so existing paying
        # customers see no observable difference.
        cur.execute(
            """
            UPDATE account_subscriptions
               SET status               = CASE
                       WHEN status = 'in_grace' THEN 'active'
                       ELSE status
                   END,
                   grace_period_ends_at = NULL,
                   current_period_start = COALESCE(%s, current_period_start),
                   current_period_end   = COALESCE(%s, current_period_end),
                   updated_at           = NOW()
             WHERE account_id = %s;
            """,
            (period_start, period_end, account_id),
        )

    cur.execute(
        """
        INSERT INTO subscription_events (
            account_id, event_type, source, source_event_id,
            sales_channel, from_block_count, to_block_count,
            from_purchased_bytes, to_purchased_bytes,
            occurred_at, payload_jsonb
        )
        VALUES (%s, 'renewed', 'stripe', %s,
                'self_service', %s, %s, %s, %s,
                NOW(), %s);
        """,
        (
            account_id,
            str(invoice.get("id") or ""),
            prior_blocks,
            (int(invoice_blocks) if restore_needed else prior_blocks),
            prior_blocks * block_bytes_val,
            ((int(invoice_blocks) if restore_needed else prior_blocks)
             * block_bytes_val),
            Json({
                "reason": "invoice_payment_succeeded",
                "amount_paid": invoice.get("amount_paid"),
                "prior_status": prior_status,
                "restored": bool(restore_needed),
                "invoice_blocks": invoice_blocks,
            }),
        ),
    )

    # Notify the user out-of-band. Best-effort — never blocks the
    # webhook write. Fires whenever the handler flipped ANY status
    # transition; specifically it does NOT fire when the account was
    # already `active` (nothing changed).
    if prior_status and prior_status != "active":
        try:
            from vault_billing_notifications import notify_payment_recovered
            notify_payment_recovered(
                account_id,
                invoice_id=str(invoice.get("id") or "") or None,
                restored_block_count=(
                    int(invoice_blocks) if restore_needed else None
                ),
            )
        except Exception:
            logger.exception(
                "[BILLING-NOTIFY] payment_recovered dispatch failed "
                "account=%s", (account_id or "")[:8],
            )
    return account_id


def _handle_checkout_session_completed(event: dict, cur) -> Optional[str]:


    session = (event.get("data") or {}).get("object") or {}
    customer_id = session.get("customer")
    if not customer_id:
        return None
    metadata = session.get("metadata") or {}
    account_id = metadata.get("account_id") if isinstance(metadata, dict) else None
    if not account_id:
                                                                        
        account_id = session.get("client_reference_id")
    if not account_id:
        return None
                                                                    
                                                   
    cur.execute(
        "SELECT account_id FROM stripe_customers "
        "WHERE stripe_customer_id = %s;",
        (str(customer_id),),
    )
    prior_row = cur.fetchone()
    if prior_row:
                                                                      
                                                               
        try:
            prior_account_id = prior_row["account_id"]
        except (TypeError, KeyError):
            prior_account_id = prior_row[0]
        prior_account_id = str(prior_account_id)
        if prior_account_id != str(account_id):
                                                             
                                                                  
            logger.warning(
                "stripe webhook: cross-account guard tripped — "
                "stripe_customer=%s already maps to account=%s, "
                "checkout metadata wants account=%s; keeping prior",
                str(customer_id)[:14],
                prior_account_id[:8],
                str(account_id)[:8],
            )
            return prior_account_id
    cur.execute(
        """
        INSERT INTO stripe_customers (account_id, stripe_customer_id, livemode)
        VALUES (%s, %s, %s)
        ON CONFLICT (account_id) DO UPDATE
          SET stripe_customer_id = EXCLUDED.stripe_customer_id,
              livemode           = EXCLUDED.livemode,
              updated_at         = NOW();
        """,
        (str(account_id), str(customer_id), bool(event.get("livemode"))),
    )
    return str(account_id)


def _handle_charge_refunded(event: dict, cur) -> Optional[str]:

    charge = (event.get("data") or {}).get("object") or {}
    customer_id = charge.get("customer")
    if not customer_id:
        return None
    cur.execute(
        "SELECT account_id FROM stripe_customers "
        "WHERE stripe_customer_id = %s;",
        (str(customer_id),),
    )
    row = cur.fetchone()
    if not row:
        return None
    account_id = str(row["account_id"])

    cur.execute(
        """
        SELECT block_count, purchased_bytes
          FROM account_subscriptions
         WHERE account_id = %s
         FOR UPDATE;
        """,
        (account_id,),
    )
    prior = cur.fetchone()
    from_blocks = int(prior["block_count"]) if prior else 0
    from_purchased = int(prior["purchased_bytes"]) if prior else 0

    cur.execute(
        """
        UPDATE account_subscriptions
           SET status          = 'refunded',
               block_count     = 0,
               purchased_bytes = 0,
               updated_at      = NOW()
         WHERE account_id = %s;
        """,
        (account_id,),
    )
    cur.execute(
        """
        INSERT INTO subscription_events (
            account_id, event_type, source, source_event_id,
            sales_channel, from_block_count, to_block_count,
            from_purchased_bytes, to_purchased_bytes,
            occurred_at, payload_jsonb
        )
        VALUES (%s, 'refunded', 'stripe', %s,
                'self_service', %s, 0, %s, 0,
                NOW(), %s);
        """,
        (
            account_id,
            str(charge.get("id") or ""),
            from_blocks,
            from_purchased,
            Json({"amount_refunded": charge.get("amount_refunded")}),
        ),
    )
    return account_id


_STRIPE_STATUS_MAP: dict[str, str] = {
    "active":               "active",
    "trialing":             "active",                                      
    "past_due":             "in_grace",
    "unpaid":               "past_due",
    "canceled":             "expired",
    "incomplete":           "past_due",
    "incomplete_expired":   "expired",
    "paused":               "paused",
}


_HANDLERS = {
    "checkout.session.completed":       _handle_checkout_session_completed,
    "customer.subscription.created":    _handle_subscription_created,
    "customer.subscription.updated":    _handle_subscription_updated,
    "customer.subscription.deleted":    _handle_subscription_deleted,
    "invoice.payment_failed":           _handle_invoice_payment_failed,
    "invoice.payment_succeeded":        _handle_invoice_payment_succeeded,
    "charge.refunded":                  _handle_charge_refunded,
}


def probe_stripe_price_currency() -> dict:


    out: dict = {
        "ok": False,
        "price_id": None,
        "currency": None,
        "unit_amount_cents": None,
        "interval": None,
        "active": None,
        "matches_expected_usd_2500": False,
        "error": None,
    }
    try:
        if not _stripe_initialized():
            out["error"] = "stripe_unconfigured_api_key"
            return out
        price_id = get_stripe_block_price_id()
        out["price_id"] = price_id
        if not price_id:
            out["error"] = "stripe_unconfigured_price_id"
            return out
        price = stripe.Price.retrieve(price_id)
        currency = (getattr(price, "currency", None) or "").lower()
        amount = getattr(price, "unit_amount", None)
        recurring = getattr(price, "recurring", None) or {}
        interval = recurring.get("interval") if isinstance(recurring, dict) \
            else getattr(recurring, "interval", None)
        out["ok"] = True
        out["currency"] = currency
        out["unit_amount_cents"] = amount
        out["interval"] = interval
        out["active"] = bool(getattr(price, "active", False))
                                                                     
                                                                    
        out["matches_expected_usd_2500"] = (
            currency == "usd"
            and amount == block_price_cents_usd()
            and interval == "month"
        )
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def build_billing_admin_health_envelope(
    *, window_seconds: int = 60,
) -> dict[str, Any]:
    api_key_configured = bool(
        os.getenv("STRIPE_API_KEY", "").strip(),
    )
    webhook_secret_configured = bool(
        os.getenv("STRIPE_WEBHOOK_SECRET", "").strip(),
    )
    block_price_configured = bool(
        os.getenv("STRIPE_STORAGE_BLOCK_PRICE_ID", "").strip(),
    )

    recent_count = 0
    last_event: Optional[dict[str, Any]] = None
    outcome_counts: dict[str, int] = {}
    active_sub_count = 0
    duplicate_account_ids: list[str] = []

    try:
        conn = get_db()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT COUNT(*)::int AS n "
                "FROM provider_event_log "
                "WHERE source = 'stripe' "
                "  AND received_at > NOW() "
                "  - (INTERVAL '1 second' * %s);",
                (window_seconds,),
            )
            row = cur.fetchone()
            if row:
                recent_count = int(row.get("n") or 0)

            cur.execute(
                "SELECT source_event_id, outcome, received_at, "
                "  EXTRACT(EPOCH FROM NOW() - received_at)::int "
                "  AS age_seconds "
                "FROM provider_event_log "
                "WHERE source = 'stripe' "
                "ORDER BY received_at DESC "
                "LIMIT 1;",
            )
            row = cur.fetchone()
            if row:
                last_event = {
                    "event_id_prefix": redact_stripe_id(
                        row.get("source_event_id"),
                    ),
                    "outcome":     (row.get("outcome") or ""),
                    "age_seconds": int(row.get("age_seconds") or 0),
                }

            cur.execute(
                "SELECT outcome, COUNT(*)::int AS n "
                "FROM provider_event_log "
                "WHERE source = 'stripe' "
                "  AND received_at > NOW() "
                "  - (INTERVAL '1 hour') "
                "GROUP BY outcome;",
            )
            for row in cur.fetchall():
                outcome = str(row.get("outcome") or "unknown")
                outcome_counts[outcome] = int(row.get("n") or 0)

            cur.execute(
                "SELECT COUNT(*)::int AS n "
                "FROM account_subscriptions "
                "WHERE source = 'stripe' AND status = 'active';",
            )
            row = cur.fetchone()
            if row:
                active_sub_count = int(row.get("n") or 0)

            cur.execute(
                "SELECT account_id::text AS account_id, "
                "  COUNT(*)::int AS n "
                "FROM account_subscriptions "
                "WHERE source = 'stripe' "
                "  AND status IN ('active','in_grace') "
                "GROUP BY account_id "
                "HAVING COUNT(*) > 1 "
                "LIMIT 25;",
            )
            for row in cur.fetchall():
                account_id = str(row.get("account_id") or "")
                duplicate_account_ids.append(
                    redact_stripe_id(account_id),
                )
    except Exception:
        pass

    return {
        "status":                     "ok",
        "schema":                     BILLING_ADMIN_HEALTH_SCHEMA,
        "stripeMode":                 _stripe_mode_label(),
        "apiKeyConfigured":           api_key_configured,
        "webhookSecretConfigured":    webhook_secret_configured,
        "storageBlockPriceConfigured": block_price_configured,
        "recentWebhookCount":         recent_count,
        "recentWebhookWindowSeconds": window_seconds,
        "lastWebhookEvent":           last_event,
        "recentOutcomeCounts":        outcome_counts,
        "activeSubscriptionCount":    active_sub_count,
        "duplicateActiveSubscriptionAccountIdPrefixes": (
            duplicate_account_ids
        ),
    }


# ---------------------------------------------------------------------------
# 2026-07-30 billing lifecycle fixes: cancel_subscription_for_account +
# grace-period sweep. Both required to close the audit findings
# without changing the intended product behavior (users retain full
# read/download/delete access on their existing files after the
# subscription ends; only new uploads are blocked past the free tier).
# ---------------------------------------------------------------------------

class CancelSubscriptionResult:
    """Small typed return for ``cancel_subscription_for_account`` so
    callers can log and audit the outcome. Never raises across the
    boundary."""

    __slots__ = ("outcome", "subscription_id", "detail")

    def __init__(
        self,
        outcome: str,
        subscription_id: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        self.outcome = outcome
        self.subscription_id = subscription_id
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "outcome":              self.outcome,
            "subscription_id_prefix": redact_stripe_id(
                self.subscription_id
            ) if self.subscription_id else None,
            "detail":               self.detail,
        }


def cancel_subscription_for_account(
    account_id: str,
    *,
    reason: Optional[str] = None,
) -> CancelSubscriptionResult:
    """Cancel the Stripe subscription (if any) attached to this
    account. Best-effort — never raises. The single caller today is
    ``vault_deletion_service._cancel_stripe_subscription_best_effort``
    which fires from the 6-month unpaid-inactive cleanup and from
    user-initiated vault deletion. Without this function, deleted
    vaults kept their Stripe subscription live and the customer
    silently kept getting billed for storage they no longer had —
    the audit's billing leak.

    Outcomes:
      * ``cancelled``          — Stripe accepted the delete/cancel.
      * ``noop_no_customer``   — no Stripe customer row for this account.
      * ``noop_no_subscription`` — customer exists but no known
        subscription id.
      * ``noop_stripe_unconfigured`` — Stripe SDK not initialized
        (e.g. dev without STRIPE_API_KEY).
      * ``noop_already_cancelled`` — Stripe reports the subscription
        is already cancelled/deleted.
      * ``error``              — Stripe API raised; details in the
        return.

    Never logs the raw stripe subscription id; only the redacted
    prefix. Sets ``account_subscriptions.canceled_at = NOW()`` on
    success so an audit query can spot cancellations that our code
    (rather than Stripe dunning) initiated.
    """
    if not account_id:
        return CancelSubscriptionResult(
            outcome="noop_no_customer",
            detail="missing_account_id",
        )
    if not _stripe_initialized():
        return CancelSubscriptionResult(
            outcome="noop_stripe_unconfigured",
        )

    try:
        stripe_customer_id = get_stripe_customer_id_for_account(account_id)
    except Exception:
        logger.exception(
            "[STRIPE-CANCEL] customer lookup failed account=%s",
            (account_id or "")[:8],
        )
        return CancelSubscriptionResult(
            outcome="error",
            detail="customer_lookup_failed",
        )
    if not stripe_customer_id:
        return CancelSubscriptionResult(outcome="noop_no_customer")

    # Look up the last-known subscription id from our own state.
    subscription_id: Optional[str] = None
    try:
        conn = get_db()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT source_subscription_id "
                    "  FROM account_subscriptions "
                    " WHERE account_id = %s "
                    "   AND source = 'stripe' "
                    " LIMIT 1;",
                    (account_id,),
                )
                row = cur.fetchone()
                if row:
                    subscription_id = str(
                        row.get("source_subscription_id") or ""
                    ) or None
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "[STRIPE-CANCEL] subscription id lookup failed account=%s",
            (account_id or "")[:8],
        )
        return CancelSubscriptionResult(
            outcome="error",
            detail="subscription_id_lookup_failed",
        )
    if not subscription_id:
        return CancelSubscriptionResult(
            outcome="noop_no_subscription",
        )

    # Try the modern SDK method first (Stripe SDK >= 6.x uses
    # ``Subscription.cancel``; older SDKs expose ``Subscription.delete``).
    # Both immediately cancel the subscription without proration or a
    # further invoice. Failures are logged and translated to an
    # ``error`` outcome — never raised past this boundary.
    try:
        cancelled_obj = None
        _err_details: Optional[str] = None
        try:
            cancelled_obj = stripe.Subscription.cancel(subscription_id)
        except AttributeError:
            try:
                cancelled_obj = stripe.Subscription.delete(subscription_id)
            except Exception as exc:
                _err_details = f"delete_raised:{type(exc).__name__}"
        except stripe.error.InvalidRequestError as exc:
            # Idempotent path: already cancelled on Stripe's side.
            msg = str(exc).lower()
            if (
                "no such subscription" in msg
                or "already been cancel" in msg
                or "already been cancele" in msg
            ):
                return CancelSubscriptionResult(
                    outcome="noop_already_cancelled",
                    subscription_id=subscription_id,
                )
            _err_details = f"invalid_request:{type(exc).__name__}"
        except Exception as exc:
            _err_details = f"raised:{type(exc).__name__}"

        if _err_details:
            logger.warning(
                "[STRIPE-CANCEL] stripe cancel failed account=%s sub=%s "
                "detail=%s",
                (account_id or "")[:8],
                redact_stripe_id(subscription_id),
                _err_details,
            )
            return CancelSubscriptionResult(
                outcome="error",
                subscription_id=subscription_id,
                detail=_err_details,
            )
    except Exception as exc:
        logger.exception(
            "[STRIPE-CANCEL] stripe cancel unexpected account=%s",
            (account_id or "")[:8],
        )
        return CancelSubscriptionResult(
            outcome="error",
            subscription_id=subscription_id,
            detail=f"unexpected:{type(exc).__name__}",
        )

    # Local audit stamp — records that OUR code initiated the cancel
    # (as opposed to Stripe's dunning). Best-effort; the Stripe
    # cancellation is already the source of truth.
    try:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE account_subscriptions
                       SET canceled_at = NOW(),
                           updated_at  = NOW()
                     WHERE account_id = %s
                       AND source = 'stripe';
                    """,
                    (account_id,),
                )
                cur.execute(
                    """
                    INSERT INTO subscription_events (
                        account_id, event_type, source, source_event_id,
                        sales_channel, occurred_at, payload_jsonb
                    )
                    VALUES (%s, 'canceled_by_vaultai', 'stripe', %s,
                            'self_service', NOW(), %s);
                    """,
                    (
                        account_id,
                        (subscription_id or "")[:64],
                        Json({
                            "reason":            reason or "vault_deletion",
                            "initiator":         "backend",
                        }),
                    ),
                )
                conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "[STRIPE-CANCEL] local audit stamp failed account=%s",
            (account_id or "")[:8],
        )

    logger.info(
        "[STRIPE-CANCEL] cancelled account=%s sub=%s reason=%s",
        (account_id or "")[:8],
        redact_stripe_id(subscription_id),
        (reason or "vault_deletion"),
    )
    return CancelSubscriptionResult(
        outcome="cancelled",
        subscription_id=subscription_id,
    )


def sweep_expired_grace_periods(*, now_iso: Optional[str] = None) -> dict:
    """2026-07-30 grace-state enforcer. Called from the daily
    ``inactive_unpaid_cleanup`` sweeper at the start of each run.

    Two transitions:

      * ``in_grace`` rows whose ``grace_period_ends_at`` is in the
        past → transitioned to ``past_due``. This mirrors what
        Stripe's ``unpaid`` status maps to internally
        (``stripe_service.py:1607-1616``) but does not depend on
        Stripe firing a further webhook. Emits a
        ``billing.payment_failed`` banner (final failure).
      * ``over_quota_grace`` rows whose
        ``over_quota_grace_ends_at`` is in the past → transitioned
        to ``over_quota_locked``. Entitlement is unchanged
        (already free-tier since block_count=0), but the state
        transition is now recorded so the DB reflects reality.
        Emits a ``billing.account_over_quota`` banner.

    Both are read-only for user data; no encrypted content, PIN
    material, or vault metadata is touched. Idempotent — running
    the sweep twice back-to-back is a no-op on the second run.

    Returns a dict summarizing how many rows were transitioned and
    how many notifications were dispatched. Never raises across the
    boundary.
    """
    result = {
        "in_grace_expired":         0,
        "over_quota_grace_expired": 0,
        "notifications_sent":       0,
        "errors":                   [],
    }
    try:
        conn = get_db()
    except Exception:
        try:
            result["errors"].append("db_connect_failed")
        except Exception:
            pass
        return result

    try:
        # in_grace -> past_due
        expired_grace_accounts: list[str] = []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE account_subscriptions
                       SET status     = 'past_due',
                           updated_at = NOW()
                     WHERE status = 'in_grace'
                       AND grace_period_ends_at IS NOT NULL
                       AND grace_period_ends_at < NOW()
                    RETURNING account_id;
                    """
                )
                for row in cur.fetchall() or []:
                    expired_grace_accounts.append(str(row.get("account_id")))
                for account_id in expired_grace_accounts:
                    cur.execute(
                        """
                        INSERT INTO subscription_events (
                            account_id, event_type, source, source_event_id,
                            sales_channel, occurred_at, payload_jsonb
                        )
                        VALUES (%s, 'grace_expired', 'vaultai', %s,
                                'self_service', NOW(), %s);
                        """,
                        (
                            account_id,
                            f"grace-sweep-{account_id[:16]}",
                            Json({
                                "reason":     "grace_period_elapsed",
                                "from":       "in_grace",
                                "to":         "past_due",
                            }),
                        ),
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("[STRIPE-SWEEP] in_grace transition failed")
            result["errors"].append("in_grace_transition_failed")
            expired_grace_accounts = []

        result["in_grace_expired"] = len(expired_grace_accounts)

        # over_quota_grace -> over_quota_locked
        expired_oq_accounts: list[str] = []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE account_subscriptions
                       SET status     = 'over_quota_locked',
                           updated_at = NOW()
                     WHERE status = 'over_quota_grace'
                       AND over_quota_grace_ends_at IS NOT NULL
                       AND over_quota_grace_ends_at < NOW()
                    RETURNING account_id;
                    """
                )
                for row in cur.fetchall() or []:
                    expired_oq_accounts.append(str(row.get("account_id")))
                for account_id in expired_oq_accounts:
                    cur.execute(
                        """
                        INSERT INTO subscription_events (
                            account_id, event_type, source, source_event_id,
                            sales_channel, occurred_at, payload_jsonb
                        )
                        VALUES (%s, 'over_quota_locked', 'vaultai', %s,
                                'self_service', NOW(), %s);
                        """,
                        (
                            account_id,
                            f"oq-sweep-{account_id[:16]}",
                            Json({
                                "reason":     "over_quota_grace_elapsed",
                                "from":       "over_quota_grace",
                                "to":         "over_quota_locked",
                            }),
                        ),
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception(
                "[STRIPE-SWEEP] over_quota_grace transition failed",
            )
            result["errors"].append("over_quota_transition_failed")
            expired_oq_accounts = []

        result["over_quota_grace_expired"] = len(expired_oq_accounts)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Notifications — done AFTER the transactions commit so a failure
    # here can't leave the DB in an inconsistent state.
    try:
        from vault_billing_notifications import (
            notify_payment_failed,
            notify_account_over_quota,
        )
    except Exception:
        return result

    for account_id in expired_grace_accounts:
        try:
            notify_payment_failed(
                account_id,
                # Sweep produces "final failure" notification with no
                # grace timer field (grace already elapsed).
                grace_period_ends_at_iso=None,
            )
            result["notifications_sent"] += 1
        except Exception:
            logger.exception(
                "[STRIPE-SWEEP] payment_failed notify failed account=%s",
                (account_id or "")[:8],
            )
    for account_id in expired_oq_accounts:
        try:
            notify_account_over_quota(account_id)
            result["notifications_sent"] += 1
        except Exception:
            logger.exception(
                "[STRIPE-SWEEP] account_over_quota notify failed "
                "account=%s", (account_id or "")[:8],
            )
    return result


__all__ = [
    "StripeUnconfiguredError",
    "StripeCeilingExceededError",
    "StripeCheckoutRejectedError",
    "StripeSignatureError",
    "StripeEventDecodeError",
    "StripeSubscriptionAlreadyAtQuantityError",
    "StripeSubscriptionDowngradeUnsupportedError",
    "CheckoutSession",
    "PortalSession",
    "WebhookDispatchResult",
    "ActiveStorageSubscription",
    "SubscriptionQuantityUpdate",
    "CancelSubscriptionResult",
    "BILLING_ADMIN_HEALTH_SCHEMA",
    "create_checkout_session",
    "create_portal_session",
    "verify_webhook_signature",
    "dispatch_webhook_event",
    "get_active_storage_subscription",
    "modify_existing_subscription_quantity",
    "backfill_subscription_item_id_from_stripe",
    "cancel_duplicate_storage_subscriptions",
    "cancel_subscription_for_account",
    "sweep_expired_grace_periods",
    "get_stripe_customer_id_for_account",
    "upsert_stripe_customer",
    "probe_stripe_price_currency",
    "build_billing_admin_health_envelope",
    "redact_stripe_id",
    "stripe_mode_label",
    "block_bytes",
    "block_price_cents_usd",
]
