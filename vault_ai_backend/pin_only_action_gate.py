"""Authorization for actions that use a PIN only as a recheck.

Callers must not use this helper when they need a PIN-derived key to decrypt,
encrypt, or rotate legacy content. The OPAQUE path is dormant by default.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Optional

from fastapi import HTTPException


def authorize_pin_only_action(
    principal: dict,
    *,
    pin: Optional[str],
    zk_proof_token: Optional[str],
    flag_name: str,
    verify_pin: Callable[[str, str], object],
) -> None:
    vault_id = principal["vault_id"]
    enabled = os.getenv(flag_name, "false").strip().lower() == "true"
    if enabled:
        from vault_core import is_vault_zk_adopted

        if is_vault_zk_adopted(vault_id):
            if pin is not None:
                raise HTTPException(409, detail="zk_client_update_required")
            if not zk_proof_token:
                raise HTTPException(401, detail="zk_proof_token_required")
            from routes.auth_zk_routes import consume_recent_zk_proof

            consume_recent_zk_proof(zk_proof_token, principal)
            return
    if zk_proof_token is not None:
        raise HTTPException(409, detail="zk_action_proof_not_enabled")
    if not pin:
        raise HTTPException(400, detail="pin_required")
    verify_pin(vault_id, pin)
