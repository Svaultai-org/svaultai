"""Compatibility gate for vaults containing client-only V2 files.

The header is a client capability signal, not an authentication factor. The
server binds it to a session at login and refuses an older client before that
login can supersede the current session. This prevents an old mobile build
from taking over a vault whose newly uploaded files it cannot open.
"""

from __future__ import annotations

from fastapi import HTTPException, Request


READER_HEADER = "X-SVaultAI-File-V2-Reader"


def request_has_file_v2_reader(request: Request) -> bool:
    return request.headers.get(READER_HEADER, "") == "1"


def require_file_v2_reader_for_login(cur, vault_id: str, capable: bool) -> None:
    if capable:
        return
    cur.execute(
        "SELECT 1 FROM file_v2_records WHERE vault_id=%s "
        "AND lifecycle_state='client_v2_ready' "
        "AND verification_state='client_verified' LIMIT 1",
        (vault_id,),
    )
    if cur.fetchone() is not None:
        raise HTTPException(status_code=426, detail={
            "code": "client_update_required",
            "message": "Update SVaultAI to open this vault's encrypted files.",
        })
