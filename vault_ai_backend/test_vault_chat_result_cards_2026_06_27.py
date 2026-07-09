

from __future__ import annotations

import base64
import io
import json
import logging

import pytest

import vault_chat_result_cards as vcc
from vault_chat_result_cards import (
    MAX_THUMBNAIL_BYTES,
    MAX_TOTAL_THUMB_BYTES,
    THUMBNAIL_MAX_SIDE,
    _build_summary_message,
    _render_image_thumbnail,
    _render_pdf_thumbnail,
    _ui_file_kind,
    build_find_in_vault_envelope,
)


def _make_png(size=(800, 800), color=(80, 120, 160)) -> bytes:
    from PIL import Image
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_noisy_png(size=(800, 800), seed=42) -> bytes:


    from PIL import Image
                                              
    w, h = size
    rnd = seed
    px = bytearray(w * h * 3)
    for i in range(len(px)):
        rnd = (rnd * 1103515245 + 12345) & 0x7FFFFFFF
        px[i] = rnd & 0xFF
    img = Image.frombytes("RGB", size, bytes(px))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_pdf(page_text: str = "DRIVER LICENSE Louis Iodato") -> bytes:
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), page_text, fontsize=18)
    out = doc.tobytes()
    doc.close()
    return out


def _hit(
    *,
    file_id: str,
    file_name: str,
    file_kind: str = "image",
    evidence_type: str = "image_vision",
    match_type: str = "vision",
    document_type: str = "driver_license",
    matched_name: str | None = "Louis Iodato",
    confidence: float = 0.84,
    evidence: str = "vision: driver license, name Louis Iodato",
) -> dict:
    return {
        "file_id":       file_id,
        "file_name":     file_name,
        "file_kind":     file_kind,
        "evidence_type": evidence_type,
        "match_type":    match_type,
        "document_type": document_type,
        "matched_name":  matched_name,
        "confidence":    confidence,
        "evidence":      evidence,
    }


def _find_result(hits, *, complete=True, coverage=None) -> dict:
    return {
        "doc_kind":           "driver_license",
        "is_id_class_search": True,
        "complete":           complete,
        "hits":               hits,
        "files_inspected":    len(hits),
        "files_via_text":     0,
        "files_via_vision":   len(hits),
        "coverage":           coverage or {"text_scanned": 0, "vision_used": len(hits)},
    }


def test_image_thumbnail_is_jpeg_bounded():
    png = _make_png(size=(2000, 1500))
    jpeg = _render_image_thumbnail(png)
    assert jpeg is not None
                 
    assert jpeg[:3] == b"\xff\xd8\xff"
                                                             
    from PIL import Image
    out = Image.open(io.BytesIO(jpeg))
    assert max(out.size) <= THUMBNAIL_MAX_SIDE
                                                     
    assert len(jpeg) <= MAX_THUMBNAIL_BYTES


