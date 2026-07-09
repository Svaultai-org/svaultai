

from __future__ import annotations

import json
import logging
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from device_gate import verify_trusted_device
from password_audit import (
    WEAK_THRESHOLD,
    MODERATE_THRESHOLD,
    band_for,
    hash_password,
    score_password,
)
from vault_core import (
    MAX_VAULT_BYTES,
    decrypt_message,
    get_db,
    verify_vault_pin,
)


logger = logging.getLogger(__name__)
router = APIRouter()


INACTIVE_TRUSTED_DAYS = 90
MODERN_KDF_THRESHOLD = 600_000
RATE_PER_MIN = int(os.getenv("VAULTAI_SECURITY_CENTER_RATE_PER_MIN", "30"))


_rate: "OrderedDict[str, list[float]]" = OrderedDict()


def _is_enabled() -> bool:

    return os.getenv("VAULTAI_SECURITY_CENTER_ENABLED", "true").lower() == "true"


def _effective_storage_limit_for_vault(vault_id: str) -> int:


    try:
        from billing import (
            get_account_id_for_vault, get_effective_storage_limit,
        )
        return int(get_effective_storage_limit(
            get_account_id_for_vault(vault_id),
        ))
    except Exception:
                                                              
        return int(MAX_VAULT_BYTES)


def _rate_limit(vault_id: str) -> None:
    now = time.time()
    window = [t for t in _rate.get(vault_id, []) if now - t < 60.0]
    if len(window) >= RATE_PER_MIN:
        raise HTTPException(
            status_code=429,
            detail="Security Center rate limit exceeded. Try again shortly.",
        )
    window.append(now)
    _rate[vault_id] = window
    if len(_rate) > 4096:
        _rate.popitem(last=False)


def _build_score(
    *,
    has_trusted: bool,
    no_pending: bool,
    all_active: bool,
    no_pending_self_approval: bool,
    modern_kdf: bool,
    inheritance_configured: bool,
    audited_count: int,
    strong_count: int,
    generated_count: int,
    has_reuse: bool,
) -> int:


    s = 0
    if has_trusted:
        s += 15
    if no_pending:
        s += 5
    if all_active:
        s += 5
    if no_pending_self_approval:
        s += 5
    if modern_kdf:
        s += 15
    if inheritance_configured:
        s += 10
    if audited_count == 0:
        s += 25 + 10 + 10                           
    else:
        s += int(round(25 * (strong_count / audited_count)))
        s += int(round(10 * (generated_count / audited_count)))
        if not has_reuse:
            s += 10
    return max(0, min(s, 100))


def _build_recommendations(
    *,
    weak_count: int,
    pending_devices: int,
    inactive_trusted: int,
    pending_self_approval: int,
    inheritance_configured: bool,
    unanalyzed_count: int,
) -> list[dict]:
    recs: list[dict] = []
    if weak_count > 0:
        recs.append({
            "id": "weak_passwords",
            "priority": "high",
            "message": (
                f"Replace {weak_count} weak password"
                f"{'s' if weak_count != 1 else ''}."
            ),
            "route": None,
        })
    if pending_devices > 0:
        recs.append({
            "id": "pending_device",
            "priority": "high",
            "message": (
                f"Finish {pending_devices} pending device approval"
                f"{'s' if pending_devices != 1 else ''}."
            ),
            "route": "/devices",
        })
    if pending_self_approval > 0:
        recs.append({
            "id": "pending_self_approval",
            "priority": "high",
            "message": "Pending self-approval cooldown in progress.",
            "route": "/devices",
        })
    if inactive_trusted > 0:
        recs.append({
            "id": "inactive_devices",
            "priority": "moderate",
            "message": (
                f"Review {inactive_trusted} inactive trusted device"
                f"{'s' if inactive_trusted != 1 else ''}."
            ),
            "route": "/devices",
        })
    if not inheritance_configured:
        recs.append({
            "id": "enable_inheritance",
            "priority": "low",
            "message": "Enable inheritance pairing.",
            "route": None,
        })
    if unanalyzed_count > 0:
        recs.append({
            "id": "unanalyzed_passwords",
            "priority": "low",
            "message": (
                f"{unanalyzed_count} password"
                f"{'s' if unanalyzed_count != 1 else ''} not yet analyzed. "
                "They'll be scored as you save or view them."
            ),
            "route": None,
        })
    return recs


