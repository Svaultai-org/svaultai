

from __future__ import annotations

import json

import pytest

import vault_complete_search as vcs
import vault_pdf_page_vision as vpv
from vault_complete_search import (
    DOC_TYPE_DRIVER_LICENSE,
    DOC_TYPE_PASSPORT,
    EVIDENCE_PDF_PAGE_VISION,
    MATCH_VISION,
    find_in_vault,
)
from vault_pdf_page_vision import (
    MAX_PDF_PAGES_PER_DOC,
    inspect_pdf_pages_with_vision,
    render_pdf_pages_to_png,
)


VAULT = "55555555-aaaa-bbbb-cccc-dddddddddddd"
KEY32 = b"\x00" * 32


def _make_pdf_with_pages(page_texts: list[str]) -> bytes:


    import fitz
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page()
        page.insert_text((72, 72), text or "", fontsize=18)
    out = doc.tobytes()
    doc.close()
    return out


@pytest.fixture
def fitz_two_page_pdf_bytes() -> bytes:
    return _make_pdf_with_pages([
        "STATE OF NEW YORK DRIVER LICENSE Holder LOUIS IODATO",
        "Issued 2020-01-01 Class D",
    ])


@pytest.fixture
def fitz_blank_pdf_bytes() -> bytes:
    return _make_pdf_with_pages(["", ""])


