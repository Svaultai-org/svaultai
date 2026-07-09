

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from device_gate import verify_trusted_device
from vault_core import get_db, verify_vault_pin                                          


logger = logging.getLogger(__name__)
router = APIRouter()


class ImportBatchStartRequest(BaseModel):
    vault_name: str                                                  
    pin: str

                                                                     
    root_folder_name: Optional[str] = None

                                                                  
    total_files: int = 0
    total_bytes_planned: int = 0


class ImportBatchActionRequest(BaseModel):
    vault_name: str                                                  
    pin: str

                                                                    
    failed_count_delta: int = 0
    skipped_duplicate_count_delta: int = 0


@router.post("/imports/start")
async def start_import_endpoint(
    payload: ImportBatchStartRequest,
    principal=Depends(verify_trusted_device),
):
                                                                     
                                                                  
    from main import start_import_batch

    vault_id = principal["vault_id"]
    verify_vault_pin(vault_id, payload.pin)

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
    verify_vault_pin(vault_id, payload.pin)

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
    verify_vault_pin(vault_id, payload.pin)

    return complete_import_batch(
        vault_id=vault_id,
        import_id=import_id,
        failed_count_delta=payload.failed_count_delta,
        skipped_duplicate_count_delta=payload.skipped_duplicate_count_delta,
    )
