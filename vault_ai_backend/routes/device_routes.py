

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from auth_local import verify_session_token
from device_gate import (
    is_dev_auto_trust_enabled,
    load_self_approval_cooldown_seconds,
    verify_caller_is_trusted_device,
    verify_trusted_device,
)
from device_monitor import (
    ip_prefix_from,
    list_devices_for_vault,
    register_or_refresh,
)
from vault_core import get_db, verify_vault_pin


logger = logging.getLogger(__name__)

router = APIRouter()


SELF_APPROVAL_COOLDOWN_SECONDS = load_self_approval_cooldown_seconds()


def _notify(vault_id: str, kind: str, title: str, body: str,
            metadata: Optional[dict] = None) -> None:


    try:
        from vault_core import is_vault_zk_adopted
        # ZK/adopted vault: never persist readable device-related
        # notification title/body. Insert a structural-only shell.
        if is_vault_zk_adopted(vault_id):
            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO notifications
                        (vault_id, kind, title, body, metadata)
                    VALUES (%s, %s, NULL, NULL, NULL)
                    """,
                    (vault_id, kind),
                )
                conn.commit()
            finally:
                conn.close()
            return

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO notifications (vault_id, kind, title, body, metadata)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (vault_id, kind, title, body,
                 json.dumps(metadata) if metadata else None),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("Notification insert failed (kind=%s)", kind)


_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{16,128}$")
_LABEL_MAX_LEN = 64


class RegisterDeviceRequest(BaseModel):
    device_id: str
    label: Optional[str] = None
    user_agent_brand: Optional[str] = None


def _validate_device_id(device_id: str) -> str:
    if not _DEVICE_ID_RE.match(device_id or ""):
        raise HTTPException(status_code=400, detail="Invalid device_id format")
    return device_id


def _clean_label(label: Optional[str]) -> Optional[str]:
    if not label:
        return None
    s = label.strip()
    if not s:
        return None
    return s[:_LABEL_MAX_LEN]


@router.post("/devices/register")
async def register_device_endpoint(
    payload: RegisterDeviceRequest,
    request: Request,
    principal=Depends(verify_trusted_device),
):


    vault_id = principal["vault_id"]
    device_id = _validate_device_id(payload.device_id)
    label = _clean_label(payload.label)
    ua_brand = _clean_label(payload.user_agent_brand)
    ip_prefix = ip_prefix_from(request)

    result = register_or_refresh(
        vault_id=vault_id,
        device_id=device_id,
        label=label,
        user_agent_brand=ua_brand,
        ip_prefix=ip_prefix,
    )

    return {
        "status": result["status"],
        "is_first_device": result["is_first_device"],
        "created": result["created"],
    }


@router.get("/devices/diagnose-trust")
async def diagnose_trust_endpoint(
    request: Request,
    principal=Depends(verify_session_token),
):


    vault_id = principal["vault_id"]
    sent_device_id = (request.headers.get("x-device-id") or "").strip()
    short = lambda s, n=8: (s[:n] if s and len(s) > n else (s or ""))

    print(
        f"[VAULT-DEBUG] /devices/diagnose-trust vault=...{str(vault_id)[-6:]} "
        f"sent_device_id_prefix={short(sent_device_id)!r}",
        flush=True,
    )

    rows = list_devices_for_vault(vault_id)
    current_row = None
    trusted_count = 0
    other_rows = []
    for r in rows:
        is_current = (
            sent_device_id != "" and r["device_id"] == sent_device_id
        )
        snapshot = {
            "device_id_prefix": short(r["device_id"]),
            "label": r.get("label"),
            "user_agent_brand": r.get("user_agent_brand"),
            "status": r.get("status"),
            "created_at":
                r["created_at"].isoformat() if r.get("created_at") else None,
            "last_seen_at":
                r["last_seen_at"].isoformat() if r.get("last_seen_at") else None,
            "approved_at":
                r["approved_at"].isoformat() if r.get("approved_at") else None,
            "revoked_at":
                r["revoked_at"].isoformat() if r.get("revoked_at") else None,
            "is_current": is_current,
        }
        if r.get("status") == "trusted":
            trusted_count += 1
        if is_current:
            current_row = snapshot
        else:
            other_rows.append(snapshot)

                                                                      
    if not sent_device_id:
        verdict = "missing_x_device_id_header"
    elif current_row is None:
        verdict = "device_id_not_in_db"                                      
    elif current_row["status"] == "trusted":
        verdict = "trusted_but_gate_rejected"                            
    elif current_row["status"] == "pending":
        if trusted_count == 0:
            verdict = "pending_auto_trust_should_fire"
        else:
            verdict = "pending_other_trusted_devices_exist"          
    elif current_row["status"] == "revoked":
        verdict = "revoked"
    else:
        verdict = "unknown_status_value"

    return {
        "verdict": verdict,
        "sent_device_id_prefix": short(sent_device_id),
        "sent_device_id_present": bool(sent_device_id),
        "current_device_row": current_row,
        "trusted_device_count": trusted_count,
        "auto_trust_guardrail_would_fire": (
            trusted_count == 0 and bool(sent_device_id)
        ),
        "other_devices": other_rows[:20],                        
        "other_devices_total": len(other_rows),
        "vault_id_tail": f"...{str(vault_id)[-6:]}",
    }


@router.post("/devices/dev/reset-trust-state")
async def dev_reset_trust_state(
    request: Request,
    principal=Depends(verify_session_token),
):


    if not is_dev_auto_trust_enabled():
                                                                     
                                                                      
        raise HTTPException(
            status_code=403,
            detail={
                "code": "dev_reset_disabled",
                "message": (
                    "Dev-only endpoint. Requires "
                    "VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST=true AND a dev "
                    "environment signal (VAULTAI_ENV=local etc.)."
                ),
            },
        )

    vault_id = principal["vault_id"]
    device_id = (request.headers.get("x-device-id") or "").strip()
    if not device_id:
                                                                       
                                                                       
        raise HTTPException(
            status_code=400,
            detail={
                "code": "missing_device_id",
                "message": (
                    "X-Device-Id header required so we know which "
                    "device to keep."
                ),
            },
        )
                                                                    
                                                     
    _validate_device_id(device_id)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

                                                                      
        cur.execute(
            """
            SELECT status, COUNT(*) AS n
              FROM trusted_devices
             WHERE vault_id = %s
             GROUP BY status;
            """,
            (vault_id,),
        )
        prior_counts = {row["status"]: int(row["n"]) for row in cur.fetchall()}

                                                                      
        cur.execute(
            """
            INSERT INTO trusted_devices
                (vault_id, device_id, status, approved_at, last_seen_at)
            VALUES (%s, %s, 'trusted', NOW(), NOW())
            ON CONFLICT (vault_id, device_id) DO UPDATE
                SET status        = 'trusted',
                    approved_at   = NOW(),
                    last_seen_at  = NOW();
            """,
            (vault_id, device_id),
        )

                                                             
        cur.execute(
            """
            DELETE FROM trusted_devices
             WHERE vault_id = %s
               AND device_id <> %s
            RETURNING device_id, status;
            """,
            (vault_id, device_id),
        )
        deleted_rows = cur.fetchall() or []
        conn.commit()
    finally:
        conn.close()

    short = lambda s, n=8: (s[:n] if s and len(s) > n else (s or ""))
    deleted_by_status: dict[str, int] = {}
    for row in deleted_rows:
        s = row["status"] or "unknown"
        deleted_by_status[s] = deleted_by_status.get(s, 0) + 1

    deleted_prefixes = [short(row["device_id"]) for row in deleted_rows][:20]

    logger.warning(
        "[VAULT-DEBUG] DEV_RESET_TRUST_STATE vault=%s kept=%s "
        "deleted_count=%d deleted_by_status=%s",
        str(vault_id)[-6:],
        short(device_id),
        len(deleted_rows),
        deleted_by_status,
    )
    print(
        f"[VAULT-DEBUG] DEV_RESET_TRUST_STATE "
        f"vault=...{str(vault_id)[-6:]} "
        f"kept_device={short(device_id)} "
        f"prior_counts={prior_counts} "
        f"deleted_count={len(deleted_rows)} "
        f"deleted_by_status={deleted_by_status} "
        f"deleted_prefixes={deleted_prefixes}",
        flush=True,
    )

    return {
        "kept_device_id_prefix":  short(device_id),
        "prior_counts_by_status": prior_counts,
        "deleted_count":          len(deleted_rows),
        "deleted_by_status":      deleted_by_status,
        "deleted_device_id_prefixes": deleted_prefixes,
    }


@router.post("/devices/dev/cleanup-pending")
async def dev_cleanup_pending_devices(
    request: Request,
    principal=Depends(verify_session_token),
):


    if not is_dev_auto_trust_enabled():
                                                                     
                                              
        raise HTTPException(
            status_code=403,
            detail={
                "code": "dev_cleanup_disabled",
                "message": (
                    "Dev-only endpoint. Set "
                    "VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST=true and a dev "
                    "environment signal (VAULTAI_ENV=local etc.) to enable."
                ),
            },
        )

    vault_id = principal["vault_id"]
    conn = get_db()
    try:
        cur = conn.cursor()
                                                                      
                                                                        
        cur.execute(
            """
            DELETE FROM trusted_devices
            WHERE vault_id = %s AND status = 'pending'
            RETURNING device_id
            """,
            (vault_id,),
        )
        deleted = cur.fetchall() or []
        conn.commit()
    finally:
        conn.close()

    short = lambda s, n=8: (s[:n] if s and len(s) > n else (s or ""))
    deleted_prefixes = [short(row[0]) for row in deleted]
    logger.warning(
        "[VAULT-DEBUG] DEV_CLEANUP_PENDING vault=%s deleted_count=%d",
        str(vault_id)[-6:], len(deleted),
    )
    print(
        f"[VAULT-DEBUG] DEV_CLEANUP_PENDING vault=...{str(vault_id)[-6:]} "
        f"deleted_count={len(deleted)} device_prefixes={deleted_prefixes}",
        flush=True,
    )
    return {
        "deleted_count": len(deleted),
        "deleted_device_id_prefixes": deleted_prefixes,
    }


@router.get("/devices/me")
async def list_devices_endpoint(
    request: Request,
    principal=Depends(verify_trusted_device),
):


    vault_id = principal["vault_id"]
    current_device_id = request.headers.get("x-device-id")

    rows = list_devices_for_vault(vault_id)
    devices = []
    for r in rows:
        devices.append({
            "device_id": r["device_id"],
            "label": r["label"],
            "user_agent_brand": r["user_agent_brand"],
            "last_ip_prefix": r["last_ip_prefix"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "approved_at": r["approved_at"].isoformat() if r["approved_at"] else None,
            "revoked_at": r["revoked_at"].isoformat() if r["revoked_at"] else None,
            "last_seen_at": r["last_seen_at"].isoformat() if r["last_seen_at"] else None,
            "is_current": current_device_id is not None and r["device_id"] == current_device_id,
        })

    return {"devices": devices, "current_device_id": current_device_id}


class TargetDeviceRequest(BaseModel):
    device_id: str


class SelfApprovalRequest(BaseModel):
    pin: str


class CancelSelfApprovalRequest(BaseModel):
                                                                      
                                                                 
    device_id: Optional[str] = None


def _label_for(row) -> str:

    if row.get("label"):
        return str(row["label"])
    if row.get("user_agent_brand"):
        return str(row["user_agent_brand"])
    return f"device {str(row.get('device_id', '?'))[:8]}"


@router.post("/devices/approve",
             dependencies=[Depends(verify_caller_is_trusted_device)])
async def approve_device_endpoint(
    payload: TargetDeviceRequest,
    request: Request,
    principal=Depends(verify_session_token),
):


    vault_id = principal["vault_id"]
    target_id = _validate_device_id(payload.device_id)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT device_id, status, label, user_agent_brand
            FROM trusted_devices
            WHERE vault_id = %s AND device_id = %s
            FOR UPDATE
            """,
            (vault_id, target_id),
        )
        target = cur.fetchone()
        if not target:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Device not found")

        if target["status"] == "trusted":
            conn.rollback()
            return {
                "status": "trusted",
                "device_id": target_id,
                "already_trusted": True,
            }

        if target["status"] == "revoked":
            conn.rollback()
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "cannot_approve_revoked_device",
                    "message": (
                        "Revoked devices cannot be re-approved. The user "
                        "must sign in on a different browser to start fresh."
                    ),
                },
            )

        cur.execute(
            """
            UPDATE trusted_devices
            SET status = 'trusted',
                approved_at = NOW(),
                cooldown_until = NULL,
                last_seen_at = NOW()
            WHERE vault_id = %s AND device_id = %s
            """,
            (vault_id, target_id),
        )
        conn.commit()
    finally:
        conn.close()

    _notify(
        vault_id, "device_approved",
        title="Device approved",
        body=f'You approved "{_label_for(target)}" on your account.',
        metadata={"device_id": target_id},
    )

    return {"status": "trusted", "device_id": target_id, "already_trusted": False}