def _empty_security_center_summary(vault_id: Optional[str] = None) -> dict:


    storage_limit = (
        _effective_storage_limit_for_vault(vault_id) if vault_id
        else int(MAX_VAULT_BYTES)
    )
    return {
        "score": 0,
        "score_band": "starting",
        "devices": {"trusted": 0, "pending": 0, "revoked": 0,
                    "inactive_trusted": 0, "pending_self_approval": 0},
        "passwords": {"audited_count": 0, "unanalyzed_count": 0,
                      "weak": 0, "moderate": 0, "strong": 0,
                      "reused": 0, "generated_by_vaultai": 0},
        "vault": {"total_items": 0, "total_files": 0, "tag_counts": {}},
        "storage": {
            "used_bytes": 0,
            "limit_bytes": storage_limit,
            "pending_bytes": 0,
        },
        "encryption": {"kdf_iterations": 0, "kdf_strength": "unknown",
                       "chunked_upload_enabled": False,
                       "semantic_search_enabled": False},
        "inheritance": {"configured": False, "frozen": False,
                        "vault_frozen_until": None},
        "recommendations": [],
        "engine": "empty",
    }


@router.get("/security-center/summary")
async def security_center_summary(
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    print(
        f"[VAULT-DEBUG] /security-center/summary ENTRY vault=...{str(vault_id)[-6:]}",
        flush=True,
    )
    if not _is_enabled():
                                                                    
                                                                    
        return _empty_security_center_summary(vault_id)
    try:
        return await _security_center_summary_inner(vault_id)
    except HTTPException:
        raise
    except Exception as exc:
                                                                      
                                                                      
        print(
            f"[VAULT-DEBUG] /security-center/summary DEGRADED "
            f"error_type={type(exc).__name__} repr={exc!r}",
            flush=True,
        )
        import traceback as _tb
        print(_tb.format_exc(), flush=True)
        return _empty_security_center_summary(vault_id)


async def _security_center_summary_inner(vault_id: str) -> dict:
    _rate_limit(vault_id)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

                                                                           
        cur.execute(
            f"""
            SELECT
              COUNT(*) FILTER (WHERE status='trusted')                            AS trusted,
              COUNT(*) FILTER (WHERE status='pending')                            AS pending,
              COUNT(*) FILTER (WHERE status='revoked')                            AS revoked,
              COUNT(*) FILTER (WHERE status='trusted'
                               AND last_seen_at <
                                   (NOW() AT TIME ZONE 'UTC')
                                   - INTERVAL '{INACTIVE_TRUSTED_DAYS} days')    AS inactive_trusted,
              COUNT(*) FILTER (WHERE cooldown_until IS NOT NULL
                               AND cooldown_until >
                                   (NOW() AT TIME ZONE 'UTC'))                   AS pending_self_approval
            FROM trusted_devices WHERE vault_id = %s
            """,
            (vault_id,),
        )
        d = cur.fetchone() or {}

                                                                     
        cur.execute(
            """
            SELECT password_strength_score, generated_by_vaultai
            FROM vault_password_audit WHERE vault_id = %s
            """,
            (vault_id,),
        )
        rows = cur.fetchall() or []
        audited = len(rows)
        weak = sum(1 for r in rows
                   if r["password_strength_score"] < WEAK_THRESHOLD)
        moderate = sum(1 for r in rows
                       if WEAK_THRESHOLD <= r["password_strength_score"]
                       < MODERATE_THRESHOLD)
        strong = sum(1 for r in rows
                     if r["password_strength_score"] >= MODERATE_THRESHOLD)
        generated = sum(1 for r in rows if r["generated_by_vaultai"])

                                               
        cur.execute(
            """
            SELECT COUNT(*) AS n FROM (
              SELECT 1 FROM vault_password_audit
              WHERE vault_id = %s
              GROUP BY password_hash_sha256
              HAVING COUNT(*) > 1
            ) s
            """,
            (vault_id,),
        )
        reused_groups = int((cur.fetchone() or {"n": 0})["n"])

                                                          
        cur.execute(
            """
            SELECT item_type, COUNT(*) AS n
            FROM vault_items WHERE vault_id = %s
            GROUP BY item_type
            """,
            (vault_id,),
        )
        type_counts = {r["item_type"]: int(r["n"])
                       for r in (cur.fetchall() or [])}
        audit_eligible = type_counts.get("login", 0) + type_counts.get("bank", 0)
        unanalyzed = max(0, audit_eligible - audited)
        total_items = sum(type_counts.values())

                                                               
        cur.execute(
            """
            SELECT COUNT(*) AS n FROM uploaded_files
            WHERE vault_id = %s AND upload_status = 'complete'
            """,
            (vault_id,),
        )
        total_files = int((cur.fetchone() or {"n": 0})["n"])

                               
        cur.execute(
            """
            SELECT tag, COUNT(*) AS n FROM vault_asset_tags
            WHERE vault_id = %s GROUP BY tag
            """,
            (vault_id,),
        )
        tag_counts = {r["tag"]: int(r["n"])
                      for r in (cur.fetchall() or [])}

                                                                       
        cur.execute(
            """
            SELECT kdf_iterations, total_bytes, frozen_until
            FROM vaults WHERE vault_id = %s LIMIT 1
            """,
            (vault_id,),
        )
        vn = cur.fetchone() or {}
        kdf_iter = int(vn.get("kdf_iterations") or 0)
        kdf_strength = "modern" if kdf_iter >= MODERN_KDF_THRESHOLD else "legacy"
        used_bytes = int(vn.get("total_bytes") or 0)
        frozen_until = vn.get("frozen_until")

                                          
        cur.execute(
            """
            SELECT COALESCE(SUM(file_size), 0) AS n FROM uploaded_files
            WHERE vault_id = %s AND upload_status = 'uploading'
            """,
            (vault_id,),
        )
        pending_bytes = int((cur.fetchone() or {"n": 0})["n"])

                                                                              
        cur.execute(
            """
            SELECT COUNT(*) AS n FROM beneficiary_links
            WHERE passer_vault_id = %s
              AND status NOT IN ('cancelled', 'transferred')
            """,
            (vault_id,),
        )
        inheritance_configured = int((cur.fetchone() or {"n": 0})["n"]) > 0
    finally:
        conn.close()

    has_trusted = int(d.get("trusted", 0)) > 0
    no_pending = int(d.get("pending", 0)) == 0
    all_active = int(d.get("inactive_trusted", 0)) == 0
    no_pending_self_approval = int(d.get("pending_self_approval", 0)) == 0
    modern_kdf = kdf_iter >= MODERN_KDF_THRESHOLD
    has_reuse = reused_groups > 0

    score = _build_score(
        has_trusted=has_trusted,
        no_pending=no_pending,
        all_active=all_active,
        no_pending_self_approval=no_pending_self_approval,
        modern_kdf=modern_kdf,
        inheritance_configured=inheritance_configured,
        audited_count=audited,
        strong_count=strong,
        generated_count=generated,
        has_reuse=has_reuse,
    )

    recs = _build_recommendations(
        weak_count=weak,
        pending_devices=int(d.get("pending", 0)),
        inactive_trusted=int(d.get("inactive_trusted", 0)),
        pending_self_approval=int(d.get("pending_self_approval", 0)),
        inheritance_configured=inheritance_configured,
        unanalyzed_count=unanalyzed,
    )

                                                                       
    return {
        "score": score,
        "score_band": band_for(score),
        "devices": {
            "trusted": int(d.get("trusted", 0)),
            "pending": int(d.get("pending", 0)),
            "revoked": int(d.get("revoked", 0)),
            "inactive_trusted": int(d.get("inactive_trusted", 0)),
            "pending_self_approval": int(d.get("pending_self_approval", 0)),
        },
        "passwords": {
            "audited_count": audited,
            "unanalyzed_count": unanalyzed,
            "weak": weak,
            "moderate": moderate,
            "strong": strong,
            "reused": reused_groups,
            "generated_by_vaultai": generated,
        },
        "vault": {
            "total_items": total_items,
            "total_files": total_files,
            "tag_counts": tag_counts,
        },
                                                                   
                                                                      
        "storage": {
            "used_bytes": used_bytes,
            "limit_bytes": _effective_storage_limit_for_vault(vault_id),
            "pending_bytes": pending_bytes,
        },
        "encryption": {
            "kdf_iterations": kdf_iter,
            "kdf_strength": kdf_strength,
            "chunked_upload_enabled":
                os.getenv("VAULTAI_CHUNKED_UPLOADS", "false").lower() == "true",
            "semantic_search_enabled":
                os.getenv("VAULTAI_SEMANTIC_SEARCH_ENABLED", "false").lower() == "true",
        },
        "inheritance": {
            "configured": inheritance_configured,
            "frozen": frozen_until is not None,
            "vault_frozen_until": frozen_until.isoformat() if frozen_until else None,
        },
        "recommendations": recs,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


ANALYZE_MAX_LIMIT = 500
ANALYZE_RATE_PER_HOUR = 5

                                                                        
_analyze_rate: "OrderedDict[str, list[float]]" = OrderedDict()


def _analyze_rate_limit(vault_id: str) -> None:
    now = time.time()
    window = [t for t in _analyze_rate.get(vault_id, []) if now - t < 3600.0]
    if len(window) >= ANALYZE_RATE_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Analyze-passwords rate limit ({ANALYZE_RATE_PER_HOUR}/hour) "
                "exceeded. Try again later."
            ),
        )
    window.append(now)
    _analyze_rate[vault_id] = window
    if len(_analyze_rate) > 4096:
        _analyze_rate.popitem(last=False)


