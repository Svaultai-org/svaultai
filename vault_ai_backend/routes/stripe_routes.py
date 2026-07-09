

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from device_gate import verify_trusted_device


logger = logging.getLogger(__name__)
router = APIRouter()


class CheckoutSessionRequest(BaseModel):
    block_count: int = Field(..., ge=1, le=10_000)
    success_url: Optional[str] = Field(None, max_length=2048)
    cancel_url:  Optional[str] = Field(None, max_length=2048)


@router.post("/billing/checkout-session")
async def create_checkout_session_endpoint(
    payload: CheckoutSessionRequest,
    principal=Depends(verify_trusted_device),
):


    vault_id = principal["vault_id"]

                                                                     
    print(
        "[STRIPE] checkout-session REQUEST "
        f"vault_id={vault_id!r} "
        f"requested_blocks={payload.block_count} "
        f"has_success_url={bool(payload.success_url)} "
        f"has_cancel_url={bool(payload.cancel_url)}",
        flush=True,
    )

    from billing import ensure_account_for_vault
    from stripe_service import (
        StripeCeilingExceededError,
        StripeCheckoutRejectedError,
        StripeSubscriptionAlreadyAtQuantityError,
        StripeSubscriptionDowngradeUnsupportedError,
        StripeUnconfiguredError,
        backfill_subscription_item_id_from_stripe,
        create_checkout_session,
        get_active_storage_subscription,
        modify_existing_subscription_quantity,
    )

    account_id = ensure_account_for_vault(vault_id)
    active = get_active_storage_subscription(account_id)

                                                                        
    if active and not active.stripe_subscription_item_id:
        try:
            active = backfill_subscription_item_id_from_stripe(active)
        except StripeUnconfiguredError:
                                                                        
                                              
            pass
        except Exception as exc:
            logger.exception(
                "backfill_subscription_item_id_from_stripe raised — "
                "falling back to Checkout for account_id=%s sub_id=%s",
                account_id, active.stripe_subscription_id,
            )
            print(
                "[STRIPE] checkout-session dispatch backfill RAISED "
                f"account_id={account_id!r} "
                f"sub_id={active.stripe_subscription_id!r} "
                f"error_type={type(exc).__name__} "
                f"error={exc!s}",
                flush=True,
            )
                                                                    
                                                                       
    print(
        "[STRIPE] checkout-session dispatch "
        f"account_id={account_id!r} "
        f"requested_blocks={payload.block_count} "
        f"active_sub={'yes' if active else 'no'} "
        f"active_blocks={active.block_count if active else None} "
        f"has_item_id={bool(active and active.stripe_subscription_item_id)}",
        flush=True,
    )

    try:
        if active and active.stripe_subscription_item_id:
                                                                     
            update = modify_existing_subscription_quantity(
                active=active,
                new_block_count=payload.block_count,
            )
            return {
                "action": "updated_existing",
                "previous_blocks": update.previous_block_count,
                "new_blocks":      update.new_block_count,
                "stripe_subscription_id":      update.stripe_subscription_id,
                "stripe_subscription_item_id": update.stripe_subscription_item_id,
            }
                                                            
        result = create_checkout_session(
            account_id=account_id,
            vault_id=vault_id,
            block_count=payload.block_count,
            success_url=payload.success_url,
            cancel_url=payload.cancel_url,
        )
    except StripeSubscriptionAlreadyAtQuantityError as exc:
                                                                       
                                                                     
        raise HTTPException(
            status_code=400,
            detail={
                "code": "no_change",
                "message": (
                    "You already have that storage plan. Pick a "
                    "different tier or manage your subscription."
                ),
                "current_blocks":   exc.current_blocks,
                "requested_blocks": exc.requested_blocks,
            },
        )
    except StripeSubscriptionDowngradeUnsupportedError as exc:
                                                                 
                                                                   
        raise HTTPException(
            status_code=400,
            detail={
                "code": "downgrade_not_supported",
                "message": (
                    "Downgrades aren't available from this screen. "
                    "Open Manage subscription to cancel or schedule a "
                    "lower plan."
                ),
                "current_blocks":   exc.current_blocks,
                "requested_blocks": exc.requested_blocks,
            },
        )
    except StripeCeilingExceededError as exc:
                                                           
                                  
        raise HTTPException(
            status_code=400,
            detail={
                "code": "enterprise_required",
                "message": (
                    "For storage above the self-service maximum, "
                    "contact sales."
                ),
                "requested_blocks": exc.requested_blocks,
                "self_service_max_blocks": exc.max_blocks,
            },
        )
    except StripeUnconfiguredError as exc:
                                                                      
                                                                         
        logger.error("Stripe unconfigured: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stripe_unconfigured",
                "message": (
                    "Storage purchases are temporarily unavailable. "
                    "Please try again shortly."
                ),
            },
        )
    except StripeCheckoutRejectedError as exc:
                                                                        
                                                                     
        raise HTTPException(
            status_code=400,
            detail={
                "code": "stripe_checkout_invalid_request",
                "message": (
                    "Stripe rejected the checkout request. See the "
                    "stripe_message field for the specific reason."
                ),
                "stripe_type":    exc.stripe_type,
                "stripe_code":    exc.stripe_code,
                "stripe_message": exc.stripe_message,
                "stripe_param":   exc.param,
            },
        )
    except Exception as exc:
                                                                      
                                                                    
        logger.exception("checkout-session failed vault=%s", vault_id)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "checkout_session_error",
                "message": f"Could not start checkout: {type(exc).__name__}",
            },
        )

                                                               
    return {
        "action":       "open_checkout",
        "checkout_url": result.checkout_url,
        "session_id":   result.session_id,
    }


