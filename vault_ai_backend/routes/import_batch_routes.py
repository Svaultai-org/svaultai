

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from device_gate import verify_trusted_device
from vault_core import get_db, verify_vault_pin                                          


logger = logging.getLogger(__name__)
router = APIRouter()


class ImportBatchStartRequest(BaseModel):
    vault_name: str                                                  
    pin: Optional[str] = Field(default=None, min_length=1, max_length=64)

                                                                     
    root_folder_name: Optional[str] = None

                                                                  
    total_files: int = 0
    total_bytes_planned: int = 0


class ImportBatchActionRequest(BaseModel):
    vault_name: str                                                  
    pin: Optional[str] = Field(default=None, min_length=1, max_length=64)

                                                                    
    failed_count_delta: int = 0
    skipped_duplicate_count_delta: int = 0


class ImportBatchSessionStartRequest(BaseModel):
    """PIN-free import bookkeeping; no vault or folder name crosses the wire."""

    model_config = ConfigDict(extra="forbid")
    total_files: int = Field(default=0, ge=0)
    total_bytes_planned: int = Field(default=0, ge=0)


class ImportBatchSessionActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    failed_count_delta: int = Field(default=0, ge=0)
    skipped_duplicate_count_delta: int = Field(default=0, ge=0)


def _require_zk_import_session(vault_id: str) -> None:
    from vault_core import is_vault_zk_adopted

    if (
        os.getenv("VAULTAI_ZK_IMPORT_SESSION_ACTIONS_ENABLED", "false")
        .strip().lower() != "true"
        or not is_vault_zk_adopted(vault_id)
    ):
        raise HTTPException(status_code=404, detail="not_found")


def _authorize_import_batch_action(principal: dict, pin: Optional[str]) -> bool:
    """Return whether this is a PIN-free, trusted-device ZK action."""
    vault_id = principal["vault_id"]
    if os.getenv("VAULTAI_ZK_IMPORT_SESSION_ACTIONS_ENABLED", "false").strip().lower() == "true":
        from vault_core import is_vault_zk_adopted

        if is_vault_zk_adopted(vault_id):
            if pin is not None:
                raise HTTPException(409, detail="zk_client_update_required")
            return True
    if not pin:
        raise HTTPException(400, detail="pin_required")
    verify_vault_pin(vault_id, pin)
    return False


@router.post("/imports/start")
async def start_import_endpoint(
    payload: ImportBatchStartRequest,
    principal=Depends(verify_trusted_device),
):
                                                                     
                                                                  
    from main import start_import_batch

    vault_id = principal["vault_id"]
    zk_session_only = _authorize_import_batch_action(principal, payload.pin)
    if zk_session_only and payload.root_folder_name is not None:
        raise HTTPException(409, detail="zk_plaintext_folder_name_not_supported")

    batch = start_import_batch(
        vault_id=vault_id,
        root_folder_name=payload.root_folder_name,
        total_files=payload.total_files,
        total_bytes_planned=payload.total_bytes_planned,
    )
    return batch


@router.get("/imports/{import_id}")
async def get_import_endpoint(
    import_id: str,
    principal=Depends(verify_trusted_device),
):
    from main import get_import_batch

    vault_id = principal["vault_id"]
    batch = get_import_batch(vault_id=vault_id, import_id=import_id)
    if batch is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "import_batch_not_found",
                "message": "Import batch not found for this vault.",
            },
        )
    return batch


@router.post("/imports/{import_id}/cancel")
async def cancel_import_endpoint(
    import_id: str,
    payload: ImportBatchActionRequest,
    principal=Depends(verify_trusted_device),
):
    from main import cancel_import_batch

    vault_id = principal["vault_id"]
    _authorize_import_batch_action(principal, payload.pin)

    return cancel_import_batch(
        vault_id=vault_id,
        import_id=import_id,
    )


@router.post("/imports/{import_id}/complete")
async def complete_import_endpoint(
    import_id: str,
    payload: ImportBatchActionRequest,
    principal=Depends(verify_trusted_device),
):
    from main import complete_import_batch

    vault_id = principal["vault_id"]
    _authorize_import_batch_action(principal, payload.pin)

    return complete_import_batch(
        vault_id=vault_id,
        import_id=import_id,
        failed_count_delta=payload.failed_count_delta,
        skipped_duplicate_count_delta=payload.skipped_duplicate_count_delta,
    )


@router.post("/imports/session/start")
async def start_import_session_endpoint(
    payload: ImportBatchSessionStartRequest,
    principal=Depends(verify_trusted_device),
):
    _require_zk_import_session(principal["vault_id"])
    return await start_import_endpoint(
        ImportBatchStartRequest(
            vault_name="",
            total_files=payload.total_files,
            total_bytes_planned=payload.total_bytes_planned,
        ),
        principal,
    )


@router.post("/imports/session/{import_id}/cancel")
async def cancel_import_session_endpoint(
    import_id: str,
    payload: ImportBatchSessionActionRequest,
    principal=Depends(verify_trusted_device),
):
    _require_zk_import_session(principal["vault_id"])
    return await cancel_import_endpoint(
        import_id, ImportBatchActionRequest(vault_name=""), principal,
    )


@router.post("/imports/session/{import_id}/complete")
async def complete_import_session_endpoint(
    import_id: str,
    payload: ImportBatchSessionActionRequest,
    principal=Depends(verify_trusted_device),
):
    _require_zk_import_session(principal["vault_id"])
    return await complete_import_endpoint(
        import_id,
        ImportBatchActionRequest(
            vault_name="",
            failed_count_delta=payload.failed_count_delta,
            skipped_duplicate_count_delta=payload.skipped_duplicate_count_delta,
        ),
        principal,
    )