class AnalyzePasswordsRequest(BaseModel):
    pin: str = Field(..., min_length=1, max_length=200)
    cursor: Optional[int] = None
    limit: Optional[int] = None


@router.post("/security-center/analyze-passwords")
async def analyze_passwords(
    req: AnalyzePasswordsRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    if not _is_enabled():
        raise HTTPException(
            status_code=503,
            detail="Security Center is disabled on this server.",
        )
    _analyze_rate_limit(vault_id)

                                                                  
    key = verify_vault_pin(vault_id, req.pin)

    requested = req.limit if req.limit is not None else ANALYZE_MAX_LIMIT
    limit = max(1, min(requested, ANALYZE_MAX_LIMIT))
    cursor = req.cursor if req.cursor is not None else 0

    analyzed = 0
    skipped = 0
    failed = 0
    weak = 0
    moderate = 0
    strong = 0
    last_id = cursor

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
                                                                          
                                                                        
        cur.execute(
            """
            SELECT id, encrypted_data, item_type
            FROM vault_items
            WHERE vault_id = %s
              AND item_type IN ('login', 'bank')
              AND id > %s
            ORDER BY id ASC
            LIMIT %s
            """,
            (vault_id, cursor, limit + 1),
        )
        rows = cur.fetchall() or []
        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        for row in rows:
            last_id = row["id"]
            try:
                pt = decrypt_message(row["encrypted_data"], key)
                fields = json.loads(pt)
            except Exception:
                                                                    
                failed += 1
                continue

            if not isinstance(fields, dict):
                skipped += 1
                continue
            pw = fields.get("password")
            if not pw:
                skipped += 1
                continue

            try:
                h = hash_password(vault_id, pw)
                s = score_password(pw)
                with conn.cursor() as wcur:
                                                                           
                                                           
                    wcur.execute(
                        """
                        INSERT INTO vault_password_audit
                            (vault_id, vault_item_id, password_hash_sha256,
                             password_strength_score, generated_by_vaultai)
                        VALUES (%s, %s, %s, %s, FALSE)
                        ON CONFLICT (vault_id, vault_item_id) DO UPDATE SET
                            password_hash_sha256    = EXCLUDED.password_hash_sha256,
                            password_strength_score = EXCLUDED.password_strength_score,
                            generated_by_vaultai    = vault_password_audit.generated_by_vaultai
                                                      OR EXCLUDED.generated_by_vaultai,
                            updated_at              = NOW()
                        """,
                        (vault_id, row["id"], h, s),
                    )
                conn.commit()                                         
                analyzed += 1
                if s < WEAK_THRESHOLD:
                    weak += 1
                elif s < MODERATE_THRESHOLD:
                    moderate += 1
                else:
                    strong += 1
            except Exception as e:
                logger.warning(
                    "analyze-passwords upsert failed vault=%s item=%s: %s",
                    vault_id, row["id"], e,
                )
                try:
                    conn.rollback()
                except Exception:
                    pass
                failed += 1
                continue

                                                                         
        cur.execute(
            """
            SELECT COUNT(*) AS n FROM (
              SELECT 1 FROM vault_password_audit
              WHERE vault_id = %s
              GROUP BY password_hash_sha256
              HAVING COUNT(*) > 1
            ) s
            """,
            (vault_id,),
        )
        reused_groups = int((cur.fetchone() or {"n": 0})["n"])
    finally:
        conn.close()

                                                             
    return {
        "analyzed_count": analyzed,
        "skipped_count": skipped,
        "failed_count": failed,
        "weak": weak,
        "moderate": moderate,
        "strong": strong,
        "reused": reused_groups,
        "has_more": has_more,
        "next_cursor": last_id if has_more else None,
    }
