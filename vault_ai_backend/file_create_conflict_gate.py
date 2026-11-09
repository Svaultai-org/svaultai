"""Fail closed until all new V2 uploads preserve legacy conflict decisions.

V2 manifests intentionally hide names and content from the server. The current
schema has no MVK-blinded name/content tokens, and older uploaded_files rows
have no such tokens either. A local preflight cannot close a concurrent writer
race. Do not issue a signed file-create offer or publish through any new-file
V2 mode until all older and V2 files are indexed and an atomic server-side
conflict decision is implemented and tested.
"""

from fastapi import HTTPException


def new_file_conflict_parity_ready() -> bool:
    # This is deliberately not an environment switch. Setting only deployment
    # flags cannot assert that schema, backfill, and race-safe decisions exist.
    return False


def require_new_file_conflict_parity() -> None:
    if not new_file_conflict_parity_ready():
        raise HTTPException(409, detail="private_file_conflict_index_unavailable")
