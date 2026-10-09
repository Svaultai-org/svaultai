"""Authenticated, consented exposure checks and opaque local-state sync."""
from __future__ import annotations

import base64
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from psycopg2.extras import RealDictCursor

import concierge_exposure as exposure
from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from vault_core import get_db

router = APIRouter(prefix="/concierge", tags=["concierge"])


class EmailRangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prefix: str = Field(pattern=r"^[0-9A-Fa-f]{6}$")
    consent_version: str
    prefix_disclosure_consent: bool


class MonitorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    source_item_id: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    consent_version: str
    email_disclosure_consent: bool
    background: bool
    stealer_logs: bool = False
    stealer_disclosure_consent: bool = False

    @model_validator(mode="after")
    def require_consent(self):
        if (self.consent_version != exposure.CONSENT_VERSION or not self.email_disclosure_consent
                or not self.background or (self.stealer_logs and not self.stealer_disclosure_consent)):
            raise ValueError("separate_current_monitoring_consent_required")
        self.email = exposure.normalize_email(self.email)
        return self


class OpaqueStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ciphertext: str = Field(min_length=39, max_length=273072)
    envelope_version: str = Field(pattern=r"^v1$")
    expected_revision: int = Field(ge=0, le=2147483646)


def _require_enabled() -> exposure.Settings:
    settings = exposure.Settings.from_environment()
    if not settings.enabled:
        raise HTTPException(404, detail={"code": "concierge_disabled"})
    return settings


def _provider_http_error(exc: exposure.ProviderError) -> HTTPException:
    status = 429 if exc.code in ("concierge_rate_limited", "monitor_check_rate_limited", "monitor_check_in_progress") else 503
    return HTTPException(status, detail={"code": exc.code, "retry_after_seconds": exc.retry_after_seconds})


@router.get("/capabilities")
def get_capabilities(principal: SessionPrincipal = Depends(verify_trusted_device)):
    return exposure.capabilities()


@router.post("/email-range")
def email_range(payload: EmailRangeRequest, principal: SessionPrincipal = Depends(verify_trusted_device)):
    settings = _require_enabled()
    if payload.consent_version != exposure.CONSENT_VERSION or not payload.prefix_disclosure_consent:
        raise HTTPException(400, detail={"code": "prefix_consent_required"})
    attempted = exposure.now_utc()
    try:
        exposure.consume_vault_budget(principal["vault_id"])
        exposure.require_capability(exposure.capabilities(settings), "email_range")
        rows = exposure.HibpProvider(settings, allow_rate_wait=True).email_range(payload.prefix)
        return {"status": "checked", "rows": rows, "provider": "hibp", "attempted_at": attempted,
                "successful_at": exposure.now_utc(), "coverage": exposure.COVERAGE,
                "attribution_url": exposure.ATTRIBUTION_URL}
    except exposure.ProviderError as exc:
        return {**exposure.unavailable(exc, attempted_at=attempted), "rows": []}


@router.get("/breaches/{name}")
def breach_metadata(name: str, principal: SessionPrincipal = Depends(verify_trusted_device)):
    settings = _require_enabled()
    attempted = exposure.now_utc()
    try:
        exposure.consume_vault_budget(principal["vault_id"])
        value = exposure.HibpProvider(settings, allow_rate_wait=True).breach(name)
        return {"status": "checked", "breach": value, "provider": "hibp", "attempted_at": attempted,
                "successful_at": exposure.now_utc(), "attribution_url": exposure.ATTRIBUTION_URL}
    except ValueError:
        raise HTTPException(400, detail={"code": "invalid_breach_name"}) from None
    except exposure.ProviderError as exc:
        return {**exposure.unavailable(exc, attempted_at=attempted), "breach": None}


@router.post("/monitors", status_code=201)
def create_monitor(payload: MonitorRequest, principal: SessionPrincipal = Depends(verify_trusted_device)):
    settings = _require_enabled()
    try:
        exposure.consume_vault_budget(principal["vault_id"])
        return exposure.create_monitor(principal["vault_id"], payload.email, payload.source_item_id,
                                       stealer_logs=payload.stealer_logs, settings=settings)
    except ValueError as exc:
        # Value errors here are constant validation codes, not provider responses.
        raise HTTPException(400, detail={"code": str(exc)}) from None
    except exposure.ProviderError as exc:
        raise _provider_http_error(exc) from None