def test_render_returns_png_per_page(fitz_two_page_pdf_bytes):
    pngs, total = render_pdf_pages_to_png(
        fitz_two_page_pdf_bytes, max_pages=3,
    )
    assert total == 2
    assert len(pngs) == 2
    for b in pngs:
                                                            
                                               
        assert b[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(b) > 200                           


def test_render_caps_at_max_pages():
    pdf = _make_pdf_with_pages([
        "Page 1", "Page 2", "Page 3", "Page 4", "Page 5",
    ])
    pngs, total = render_pdf_pages_to_png(pdf, max_pages=2)
    assert total == 5
    assert len(pngs) == 2


def test_render_handles_garbage_input():
    pngs, total = render_pdf_pages_to_png(b"definitely not a pdf")
    assert pngs == []
    assert total == 0


def test_render_handles_empty_bytes():
    pngs, total = render_pdf_pages_to_png(b"")
    assert pngs == []
    assert total == 0


def test_render_skips_oversize_pages(monkeypatch, fitz_two_page_pdf_bytes):


    monkeypatch.setattr(vpv, "MAX_PNG_BYTES", 1, raising=True)
    pngs, total = render_pdf_pages_to_png(
        fitz_two_page_pdf_bytes, max_pages=3,
    )
    assert total == 2
    assert pngs == []


def test_inspect_runs_vision_per_page(fitz_two_page_pdf_bytes):


    calls: list[tuple[int, str]] = []

    def fake_vision(png_bytes, question):
        calls.append((len(png_bytes), question))
        return f"page-{len(calls)} says: driver license for Louis Iodato"

    out = inspect_pdf_pages_with_vision(
        file_id="abcdef12-3456-7890",
        pdf_bytes=fitz_two_page_pdf_bytes,
        question="Is this a driver license?",
        max_pages=3,
        vision_callable=fake_vision,
    )
    assert out["pages_inspected"] == 2
    assert out["total_pages"] == 2
    assert out["budget_exceeded"] is False
    assert len(out["page_results"]) == 2
    assert {pr["page_index"] for pr in out["page_results"]} == {0, 1}
                                                        
    assert all(q == "Is this a driver license?" for _, q in calls)


def test_inspect_skips_pages_with_no_vision_response(fitz_two_page_pdf_bytes):


    def fake_vision(png_bytes, question):
        return None

    out = inspect_pdf_pages_with_vision(
        file_id="x", pdf_bytes=fitz_two_page_pdf_bytes,
        question="?", vision_callable=fake_vision,
    )
    assert out["pages_inspected"] == 2
    assert out["page_results"] == []


def test_inspect_marks_budget_exceeded_when_total_exceeds_cap():
    pdf = _make_pdf_with_pages(["1", "2", "3", "4", "5"])

    def fake_vision(png_bytes, question):
        return ""

    out = inspect_pdf_pages_with_vision(
        file_id="x", pdf_bytes=pdf, question="?",
        max_pages=2, vision_callable=fake_vision,
    )
    assert out["total_pages"] == 5
    assert out["pages_inspected"] == 2
    assert out["budget_exceeded"] is True


def test_inspect_vision_callable_exception_continues_to_next_page(
    fitz_two_page_pdf_bytes,
):
    def fake_vision(png_bytes, question):
                                             
        if "page 0" not in question:
            return "this image is a driver license for Louis Iodato"
        raise RuntimeError("simulated vision failure")

                                                              
    state = {"n": 0}

    def fake_vision_v2(png_bytes, question):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("vision exploded on page 0")
        return "driver license for Louis Iodato"

    out = inspect_pdf_pages_with_vision(
        file_id="x", pdf_bytes=fitz_two_page_pdf_bytes,
        question="?", vision_callable=fake_vision_v2,
    )
    assert out["pages_inspected"] == 2
    assert len(out["page_results"]) == 1
    assert out["page_results"][0]["page_index"] == 1


def _pdf_row(*, file_id: str, file_name: str = "scanned_id.pdf",
             encrypted: bytes = b"") -> dict:


    return {
        "id":                  file_id,
        "file_name":           file_name,
        "saved_name":          file_name,
        "content_type":        "application/pdf",
        "asset_type":          "document",
        "extracted_text":      None,
        "relative_path":       "",
        "created_at":          None,
        "encrypted_file_data": "ENC:" + file_name,                  
    }


@pytest.fixture
def install_file_list(monkeypatch):
    def _do(rows: list[dict]):
        def _fake_list(vault_id, key):
            return [dict(r) for r in rows]
        monkeypatch.setattr(
            "main._list_uploaded_files_for_credential_search",
            _fake_list, raising=True,
        )
    return _do


@pytest.fixture
def install_pdf_decrypt(monkeypatch):


    def _do(mapping: dict[str, bytes]):
        def _fake_decrypt(row, key):
            return mapping.get(row.get("id"))
        monkeypatch.setattr(
            "vault_complete_search._decrypt_pdf_bytes",
            _fake_decrypt, raising=True,
        )
    return _do


@pytest.fixture
def install_pdf_inspector(monkeypatch):


    def _do(side_effect):
        def _fake_inspect(
            *, file_id, pdf_bytes, question,
            max_pages=MAX_PDF_PAGES_PER_DOC, dpi=None,
            vision_callable=None,
        ):
            return side_effect(
                file_id, pdf_bytes, question, max_pages,
            )
        monkeypatch.setattr(
            "vault_pdf_page_vision.inspect_pdf_pages_with_vision",
            _fake_inspect, raising=True,
        )
    return _do


@pytest.fixture
def install_image_vision_stub(monkeypatch):


    def _fake_image(*, vault_id, key, file_id, question):
        return json.dumps({"file_id": file_id, "analysis": ""})
    monkeypatch.setattr(
        "vault_inspection_tools.read_image_with_vision",
        _fake_image, raising=True,
    )


def test_scanned_pdf_driver_license_with_name_is_found(
    install_file_list, install_pdf_decrypt,
    install_pdf_inspector, install_image_vision_stub,
):


    install_file_list([
        _pdf_row(file_id="pdf-dl", file_name="scanned_dl.pdf"),
    ])
    install_pdf_decrypt({"pdf-dl": b"%PDF-FAKE"})
    install_pdf_inspector(lambda fid, pdf, q, max_pages: {
        "pages_inspected": 1,
        "total_pages":     1,
        "budget_exceeded": False,
        "page_results":    [{
            "page_index": 0,
            "analysis": (
                "This page is a State of New York driver license. "
                "The name on the license is Louis Iodato. "
                "Class D."
            ),
        }],
    })
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="find me a driver license for Louis Lodato",
        doc_kind="id_photo",
    ))
    assert out["complete"] is True
    assert len(out["hits"]) == 1
    hit = out["hits"][0]
    assert hit["file_id"] == "pdf-dl"
    assert hit["file_name"] == "scanned_dl.pdf"
    assert hit["file_kind"] == "pdf"
    assert hit["evidence_type"] == EVIDENCE_PDF_PAGE_VISION
    assert hit["match_type"] == MATCH_VISION
    assert hit["document_type"] == DOC_TYPE_DRIVER_LICENSE
    assert hit["matched_name"] == "Louis Iodato"
    assert 0.0 <= hit["confidence"] <= 1.0


def test_scanned_pdf_passport_is_found(
    install_file_list, install_pdf_decrypt,
    install_pdf_inspector, install_image_vision_stub,
):
    install_file_list([
        _pdf_row(file_id="pdf-pp", file_name="passport_scan.pdf"),
    ])
    install_pdf_decrypt({"pdf-pp": b"%PDF-FAKE-PP"})
    install_pdf_inspector(lambda fid, pdf, q, max_pages: {
        "pages_inspected": 2,
        "total_pages":     2,
        "budget_exceeded": False,
        "page_results":    [
            {"page_index": 0, "analysis": (
                "This is a US passport. The name on the document "
                "is Louis Iodato. Place of birth visible."
            )},
            {"page_index": 1, "analysis": "Visa page; blank."},
        ],
    })
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="find me any passport for Louis Lodato",
        doc_kind="passport",
    ))
    assert out["complete"] is True
    assert len(out["hits"]) == 1
    hit = out["hits"][0]
    assert hit["document_type"] == DOC_TYPE_PASSPORT
    assert hit["evidence_type"] == EVIDENCE_PDF_PAGE_VISION
    assert hit["file_name"] == "passport_scan.pdf"
    assert hit["matched_name"] == "Louis Iodato"