@router.post("/devices/revoke",
             dependencies=[Depends(verify_caller_is_trusted_device)])
async def revoke_device_endpoint(
    payload: TargetDeviceRequest,
    request: Request,
    principal=Depends(verify_session_token),
):


    vault_id = principal["vault_id"]
    target_id = _validate_device_id(payload.device_id)
    caller_device_id = request.headers.get("x-device-id") or ""

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT device_id, status, label, user_agent_brand
            FROM trusted_devices
            WHERE vault_id = %s AND device_id = %s
            FOR UPDATE
            """,
            (vault_id, target_id),
        )
        target = cur.fetchone()
        if not target:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Device not found")

        if target["status"] == "revoked":
            conn.rollback()
            return {
                "status": "revoked",
                "device_id": target_id,
                "caller_revoked": caller_device_id == target_id,
                "already_revoked": True,
            }

        cur.execute(
            """
            UPDATE trusted_devices
            SET status = 'revoked',
                revoked_at = NOW(),
                cooldown_until = NULL
            WHERE vault_id = %s AND device_id = %s
            """,
            (vault_id, target_id),
        )
        conn.commit()
    finally:
        conn.close()

    _notify(
        vault_id, "device_revoked",
        title="Device revoked",
        body=f'You revoked "{_label_for(target)}".',
        metadata={"device_id": target_id},
    )

    return {
        "status": "revoked",
        "device_id": target_id,
        "caller_revoked": caller_device_id == target_id,
        "already_revoked": False,
    }


@router.post("/devices/request-self-approval")
async def request_self_approval_endpoint(
    payload: SelfApprovalRequest,
    request: Request,
    principal=Depends(verify_session_token),
):


    vault_id = principal["vault_id"]
    device_id = request.headers.get("x-device-id") or ""
    if not _DEVICE_ID_RE.match(device_id):
        raise HTTPException(
            status_code=400,
            detail="X-Device-Id header missing or malformed",
        )

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT status, cooldown_until, label, user_agent_brand
            FROM trusted_devices
            WHERE vault_id = %s AND device_id = %s
            FOR UPDATE
            """,
            (vault_id, device_id),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            raise HTTPException(
                status_code=404,
                detail="Device not registered. Call /devices/register first.",
            )

        if row["status"] == "trusted":
            conn.rollback()
            return {
                "status": "trusted",
                "device_id": device_id,
                "already_trusted": True,
            }

        if row["status"] == "revoked":
            conn.rollback()
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "cannot_self_approve_revoked_device",
                    "message": (
                        "This device was revoked. Sign in on a different "
                        "browser to start fresh."
                    ),
                    "device_id": device_id,
                    "status": "revoked",
                },
            )

                                                                          
        verify_vault_pin(vault_id, payload.pin)

                                                                    
        cur.execute("SELECT (NOW() AT TIME ZONE 'UTC') AS now")
        now = (cur.fetchone() or {}).get("now")
        existing_cooldown = row.get("cooldown_until")
        if existing_cooldown and now and existing_cooldown > now:
            conn.rollback()
            return {
                "status": "cooldown",
                "device_id": device_id,
                "cooldown_until": existing_cooldown.isoformat(),
                "cooldown_seconds": SELF_APPROVAL_COOLDOWN_SECONDS,
                "already_in_progress": True,
            }

        cur.execute(
            """
            UPDATE trusted_devices
            SET cooldown_until = NOW() + (INTERVAL '1 second' * %s)
            WHERE vault_id = %s AND device_id = %s
            RETURNING cooldown_until
            """,
            (SELF_APPROVAL_COOLDOWN_SECONDS, vault_id, device_id),
        )
        new_cooldown = (cur.fetchone() or {}).get("cooldown_until")
        conn.commit()
    finally:
        conn.close()

    _notify(
        vault_id, "device_approval_pending",
        title="Self-approval started on a new device",
        body=(
            f'A request to trust "{_label_for(row)}" was started. '
            f"It will activate after the cooldown unless cancelled."
        ),
        metadata={
            "device_id": device_id,
            "cooldown_until": new_cooldown.isoformat() if new_cooldown else None,
        },
    )

    return {
        "status": "cooldown",
        "device_id": device_id,
        "cooldown_until": new_cooldown.isoformat() if new_cooldown else None,
        "cooldown_seconds": SELF_APPROVAL_COOLDOWN_SECONDS,
        "already_in_progress": False,
    }


