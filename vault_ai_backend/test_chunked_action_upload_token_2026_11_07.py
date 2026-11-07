"""Pending chunk completion uses PIN-free, file-scoped token routes."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from chunked_tokens import issue_chunk_token
from routes import chunked_upload_routes as routes


def test_token_routes_are_separate_from_retained_raw_pin_routes():
    app = FastAPI()
    app.include_router(routes.router)
    paths = {route.path for route in app.routes}
    assert {"/upload-file/finalize", "/upload-file/abort",
            "/upload-file/finalize-token", "/upload-file/abort-token"} <= paths
    assert "pin" in routes.ChunkFinalizeRequest.model_fields
    assert "pin" in routes.ChunkAbortRequest.model_fields
    assert "pin" not in routes.ChunkActionTokenRequest.model_fields
    with pytest.raises(ValidationError):
        routes.ChunkActionTokenRequest(
            file_id="synthetic-file", upload_token="synthetic-token",
            pin="synthetic-pin",
        )


def test_token_routes_bind_vault_file_and_kind_without_pin(monkeypatch):
    vault_id = str(uuid.uuid4())
    file_id = "synthetic-pending-file"
    token, _ = issue_chunk_token(
        kind="upload", vault_id=vault_id, file_id=file_id, ttl_seconds=60,
    )
    monkeypatch.setattr(
        routes, "verify_vault_pin",
        lambda *_args: pytest.fail("token path must not verify a PIN"),
    )
    called = []

    async def finish(*, vault_id, file_id):
        called.append(("finish", vault_id, file_id))
        return {"status": "complete", "file_id": file_id}

    async def abort(*, vault_id, file_id):
        called.append(("abort", vault_id, file_id))
        return {"status": "aborted", "file_id": file_id}

    monkeypatch.setattr(routes, "_finalize_pending_chunk_upload", finish)
    monkeypatch.setattr(routes, "_abort_pending_chunk_upload", abort)
    principal = {"vault_id": vault_id}
    payload = routes.ChunkActionTokenRequest(file_id=file_id, upload_token=token)
    assert asyncio.run(routes.upload_file_finalize_token(payload, principal)) == {
        "status": "complete", "file_id": file_id,
    }
    assert asyncio.run(routes.upload_file_abort_token(payload, principal)) == {
        "status": "aborted", "file_id": file_id,
    }
    assert called == [
        ("finish", vault_id, file_id), ("abort", vault_id, file_id),
    ]

    for wrong_vault, wrong_file in (
        (str(uuid.uuid4()), file_id),
        (vault_id, "other-file"),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(routes.upload_file_abort_token(
                routes.ChunkActionTokenRequest(
                    file_id=wrong_file, upload_token=token,
                ), {"vault_id": wrong_vault},
            ))
        assert exc.value.status_code == 401
    download_token, _ = issue_chunk_token(
        kind="download", vault_id=vault_id, file_id=file_id,
        ttl_seconds=60,
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.upload_file_finalize_token(
            routes.ChunkActionTokenRequest(
                file_id=file_id, upload_token=download_token,
            ), principal,
        ))
    assert exc.value.status_code == 401
    assert len(called) == 2