def test_pdf_with_no_id_returns_no_hit(
    install_file_list, install_pdf_decrypt,
    install_pdf_inspector, install_image_vision_stub,
):


    install_file_list([
        _pdf_row(file_id="pdf-recipe", file_name="recipe.pdf"),
    ])
    install_pdf_decrypt({"pdf-recipe": b"%PDF-FAKE-RECIPE"})
    install_pdf_inspector(lambda fid, pdf, q, max_pages: {
        "pages_inspected": 1,
        "total_pages":     1,
        "budget_exceeded": False,
        "page_results":    [{
            "page_index": 0,
            "analysis": (
                "This page shows a chocolate cake recipe. "
                "No ID document, no passport, no driver "
                "license visible."
            ),
        }],
    })
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="show me all my ID photos",
        doc_kind="id_photo",
    ))
    assert out["hits"] == []
    assert out["complete"] is True


def test_pdf_page_budget_exceeded_keeps_complete_true(
    install_file_list, install_pdf_decrypt,
    install_pdf_inspector, install_image_vision_stub,
):


    install_file_list([
        _pdf_row(file_id="pdf-long", file_name="bigscan.pdf"),
    ])
    install_pdf_decrypt({"pdf-long": b"%PDF-FAKE-LONG"})
    install_pdf_inspector(lambda fid, pdf, q, max_pages: {
        "pages_inspected": max_pages,
        "total_pages":     5,
        "budget_exceeded": True,
        "page_results":    [
            {"page_index": i, "analysis": "No ID document on this page."}
            for i in range(max_pages)
        ],
    })
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="find me any passport in my vault",
    ))
    assert out["hits"] == []
                                                            
                              
    assert out["complete"] is True
    assert out["partial_inspection"] is True
    assert out["coverage"]["pdf_overflow"] is True
    assert out["coverage"]["pdf_pages_used"] >= 1


def test_text_files_are_still_rejected_for_id_search(
    install_file_list, install_pdf_decrypt,
    install_pdf_inspector, install_image_vision_stub,
):


    install_file_list([
        {
            "id": "txt-1",
            "file_name": "notes.txt",
            "saved_name": "notes.txt",
            "content_type": "text/plain",
            "extracted_text": "John Doe ID number 123-45-6789",
            "asset_type": None,
            "relative_path": "", "created_at": None,
        },
        _pdf_row(file_id="pdf-dl"),
    ])
    install_pdf_decrypt({"pdf-dl": b"%PDF-FAKE"})
    install_pdf_inspector(lambda fid, pdf, q, max_pages: {
        "pages_inspected": 1, "total_pages": 1,
        "budget_exceeded": False,
        "page_results": [{
            "page_index": 0,
            "analysis": "Driver license for Louis Iodato",
        }],
    })
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="show me all my ID photos",
        doc_kind="id_photo",
    ))
    assert {h["file_id"] for h in out["hits"]} == {"pdf-dl"}
    assert "notes.txt" not in {h["file_name"] for h in out["hits"]}


def test_pdf_pass_skips_pdfs_with_existing_text_hit(
    install_file_list, install_pdf_decrypt,
    install_pdf_inspector, install_image_vision_stub,
):


    inspector_calls: list = []

    def _stub(fid, pdf, q, max_pages):
        inspector_calls.append(fid)
        return {
            "pages_inspected": 0, "total_pages": 0,
            "budget_exceeded": False, "page_results": [],
        }
    install_pdf_inspector(_stub)
    install_file_list([
        {
            "id": "pdf-text-hit",
            "file_name": "license.pdf",
            "saved_name": "license.pdf",
            "content_type": "application/pdf",
            "asset_type": "document",
            "extracted_text": (
                "Driver license: holder Louis Iodato, "
                "license class D, DOB 1980-01-01."
            ),
            "encrypted_file_data": "ENC:license.pdf",
            "relative_path": "", "created_at": None,
        },
    ])
    install_pdf_decrypt({"pdf-text-hit": b"%PDF"})
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="Louis Lodato", doc_kind="id_photo",
    ))
                                                               
                    
    assert "pdf-text-hit" not in inspector_calls
    assert any(
        h["file_id"] == "pdf-text-hit" for h in out["hits"]
    )