@router.post("/billing/dev/cleanup-duplicate-subs")
async def dev_cleanup_duplicate_subs(
    principal=Depends(verify_trusted_device),
):


    from device_gate import is_dev_auto_trust_enabled
    from vault_config import is_production
    if is_production():
        raise HTTPException(
            status_code=403,
            detail={
                "code": "dev_cleanup_disabled_in_production",
                "message": (
                    "Dev cleanup endpoint refuses to run in production. "
                    "This route only serves local/dev environments."
                ),
            },
        )
    if not is_dev_auto_trust_enabled():
        raise HTTPException(
            status_code=403,
            detail={
                "code": "dev_cleanup_disabled",
                "message": (
                    "Dev-only endpoint. Requires "
                    "VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST=true AND a dev "
                    "environment signal (VAULTAI_ENV=local etc.)."
                ),
            },
        )

    vault_id = principal["vault_id"]

    from billing import ensure_account_for_vault
    from stripe_service import (
        StripeUnconfiguredError,
        cancel_duplicate_storage_subscriptions,
        get_active_storage_subscription,
        get_stripe_customer_id_for_account,
    )

    account_id = ensure_account_for_vault(vault_id)
    customer_id = get_stripe_customer_id_for_account(account_id)
    if not customer_id:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "no_stripe_customer",
                "message": (
                    "This account has no Stripe customer record — "
                    "nothing to clean up."
                ),
            },
        )
    active = get_active_storage_subscription(account_id)
    if not active:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "no_active_subscription_to_keep",
                "message": (
                    "account_subscriptions has no active Stripe sub on "
                    "record. Fix the DB row to point at the sub you "
                    "want to keep, then re-run."
                ),
            },
        )

    try:
        summary = cancel_duplicate_storage_subscriptions(
            account_id=account_id,
            customer_id=customer_id,
            keep_subscription_id=active.stripe_subscription_id,
        )
    except StripeUnconfiguredError:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stripe_unconfigured",
                "message": (
                    "Stripe API key not configured; cannot cancel "
                    "duplicates."
                ),
            },
        )
    return summary


class PortalSessionRequest(BaseModel):
    return_url: Optional[str] = Field(None, max_length=2048)


@router.post("/billing/portal-session")
async def create_portal_session_endpoint(
    payload: PortalSessionRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]

    from billing import ensure_account_for_vault
    from stripe_service import (
        StripeUnconfiguredError,
        create_portal_session,
    )

    account_id = ensure_account_for_vault(vault_id)

    try:
        result = create_portal_session(
            account_id=account_id,
            return_url=payload.return_url,
        )
    except LookupError:
                                                                    
                                                                        
        raise HTTPException(
            status_code=404,
            detail={
                "code": "no_stripe_customer",
                "message": (
                    "You don't have a Stripe subscription yet — "
                    "purchase storage first."
                ),
            },
        )
    except StripeUnconfiguredError as exc:
        logger.error("Stripe unconfigured for portal: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stripe_unconfigured",
                "message": (
                    "Subscription management is temporarily unavailable. "
                    "Please try again shortly."
                ),
            },
        )
    except Exception as exc:
        logger.exception("portal-session failed vault=%s", vault_id)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "portal_session_error",
                "message": f"Could not open subscription portal: {type(exc).__name__}",
            },
        )

    return {"portal_url": result.portal_url}


