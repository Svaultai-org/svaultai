

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends

from device_gate import verify_trusted_device


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/folders")
async def list_folder_endpoint(
    path: Optional[str] = None,
    principal=Depends(verify_trusted_device),
):


    from main import build_folder_tree

    vault_id = principal["vault_id"]
    return build_folder_tree(vault_id=vault_id, path=path)