def test_image_thumbnail_handles_rgba_source():

    from PIL import Image
    img = Image.new("RGBA", (500, 500), (200, 100, 50, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    jpeg = _render_image_thumbnail(buf.getvalue())
    assert jpeg is not None and jpeg[:3] == b"\xff\xd8\xff"


def test_image_thumbnail_garbage_returns_none():
    assert _render_image_thumbnail(b"not an image") is None


def test_image_thumbnail_empty_returns_none():
    assert _render_image_thumbnail(b"") is None


def test_pdf_thumbnail_returns_jpeg_of_page_1():
    pdf = _make_pdf("PASSPORT FRANCE Iodato Louis")
    jpeg = _render_pdf_thumbnail(pdf)
    assert jpeg is not None
    assert jpeg[:3] == b"\xff\xd8\xff"
    assert len(jpeg) <= MAX_THUMBNAIL_BYTES


def test_pdf_thumbnail_garbage_returns_none():
    assert _render_pdf_thumbnail(b"%PDF-bogus") is None


def test_ui_file_kind_image_from_mime():
    assert _ui_file_kind(mime="image/png", hit_file_kind="") == "image"


def test_ui_file_kind_pdf_from_mime():
    assert _ui_file_kind(
        mime="application/pdf", hit_file_kind="",
    ) == "pdf"


def test_ui_file_kind_falls_back_to_hit_kind():
    assert _ui_file_kind(mime=None, hit_file_kind="image") == "image"
    assert _ui_file_kind(mime=None, hit_file_kind="pdf") == "pdf"
    assert _ui_file_kind(mime=None, hit_file_kind="weird") == "other"


def test_summary_message_singular_count():
    msg = _build_summary_message(
        results=[{"document_type": "driver_license"}],
        is_complete=True, query="",
    )
    assert "1" in msg and "file " in msg
    assert "driver-license" in msg


def test_summary_message_multiple_homogeneous():
    msg = _build_summary_message(
        results=[
            {"document_type": "driver_license"},
            {"document_type": "driver_license"},
            {"document_type": "driver_license"},
        ],
        is_complete=True, query="",
    )
    assert "3" in msg and "files" in msg
    assert "driver-license" in msg


def test_summary_message_mixed_uses_generic_label():
    msg = _build_summary_message(
        results=[
            {"document_type": "driver_license"},
            {"document_type": "passport"},
        ],
        is_complete=True, query="",
    )
    assert "matching" in msg


def test_summary_message_zero_complete():
    msg = _build_summary_message(
        results=[], is_complete=True, query="",
    )
    assert "couldn't find" in msg or "didn't find" in msg or "no" in msg.lower()


def test_summary_message_zero_incomplete_does_not_say_not_found():
    msg = _build_summary_message(
        results=[], is_complete=False, query="",
    )
                                                               
                                                             
    low = msg.lower()
    assert "something went wrong" in low
    assert "please try again" in low
                                             
    assert "couldn't find" not in low
    assert "search incomplete" not in low
    assert "search hit its limit" not in low
    assert "still analyzing" not in low


def test_summary_message_incomplete_with_hits_keeps_caveat():
    msg = _build_summary_message(
        results=[{"document_type": "driver_license"}],
        is_complete=False, query="",
    )
                                                                
                                                                 
    low = msg.lower()
    assert "search incomplete" in low
    assert "1 " in low                               


def test_envelope_carries_all_operator_listed_fields():
    png = _make_png(size=(900, 700))
    fetcher = lambda fid: png if fid == "f-1" else None              
    raw = build_find_in_vault_envelope(
        query="show me my driver license",
        find_result=_find_result([
            _hit(
                file_id="f-1", file_name="scanned_dl.png",
                file_kind="image",
                evidence_type="image_vision",
                document_type="driver_license",
                matched_name="Louis Iodato",
                confidence=0.84,
            ),
        ]),
        key=b"\x00" * 32,
        rows_by_id={"f-1": {
            "content_type": "image/png",
            "saved_name": "Driver License",
            "relative_path": "ID/scanned_dl.png",
            "storage_mode": "inline",
        }},
        thumbnail_fetcher=fetcher,
    )
    env = json.loads(raw)
    assert env["type"] == "file_search_results"
    assert env["query"] == "show me my driver license"
    assert env["count"] == 1
    assert "I found" in env["message"]
    row = env["results"][0]
                                             
    assert row["file_id"] == "f-1"
    assert row["file_name"] == "scanned_dl.png"
    assert row["saved_name"] == "Driver License"
    assert row["relative_path"] == "ID/scanned_dl.png"
    assert row["mime_type"] == "image/png"
    assert row["file_kind"] == "image"
    assert row["document_type"] == "driver_license"
    assert row["matched_name"] == "Louis Iodato"
    assert row["confidence"] == 0.84
    assert row["match_confidence"] == "strong"               
    assert row["evidence_type"] == "image_vision"
    assert row["match_type"] == "vision"
                                         
    assert row["thumbnail_base64"]
    decoded = base64.b64decode(row["thumbnail_base64"])
    assert decoded[:3] == b"\xff\xd8\xff"
    assert row["thumbnail_mime"] == "image/jpeg"


def test_envelope_renders_pdf_first_page_thumbnail():
    pdf = _make_pdf("DRIVER LICENSE Louis Iodato")
    fetcher = lambda fid: pdf if fid == "p-1" else None              
    raw = build_find_in_vault_envelope(
        query="driver license",
        find_result=_find_result([
            _hit(
                file_id="p-1", file_name="scanned_dl.pdf",
                file_kind="pdf",
                evidence_type="pdf_page_vision",
                document_type="driver_license",
                matched_name="Louis Iodato",
                confidence=0.81,
            ),
        ]),
        key=b"\x00" * 32,
        rows_by_id={"p-1": {
            "content_type": "application/pdf",
            "saved_name": None,
            "relative_path": None,
            "storage_mode": "inline",
        }},
        thumbnail_fetcher=fetcher,
    )
    env = json.loads(raw)
    row = env["results"][0]
    assert row["file_kind"] == "pdf"
    assert row["thumbnail_base64"]
    assert row["thumbnail_mime"] == "image/jpeg"


def test_envelope_dedupes_by_file_id():


    raw = build_find_in_vault_envelope(
        query="passport",
        find_result=_find_result([
            _hit(
                file_id="dup", file_name="dl.png", file_kind="image",
                evidence_type="image_vision",
                document_type="driver_license", matched_name="A B",
                confidence=0.6,
            ),
            _hit(
                file_id="dup", file_name="dl.png", file_kind="image",
                evidence_type="extracted_text",
                document_type="driver_license", matched_name="A B",
                confidence=0.4,
            ),
        ]),
        key=b"\x00" * 32,
        rows_by_id={"dup": {
            "content_type": "image/png",
            "saved_name": None,
            "relative_path": None,
            "storage_mode": "inline",
        }},
        thumbnail_fetcher=lambda fid: None,                   
    )
    env = json.loads(raw)
    assert env["count"] == 1
    assert env["results"][0]["file_id"] == "dup"


def test_envelope_empty_state_complete():

    raw = build_find_in_vault_envelope(
        query="driver license",
        find_result=_find_result([], complete=True),
        key=b"\x00" * 32,
        rows_by_id={},
        thumbnail_fetcher=lambda fid: None,
    )
    env = json.loads(raw)
    assert env["count"] == 0
    assert env["results"] == []
    assert env["is_complete"] is True
    assert "couldn't" in env["message"].lower() or \
           "didn't" in env["message"].lower() or \
           "no" in env["message"].lower()


def test_envelope_empty_state_incomplete_does_not_claim_not_found():
    raw = build_find_in_vault_envelope(
        query="passport",
        find_result=_find_result([], complete=False),
        key=b"\x00" * 32,
        rows_by_id={},
        thumbnail_fetcher=lambda fid: None,
    )
    env = json.loads(raw)
    assert env["is_complete"] is False
    assert env["incomplete_reason"] == "budget_exceeded"
                                                               
                                                            
    low = env["message"].lower()
    assert "couldn't find" not in low
    assert "no matches" not in low
    assert "still analyzing" not in low
    assert "search incomplete" not in low
    assert "search hit its limit" not in low
    assert "something went wrong" in low
    assert "please try again" in low


def test_oversize_thumbnail_drops_to_none(monkeypatch):
    monkeypatch.setattr(vcc, "MAX_THUMBNAIL_BYTES", 100)
                                                                
    png = _make_png(size=(1500, 1500))
    fetcher = lambda fid: png              
    raw = build_find_in_vault_envelope(
        query="driver license",
        find_result=_find_result([
            _hit(file_id="f-1", file_name="big.png", file_kind="image"),
        ]),
        key=b"\x00" * 32,
        rows_by_id={"f-1": {"content_type": "image/png"}},
        thumbnail_fetcher=fetcher,
    )
    env = json.loads(raw)
    assert env["results"][0]["thumbnail_base64"] is None
    assert env["results"][0]["thumbnail_mime"] is None


def test_total_envelope_cap_drops_tail_thumbnails(monkeypatch):
                                                                   
                                                               
    monkeypatch.setattr(vcc, "MAX_TOTAL_THUMB_BYTES", 12_000)
    png = _make_noisy_png(size=(900, 900))
    fetcher = lambda fid: png              
    hits = [
        _hit(file_id=f"f-{i}", file_name=f"id_{i}.png", file_kind="image")
        for i in range(4)
    ]
    rows = {
        f"f-{i}": {"content_type": "image/png"} for i in range(4)
    }
    raw = build_find_in_vault_envelope(
        query="driver license",
        find_result=_find_result(hits),
        key=b"\x00" * 32,
        rows_by_id=rows,
        thumbnail_fetcher=fetcher,
    )
    env = json.loads(raw)
    thumbs = [r["thumbnail_base64"] for r in env["results"]]
                                               
    assert any(t is None for t in thumbs)


def test_log_line_does_not_leak_file_names_or_names_or_query():


    png = _make_png(size=(800, 600))
    fetcher = lambda fid: png              
    records: list[logging.LogRecord] = []

    class _Sink(logging.Handler):
        def emit(self, record):
            records.append(record)

    sink = _Sink(level=logging.DEBUG)
    sink.setLevel(logging.DEBUG)
    log = logging.getLogger("vault_chat_result_cards")
    prior_level = log.level
    prior_disabled = log.disabled
    prior_propagate = log.propagate
    log.addHandler(sink)
    log.setLevel(logging.DEBUG)
    log.disabled = False
    log.propagate = True
    try:
        build_find_in_vault_envelope(
            query="super-secret query phrase about IODATO",
            find_result=_find_result([
                _hit(
                    file_id="f-secret", file_name="MY_DL_LOUIS_IODATO.png",
                    file_kind="image",
                    document_type="driver_license",
                    matched_name="LOUIS IODATO",
                ),
            ]),
            key=b"\x00" * 32,
            rows_by_id={"f-secret": {"content_type": "image/png"}},
            thumbnail_fetcher=fetcher,
        )
    finally:
        log.removeHandler(sink)
        log.setLevel(prior_level)
        log.disabled = prior_disabled
        log.propagate = prior_propagate
    joined = "\n".join(r.getMessage() for r in records)
    assert "MY_DL_LOUIS_IODATO" not in joined
    assert "IODATO" not in joined
    assert "super-secret" not in joined
                                    
    assert "hits=" in joined
    assert "cards=" in joined
    assert "thumbs_image=" in joined or "thumbs_pdf=" in joined
    assert "capped=" in joined


def test_find_in_vault_remains_never_cacheable():
    from vault_tool_result_cache import NEVER_CACHEABLE_TOOLS
    assert "find_in_vault" in NEVER_CACHEABLE_TOOLS


def test_main_ai_stream_intercepts_find_in_vault():
    import pathlib
    src = pathlib.Path(__file__).parent.joinpath("main.py").read_text(
        encoding="utf-8",
    )
    assert "build_find_in_vault_envelope" in src, (
        "ai_stream must import the envelope builder"
    )
                                            
    assert "_envelope_shipped" in src
                                                               
    assert "if not _envelope_shipped" in src
                                                                 
    assert "_truth_guard_tool_name = None" in src