@router.post("/billing/stripe/webhook")
async def stripe_webhook(request: Request):
    raw_body: bytes = await request.body()
    signature_header = request.headers.get("stripe-signature", "")

                                                                    
    print(
        "[STRIPE] webhook received "
        f"body_bytes={len(raw_body)} "
        f"signature_header_present={bool(signature_header)}",
        flush=True,
    )

    from stripe_service import (
        StripeEventDecodeError,
        StripeSignatureError,
        StripeUnconfiguredError,
        dispatch_webhook_event,
        verify_webhook_signature,
    )

    if not signature_header:
                                                                      
                    
        print(
            "[STRIPE] webhook signature fail reason=missing_signature_header",
            flush=True,
        )
        return JSONResponse(
            status_code=400,
            content={
                "code": "missing_signature",
                "message": "Stripe-Signature header missing.",
            },
        )

    try:
        event = verify_webhook_signature(
            payload=raw_body, signature_header=signature_header,
        )
    except StripeUnconfiguredError:
                                                               
        print(
            "[STRIPE] webhook signature fail reason=stripe_unconfigured",
            flush=True,
        )
        return JSONResponse(
            status_code=503,
            content={
                "code": "stripe_unconfigured",
                "message": "Webhook secret not configured.",
            },
        )
    except StripeSignatureError as exc:
                                                                 
                                                                      
        print(
            "[STRIPE] webhook signature fail "
            f"reason=signature_verification "
            f"error_type={type(exc.underlying).__name__} "
            f"detail={exc.reason!r}",
            flush=True,
        )
        logger.warning(
            "stripe webhook signature invalid: %s",
            type(exc.underlying).__name__,
        )
        return JSONResponse(
            status_code=400,
            content={
                "code": "invalid_signature",
                "message": "Stripe signature verification failed.",
            },
        )
    except StripeEventDecodeError as exc:
                                                                       
                                                                       
        underlying = exc.underlying
        key_repr = None
        if isinstance(underlying, KeyError) and underlying.args:
            try:
                key_repr = repr(underlying.args[0])
            except Exception:
                key_repr = "<unreprable>"
        print(
            "[STRIPE] webhook decode fail "
            f"reason=event_decode "
            f"error_type={type(underlying).__name__} "
            f"key={key_repr!r} "
            f"detail={exc.reason!r}",
            flush=True,
        )
                                                                      
        logger.exception(
            "stripe webhook event decode failed: %s",
            type(underlying).__name__,
        )
        return JSONResponse(
            status_code=400,
            content={
                "code": "event_decode_failed",
                "message": (
                    "Stripe signature verified but event payload could "
                    "not be decoded. See server logs for the missing "
                    "field."
                ),
                "error_type": type(underlying).__name__,
            },
        )
    except Exception as exc:
                                                                  
                                                                     
        print(
            "[STRIPE] webhook verify fail "
            f"reason=unexpected "
            f"error_type={type(exc).__name__}",
            flush=True,
        )
        logger.exception(
            "stripe webhook unexpected error during verify: %s",
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=400,
            content={
                "code": "verify_unexpected_error",
                "message": "Unexpected error verifying webhook.",
                "error_type": type(exc).__name__,
            },
        )

    print(
        "[STRIPE] webhook signature ok "
        f"event_id={event.get('id')!r} "
        f"type={event.get('type')!r} "
        f"livemode={event.get('livemode')!r}",
        flush=True,
    )

    result = dispatch_webhook_event(event)

    print(
        "[STRIPE] webhook outcome "
        f"event_id={result.event_id!r} "
        f"type={result.event_type!r} "
        f"outcome={result.outcome!r} "
        f"account_id={result.account_id!r} "
        f"error_text={result.error_text!r}",
        flush=True,
    )

                                                                       
    if result.outcome == "applied" and result.account_id:
        try:
            from billing import get_entitlement
            ent = get_entitlement(result.account_id)
                                                                       
                                                                     
            tier = "paid" if (
                ent.block_count > 0 and ent.purchased_bytes > 0
            ) else "free"
            print(
                "[STRIPE] entitlement after webhook "
                f"event_id={result.event_id!r} "
                f"account_id={result.account_id!r} "
                f"tier={tier!r} "
                f"block_count={ent.block_count} "
                f"purchased_bytes={ent.purchased_bytes} "
                f"included_bytes={ent.included_bytes} "
                f"effective_limit_bytes={ent.effective_limit_bytes} "
                f"status={ent.status!r} "
                f"source={ent.source!r}",
                flush=True,
            )
        except Exception as exc:
                                                                  
                                                                     
            print(
                "[STRIPE] entitlement after webhook FAILED "
                f"event_id={result.event_id!r} "
                f"account_id={result.account_id!r} "
                f"error_type={type(exc).__name__} "
                f"error={exc!r}",
                flush=True,
            )


    return {
        "outcome":    result.outcome,
        "event_id":   result.event_id,
        "event_type": result.event_type,
    }


def _billing_admin_safe_eq(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a, b):
        diff |= ord(x) ^ ord(y)
    return diff == 0


@router.get("/billing/admin/health")
async def get_billing_admin_health(request: Request):
    from vault_config import (
        billing_admin_health_token,
        cache as _cache_cfg,
    )
    from stripe_service import build_billing_admin_health_envelope

    expected = billing_admin_health_token()
    provided = (
        request.headers.get("X-Billing-Health-Admin-Token")
        or request.headers.get("x-billing-health-admin-token")
        or ""
    ).strip()
    debug_ok = _cache_cfg().debug_endpoints_enabled

    if expected:
        if not provided or not _billing_admin_safe_eq(
            expected, provided,
        ):
            raise HTTPException(
                status_code=403,
                detail={
                    "code":    "billing_admin_forbidden",
                    "message": "Admin token required.",
                },
            )
    elif not debug_ok:
        raise HTTPException(
            status_code=403,
            detail={
                "code":    "billing_admin_forbidden",
                "message": (
                    "Billing admin health requires "
                    "VAULTAI_BILLING_HEALTH_ADMIN_TOKEN in production."
                ),
            },
        )
    return build_billing_admin_health_envelope()