@router.get("/monitors")
def get_monitors(principal: SessionPrincipal = Depends(verify_trusted_device)):
    # Reading/withdrawal remain possible when new monitoring is disabled.
    return {"monitors": exposure.list_monitors(principal["vault_id"]), "capabilities": exposure.capabilities()}


@router.post("/monitors/{monitor_id}/check")
def check_monitor(monitor_id: UUID, principal: SessionPrincipal = Depends(verify_trusted_device)):
    settings = _require_enabled()
    try:
        exposure.consume_vault_budget(principal["vault_id"])
        claim = exposure.claim_monitor(vault_id=principal["vault_id"], monitor_id=str(monitor_id))
        if claim is None:
            raise HTTPException(404, detail={"code": "monitor_not_found"})
        result = exposure.perform_monitor_check(*claim, settings=settings)
        if result is None:
            raise HTTPException(409, detail={"code": "monitor_check_no_longer_current"})
        return result
    except exposure.ProviderError as exc:
        raise _provider_http_error(exc) from None


@router.delete("/monitors/{monitor_id}")
def withdraw_monitor(monitor_id: UUID, principal: SessionPrincipal = Depends(verify_trusted_device)):
    if not exposure.delete_monitor(principal["vault_id"], str(monitor_id)):
        raise HTTPException(404, detail={"code": "monitor_not_found"})
    return {"status": "withdrawn", "id": str(monitor_id)}


@router.get("/state")
def get_state(principal: SessionPrincipal = Depends(verify_trusted_device)):
    conn = exposure.open_db(get_db)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT ciphertext,revision,envelope_version,updated_at FROM concierge_client_state WHERE vault_id=%s",
                    (principal["vault_id"],))
        row = cur.fetchone()
        if not row:
            return {"ciphertext": None, "revision": 0, "envelope_version": "v1", "updated_at": None}
        return {"ciphertext": base64.urlsafe_b64encode(bytes(row["ciphertext"])).decode().rstrip("="),
                "revision": row["revision"], "envelope_version": row["envelope_version"], "updated_at": row["updated_at"]}
    finally:
        conn.close()


@router.put("/state")
def put_state(payload: OpaqueStateRequest, principal: SessionPrincipal = Depends(verify_trusted_device)):
    _require_enabled()
    try:
        ciphertext = exposure.decode_b64(payload.ciphertext, max_bytes=exposure.MAX_STATE_BYTES)
        if len(ciphertext) < 29:
            raise ValueError("ciphertext_too_short")
    except ValueError as exc:
        raise HTTPException(400, detail={"code": str(exc)}) from None
    conn = exposure.open_db(get_db)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Parent lock serializes initial creation and owner account deletion.
        cur.execute("SELECT vault_id FROM vaults WHERE vault_id=%s FOR UPDATE", (principal["vault_id"],))
        if not cur.fetchone():
            raise HTTPException(404, detail={"code": "vault_unavailable"})
        cur.execute("SELECT revision FROM concierge_client_state WHERE vault_id=%s FOR UPDATE", (principal["vault_id"],))
        current = cur.fetchone()
        revision = current["revision"] if current else 0
        if revision != payload.expected_revision:
            raise HTTPException(409, detail={"code": "concierge_state_conflict"})
        cur.execute("""INSERT INTO concierge_client_state(vault_id,ciphertext,revision,envelope_version)
          VALUES(%s,%s,%s,'v1') ON CONFLICT(vault_id) DO UPDATE
          SET ciphertext=EXCLUDED.ciphertext,revision=EXCLUDED.revision,updated_at=NOW()
          RETURNING revision,envelope_version,updated_at""", (principal["vault_id"], ciphertext, revision + 1))
        result = dict(cur.fetchone())
        conn.commit()
        return result
    finally:
        conn.close()
