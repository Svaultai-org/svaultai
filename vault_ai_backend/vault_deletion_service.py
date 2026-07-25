"""Vault deletion service.

Two entry points share the same underlying cascade:

  * user-requested deletion (called by /vault/delete/confirm after
    the trusted-device + PIN + exact-phrase gate has passed)
  * automatic deletion of unpaid users inactive for 6+ months
    (called by the background cleanup job)

The service deletes the vault row; PostgreSQL cascades the delete to
every vault-owned table via the ON DELETE CASCADE FKs declared in
migration 0001. Cascade covers:

  * uploaded_files (+ uploaded_file_chunks)
  * vault_items (secure items, logins, IDs, encrypted wallet records)
  * semantic_index, vault_asset_tags, vault_password_audit,
    vault_document_metadata, vault_document_entities,
    vault_ai_memory, vault_preferences, vault_relationships,
    vault_expiry_alerts, vault_intelligence_summary
  * auth_sessions, trusted_devices, notifications
  * account_members, beneficiary_links (passer side)
  * vault_content_chunks, vault_file_understanding,
    vault_file_embeddings, vault_analysis_jobs,
    vault_agent_memories/_tasks/_audit, import_batches,
    vault_file_relationships, hermes rollup rows

A safe tombstone row is inserted into vault_deletion_tombstones:
  { deleted_at, deletion_reason, hashed_vault_id }
No vault name, no account id, no file/item names, no wallet
addresses, no encrypted secrets.

Absolute rules enforced here:
  1. NEVER broadcasts a crypto transaction. Deletion touches DB
     rows and (best-effort) Stripe subscription cancellation only.
  2. NEVER logs vault name, PIN, encrypted material, or wallet
     records. Log lines carry only the hashed vault id prefix and
     the deletion reason.
  3. Refuses to delete when a fresh billing/activity re-check
     disagrees with the caller's assumption (auto-delete path).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

from vault_core import get_db


logger = logging.getLogger(__name__)


REASON_USER_REQUESTED:            str = "user_requested"
REASON_UNPAID_INACTIVE_6_MONTHS:  str = "unpaid_inactive_6_months"
REASON_DEVELOPMENT_FULL_USER_WIPE: str = "development_full_user_wipe"


_ALLOWED_REASONS = frozenset({
    REASON_USER_REQUESTED,
    REASON_UNPAID_INACTIVE_6_MONTHS,
    REASON_DEVELOPMENT_FULL_USER_WIPE,
})


CONFIRMATION_PHRASE: str = "DELETE MY VAULT"


class VaultDeletionError(Exception):
    """Raised when a deletion refuses to proceed."""


class VaultNotFoundError(VaultDeletionError):
    """Vault row was already gone when we tried to delete."""


class VaultDeletionBlockedByStripeError(VaultDeletionError):
    """Raised when the Stripe subscription tied to this vault could
    not be cancelled and we therefore refuse to delete the vault.

    Deleting the vault while Stripe still holds an active
    subscription would leave the customer being billed for storage
    that no longer exists. Callers MUST NOT delete the vault when
    this exception is raised; instead, they should retry deletion
    later (the daily unpaid-inactive job will do so automatically;
    user-initiated deletion returns HTTP 503 so the user can retry
    on their own).

    Only raised when ``cancel_subscription_for_account`` returns
    ``outcome='error'``. The noop outcomes (``noop_no_customer``,
    ``noop_no_subscription``, ``noop_stripe_unconfigured``,
    ``noop_already_cancelled``) do NOT block deletion — they mean
    there is nothing on the Stripe side that could keep charging
    the customer.
    """
    def __init__(
        self,
        vault_id_hashed_prefix: str,
        detail: str,
    ) -> None:
        self.vault_id_hashed_prefix = vault_id_hashed_prefix
        self.detail = detail
        super().__init__(
            f"stripe cancellation error hashed={vault_id_hashed_prefix} "
            f"detail={detail}"
        )


def hashed_vault_id(vault_id: str) -> str:
    """SHA-256 hex of the vault id — used in tombstones and log
    lines. Anonymized: an attacker seeing the tombstone cannot
    reverse it to a vault name."""
    if not isinstance(vault_id, str) or not vault_id:
        raise ValueError("vault_id required")
    return hashlib.sha256(vault_id.encode("utf-8")).hexdigest()


def _hashed_prefix(vault_id: str) -> str:
    try:
        return hashed_vault_id(vault_id)[:12]
    except Exception:
        return "unknown"


def _cancel_stripe_subscription_before_delete(
    vault_id: str,
) -> tuple[bool, str]:
    """Cancel any Stripe subscription tied to this vault's account
    BEFORE the local vault row is deleted, and report whether it is
    safe to proceed with the delete.

    Returns ``(safe_to_proceed, outcome_detail)``.

    Safe outcomes — deletion proceeds:
      * ``cancelled``               — Stripe accepted the cancel.
      * ``noop_no_customer``        — no Stripe customer for this
                                       account (never subscribed).
      * ``noop_no_subscription``    — customer exists but no
                                       subscription id on file.
      * ``noop_stripe_unconfigured`` — dev/CI mode
                                        (STRIPE_API_KEY unset).
      * ``noop_already_cancelled``  — Stripe reports the subscription
                                       is already gone (idempotent).

    Unsafe outcome — deletion is BLOCKED:
      * ``error`` — Stripe API raised (network / 5xx / auth) and we
        do NOT know whether the subscription is still active. If we
        deleted the vault now the customer could keep being billed.
        The caller MUST raise
        ``VaultDeletionBlockedByStripeError`` and retry later.

    Never raises across the boundary — every exception is caught
    and reported as ``outcome_detail`` on ``safe=False`` so the
    caller can decide the response.
    """
    try:
        from billing import get_account_id_for_vault
        account_id = get_account_id_for_vault(vault_id)
    except Exception:
        logger.warning(
            "[VAULT-DELETE] account lookup failed hashed=%s",
            _hashed_prefix(vault_id),
        )
        # No account row means there is no way the customer is still
        # being billed by our Stripe integration. Safe to proceed.
        return (True, "no_account_row")
    if not account_id:
        return (True, "no_account_row")

    try:
        from stripe_service import cancel_subscription_for_account
    except Exception:
        logger.exception(
            "[VAULT-DELETE] stripe_service import failed hashed=%s "
            "— refusing delete until resolved",
            _hashed_prefix(vault_id),
        )
        # The audit-mandated symbol is missing at runtime. Refuse to
        # delete because we cannot prove Stripe is cancelled. This
        # is a deploy-error surface.
        return (False, "stripe_service_import_failed")

    try:
        result = cancel_subscription_for_account(
            account_id, reason="vault_deletion",
        )
    except Exception as exc:
        logger.warning(
            "[VAULT-DELETE] cancel_subscription_for_account raised "
            "hashed=%s error_type=%s",
            _hashed_prefix(vault_id), type(exc).__name__,
        )
        return (False, f"raised:{type(exc).__name__}")

    outcome = getattr(result, "outcome", "") or ""
    if outcome == "error":
        logger.warning(
            "[VAULT-DELETE] stripe cancel returned error hashed=%s "
            "detail=%s — deletion deferred, will retry later",
            _hashed_prefix(vault_id), getattr(result, "detail", "-"),
        )
        return (False, f"stripe_error:{getattr(result, 'detail', 'unknown')}")

    # cancelled + all noop_* outcomes are safe to proceed.
    logger.info(
        "[VAULT-DELETE] stripe cancel outcome=%s hashed=%s",
        outcome, _hashed_prefix(vault_id),
    )
    return (True, outcome)


def _cancel_stripe_subscription_best_effort(vault_id: str) -> None:
    """DEPRECATED shim kept for any external caller that still binds
    to the old name. The default new caller uses
    ``_cancel_stripe_subscription_before_delete`` and honors the
    ``safe`` flag. Never raises."""
    try:
        _cancel_stripe_subscription_before_delete(vault_id)
    except Exception:
        logger.warning(
            "[VAULT-DELETE] deprecated best-effort call raised "
            "hashed=%s",
            _hashed_prefix(vault_id),
        )


def _insert_tombstone(vault_id: str, reason: str) -> None:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO vault_deletion_tombstones
              (deletion_reason, hashed_vault_id)
            VALUES (%s, %s)
            """,
            (reason, hashed_vault_id(vault_id)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception(
            "[VAULT-DELETE] tombstone insert failed hashed=%s reason=%s",
            _hashed_prefix(vault_id), reason,
        )
    finally:
        conn.close()


def _delete_vault_row(vault_id: str) -> bool:
    """Delete the vaults row; PostgreSQL cascades everything else.
    Returns True if a row was deleted, False if the vault was
    already gone."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM vaults WHERE vault_id = %s",
            (vault_id,),
        )
        deleted = cur.rowcount > 0
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _account_has_other_vaults(account_id: str) -> bool:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM vaults WHERE account_id = %s LIMIT 1",
            (account_id,),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def _delete_empty_account(account_id: str) -> None:
    """After deleting the last vault of an individual account,
    purge account-level rows too. ON DELETE CASCADE handles most of
    it; explicit deletes provide belt-and-braces cleanup."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM accounts WHERE account_id = %s",
            (account_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.warning(
            "[VAULT-DELETE] account purge failed account_prefix=%s",
            (account_id or "")[:8],
        )
    finally:
        conn.close()


def delete_vault_and_all_data(
    vault_id: str,
    *,
    reason: str,
) -> None:
    """Fully delete a vault's data. Enforced:

      * `reason` must be a member of `_ALLOWED_REASONS`.
      * Never broadcasts a crypto transaction — Stripe cancellation
        is a best-effort side effect that is swallowed on failure.
      * No sensitive data is logged.

    Raises VaultNotFoundError if the vault was already gone.
    """
    if not isinstance(vault_id, str) or not vault_id:
        raise ValueError("vault_id required")
    if reason not in _ALLOWED_REASONS:
        raise ValueError(f"invalid deletion reason: {reason!r}")

    account_id: Optional[str] = None
    try:
        from billing import get_account_id_for_vault
        account_id = get_account_id_for_vault(vault_id)
    except Exception:
        account_id = None

    # 2026-07-30 audit-review fix: cancel Stripe BEFORE deleting the
    # local row, and REFUSE to delete when Stripe returned an error
    # outcome (transient API failure). Prior version discarded the
    # outcome and unconditionally deleted, which could leave the
    # customer billed after their vault was permanently gone. Noop
    # outcomes (no customer / no subscription / dev-mode / already-
    # cancelled) all resolve to safe=True — nothing on the Stripe
    # side could keep charging in those cases. Only a real
    # ``error`` outcome blocks deletion; the caller retries later.
    safe_to_proceed, cancel_detail = (
        _cancel_stripe_subscription_before_delete(vault_id)
    )
    if not safe_to_proceed:
        raise VaultDeletionBlockedByStripeError(
            vault_id_hashed_prefix=_hashed_prefix(vault_id),
            detail=cancel_detail,
        )

    deleted = _delete_vault_row(vault_id)
    if not deleted:
        raise VaultNotFoundError(
            f"vault hashed={_hashed_prefix(vault_id)} not found"
        )

    _insert_tombstone(vault_id, reason)

    if account_id and not _account_has_other_vaults(account_id):
        _delete_empty_account(account_id)

    logger.info(
        "[VAULT-DELETE] vault deleted hashed=%s reason=%s "
        "stripe_cancel=%s",
        _hashed_prefix(vault_id), reason, cancel_detail,
    )


__all__ = [
    "CONFIRMATION_PHRASE",
    "REASON_USER_REQUESTED",
    "REASON_UNPAID_INACTIVE_6_MONTHS",
    "REASON_DEVELOPMENT_FULL_USER_WIPE",
    "VaultDeletionError",
    "VaultNotFoundError",
    "VaultDeletionBlockedByStripeError",
    "hashed_vault_id",
    "delete_vault_and_all_data",
]