@router.post("/devices/finalize-self-approval")
async def finalize_self_approval_endpoint(
    payload: SelfApprovalRequest,
    request: Request,
    principal=Depends(verify_session_token),
):


    vault_id = principal["vault_id"]
    device_id = request.headers.get("x-device-id") or ""
    if not _DEVICE_ID_RE.match(device_id):
        raise HTTPException(
            status_code=400,
            detail="X-Device-Id header missing or malformed",
        )

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT status, cooldown_until, label, user_agent_brand
            FROM trusted_devices
            WHERE vault_id = %s AND device_id = %s
            FOR UPDATE
            """,
            (vault_id, device_id),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Device not registered")

        if row["status"] == "trusted":
                                                                 
            conn.rollback()
            return {
                "status": "trusted",
                "device_id": device_id,
                "already_trusted": True,
            }

        if row["status"] == "revoked":
            conn.rollback()
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "cannot_self_approve_revoked_device",
                    "message": "Device was revoked.",
                    "device_id": device_id,
                    "status": "revoked",
                },
            )

                                                                       
        verify_vault_pin(vault_id, payload.pin)

        cooldown = row.get("cooldown_until")
        if cooldown is None:
            conn.rollback()
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "no_self_approval_in_progress",
                    "message": (
                        "No self-approval is in progress. Start one via "
                        "/devices/request-self-approval."
                    ),
                },
            )

                                                                        
        cur.execute("SELECT (NOW() AT TIME ZONE 'UTC') AS now")
        now = (cur.fetchone() or {}).get("now")
        if now and cooldown > now:
            seconds_remaining = int((cooldown - now).total_seconds())
            conn.rollback()
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "cooldown_not_elapsed",
                    "message": (
                        f"Cooldown not elapsed; {seconds_remaining}s remaining."
                    ),
                    "cooldown_until": cooldown.isoformat(),
                    "seconds_remaining": seconds_remaining,
                },
            )

        cur.execute(
            """
            UPDATE trusted_devices
            SET status = 'trusted',
                approved_at = NOW(),
                cooldown_until = NULL,
                last_seen_at = NOW()
            WHERE vault_id = %s AND device_id = %s
            """,
            (vault_id, device_id),
        )
        conn.commit()
    finally:
        conn.close()

    _notify(
        vault_id, "device_approved",
        title="Device approved",
        body=f'"{_label_for(row)}" was approved via self-approval (PIN + cooldown).',
        metadata={"device_id": device_id, "via": "self_approval"},
    )

    return {
        "status": "trusted",
        "device_id": device_id,
        "already_trusted": False,
    }


@router.post("/devices/cancel-self-approval")
async def cancel_self_approval_endpoint(
    payload: CancelSelfApprovalRequest,
    request: Request,
    principal=Depends(verify_session_token),
):


    vault_id = principal["vault_id"]
    caller_device_id = request.headers.get("x-device-id") or ""

    target_id = (payload.device_id or "").strip() or caller_device_id
    if not _DEVICE_ID_RE.match(target_id):
        raise HTTPException(status_code=400, detail="device_id required")

                                                                        
    if target_id != caller_device_id:
        from device_gate import _lookup_device_status
        caller_status = _lookup_device_status(vault_id, caller_device_id)
        if caller_status != "trusted":
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "device_must_be_trusted_to_approve",
                    "message": (
                        "Only a trusted device can cancel another device's "
                        "self-approval."
                    ),
                },
            )

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            UPDATE trusted_devices
            SET cooldown_until = NULL
            WHERE vault_id = %s AND device_id = %s
            RETURNING device_id, label, user_agent_brand
            """,
            (vault_id, target_id),
        )
        row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Device not found")

    _notify(
        vault_id, "device_self_approval_cancelled",
        title="Self-approval cancelled",
        body=f'Self-approval for "{_label_for(row)}" was cancelled.',
        metadata={"device_id": target_id},
    )

    return {"status": "cancelled", "device_id": target_id}