def test_pdf_pass_only_runs_in_id_class_mode(
    install_file_list, install_pdf_decrypt,
    install_pdf_inspector, install_image_vision_stub,
):


    inspector_calls: list = []

    def _stub(fid, pdf, q, max_pages):
        inspector_calls.append(fid)
        return {
            "pages_inspected": 0, "total_pages": 0,
            "budget_exceeded": False, "page_results": [],
        }
    install_pdf_inspector(_stub)
    install_file_list([
        _pdf_row(file_id="pdf-meh", file_name="meh.pdf"),
    ])
    install_pdf_decrypt({"pdf-meh": b"%PDF-FAKE"})
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="Wells Fargo bank statement",
    ))
    assert inspector_calls == []
    assert out["hits"] == []
    assert out["complete"] is True


def test_pdf_hit_picks_highest_confidence_page(
    install_file_list, install_pdf_decrypt,
    install_pdf_inspector, install_image_vision_stub,
):


    install_file_list([
        _pdf_row(file_id="pdf-multi", file_name="multipage.pdf"),
    ])
    install_pdf_decrypt({"pdf-multi": b"%PDF"})
    install_pdf_inspector(lambda fid, pdf, q, max_pages: {
        "pages_inspected": 3, "total_pages": 3,
        "budget_exceeded": False,
        "page_results": [
            {"page_index": 0, "analysis": (
                "This is a passport for Louis Iodato."
            )},
            {"page_index": 1, "analysis": (
                "Driver license. Holder Louis Iodato."
            )},
            {"page_index": 2, "analysis": "Blank."},
        ],
    })
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="Louis Lodato", doc_kind="id_photo",
    ))
                                                           
                
    assert len(out["hits"]) == 1
    assert out["hits"][0]["file_id"] == "pdf-multi"


def test_pdf_pass_decrypt_failure_skips_quietly(
    install_file_list, install_pdf_decrypt,
    install_pdf_inspector, install_image_vision_stub,
):


    install_file_list([
        _pdf_row(file_id="pdf-broken", file_name="broken.pdf"),
    ])
    install_pdf_decrypt({})                                       

    def _stub(fid, pdf, q, max_pages):
        raise RuntimeError("must not be called for un-decryptable PDF")
    install_pdf_inspector(_stub)

    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="show me all my ID photos",
        doc_kind="id_photo",
    ))
    assert out["hits"] == []
                                                             
                                          
    assert out["complete"] is True


def test_find_in_vault_remains_never_cacheable_after_pdf_pass():
    from vault_tool_result_cache import (
        CACHEABLE_TOOLS, NEVER_CACHEABLE_TOOLS,
    )
    assert "find_in_vault" in NEVER_CACHEABLE_TOOLS
    assert "find_in_vault" not in CACHEABLE_TOOLS


def test_evidence_pdf_page_vision_is_in_closed_set():
    from vault_complete_search import (
        EVIDENCE_EXTRACTED_TEXT, EVIDENCE_IMAGE_VISION,
        EVIDENCE_PDF_PAGE_VISION, EVIDENCE_OCR_TEXT,
    )
    assert EVIDENCE_PDF_PAGE_VISION == "pdf_page_vision"
    closed_set = {
        EVIDENCE_EXTRACTED_TEXT,
        EVIDENCE_IMAGE_VISION,
        EVIDENCE_PDF_PAGE_VISION,
        EVIDENCE_OCR_TEXT,
    }
                              
    assert len(closed_set) == 4


def test_pdf_vision_log_line_carries_no_raw_text():


    import logging
    pdf = _make_pdf_with_pages(["DRIVER LICENSE LOUIS IODATO"])

    def fake_vision(png_bytes, question):
        return "secret-vision-body-LOUIS-IODATO-licence-no-12345"

    records: list[logging.LogRecord] = []

    class _Sink(logging.Handler):
        def emit(self, record):
            records.append(record)

    sink = _Sink(level=logging.DEBUG)
    sink.setLevel(logging.DEBUG)
    log = logging.getLogger("vault_pdf_page_vision")
    prior_level = log.level
    prior_disabled = log.disabled
    prior_propagate = log.propagate
    log.addHandler(sink)
    log.setLevel(logging.DEBUG)
    log.disabled = False
    log.propagate = True
    try:
        inspect_pdf_pages_with_vision(
            file_id="abc12345-deadbeef",
            pdf_bytes=pdf,
            question="user query Louis Lodato",
            vision_callable=fake_vision,
        )
    finally:
        log.removeHandler(sink)
        log.setLevel(prior_level)
        log.disabled = prior_disabled
        log.propagate = prior_propagate
    body = "\n".join(rec.getMessage() for rec in records)
    assert "secret-vision-body" not in body
    assert "LOUIS-IODATO" not in body
    assert "Louis Lodato" not in body
    assert "user query" not in body
                                                   
    assert "file_id=abc12345" in body
    assert "pages_inspected=1" in body
    assert "total_pages=1" in body
