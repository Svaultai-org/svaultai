

from __future__ import annotations

import json

import pytest

import vault_complete_search as vcs
from vault_complete_search import (
    DOC_TYPE_DRIVER_LICENSE,
    ID_CLASS_VISION_BUDGET,
    MAX_VISION_INSPECTIONS,
    find_in_vault,
)


def _row_image(*, file_id, file_name):
    return {
        "id": file_id,
        "file_name": file_name,
        "saved_name": file_name,
        "extracted_text": None,
        "extracted_text_status": "not_available",
        "content_type": "image/jpeg",
        "encrypted_file_data": None,
        "storage_mode": "inline",
    }


def _patch_vision(monkeypatch, response_text):


    import vault_inspection_tools as vit

    def _fake(*, vault_id, key, file_id, question):
        if isinstance(response_text, dict):
            text = response_text.get(file_id, "")
        else:
            text = response_text
        return json.dumps({"analysis": text})

    monkeypatch.setattr(vit, "read_image_with_vision", _fake)


def test_id_class_budget_is_higher_than_default():
    assert ID_CLASS_VISION_BUDGET >= 50, (
        "operator pinned ID-class budget at >= 50 so small/normal "
        "vaults complete in one turn"
    )
    assert ID_CLASS_VISION_BUDGET > MAX_VISION_INSPECTIONS


def test_bob_smith_with_one_non_matching_id(monkeypatch):


    import main as main_mod

    img = _row_image(file_id="img-k", file_name="kendra.jpg")
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: [img],
    )
    _patch_vision(
        monkeypatch,
        "This is a driver's license. The visible name is "
        "Kendra Chosen.",
    )

    raw = find_in_vault(
        vault_id="v", key=b"\x00" * 32,
        query="find me an ID photo for Bob Smith",
        doc_kind="id_photo",
    )
    result = json.loads(raw)
    assert result["complete"] is True
    assert result["hits"] == []
    assert result["name_mismatch_count"] == 1
    assert result["candidate_id_docs_count"] == 1
                                                                
                               
    assert result["partial_inspection"] is False


def test_normal_id_search_does_not_return_complete_false_for_budget(monkeypatch):
    import main as main_mod

    rows = [
        _row_image(file_id=f"img-{i}", file_name=f"id_{i}.jpg")
        for i in range(20)
    ]
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: rows,
    )
    _patch_vision(
        monkeypatch,
        "This is a driver's license. The visible name is "
        "Kendra Chosen.",
    )

    raw = find_in_vault(
        vault_id="v", key=b"\x00" * 32,
        query="find me an ID photo for Bob Smith",
        doc_kind="id_photo",
    )
    result = json.loads(raw)
                                                              
                                                             
    assert result["complete"] is True
    assert result["partial_inspection"] is False
    assert result["files_via_vision"] == 0                           
    assert result["candidate_id_docs_count"] == 20
    assert result["name_mismatch_count"] == 20


def test_budget_hit_still_reports_complete_true(monkeypatch):


    import main as main_mod

                                                                  
    rows = [
        _row_image(file_id=f"img-{i}", file_name=f"id_{i}.jpg")
        for i in range(ID_CLASS_VISION_BUDGET + 5)
    ]
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: rows,
    )
    _patch_vision(
        monkeypatch,
        "This is a driver's license. The visible name is "
        "Kendra Chosen.",
    )

    raw = find_in_vault(
        vault_id="v", key=b"\x00" * 32,
        query="find me an ID photo for Bob Smith",
        doc_kind="id_photo",
    )
    result = json.loads(raw)
    assert result["complete"] is True, (
        "is_complete MUST stay True even when the budget was hit"
    )
    assert result["partial_inspection"] is True, (
        "partial_inspection MUST capture the budget hit for ops"
    )


def test_is_complete_false_reserved_for_system_errors(monkeypatch):


    import main as main_mod

    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: [],
    )

    raw = find_in_vault(
        vault_id="v", key=b"\x00" * 32,
        query="show me all ID photos",
        doc_kind="id_photo",
    )
    result = json.loads(raw)
    assert result["complete"] is True


def test_envelope_message_definitive_when_budget_hit(monkeypatch):


    import main as main_mod
    from vault_chat_result_cards import build_find_in_vault_envelope

    rows = [
        _row_image(file_id=f"img-{i}", file_name=f"id_{i}.jpg")
        for i in range(ID_CLASS_VISION_BUDGET + 5)
    ]
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: rows,
    )
    _patch_vision(
        monkeypatch,
        "This is a driver's license. The visible name is "
        "Kendra Chosen.",
    )

    raw = find_in_vault(
        vault_id="v", key=b"\x00" * 32,
        query="find me an ID photo for Bob Smith",
        doc_kind="id_photo",
    )
    find_result = json.loads(raw)
    env = json.loads(build_find_in_vault_envelope(
        query="find me an ID photo for Bob Smith",
        find_result=find_result,
        key=b"\x00" * 32,
        rows_by_id={r["id"]: {"content_type": "image/jpeg"}
                    for r in rows},
        thumbnail_fetcher=lambda fid: None,
    ))
    msg = env["message"]
    low = msg.lower()
                                                 
    assert "search incomplete" not in low
    assert "search hit its limit" not in low
    assert "still analyzing" not in low
    assert "ask again" not in low
                                                              
                  
    assert "found id documents" in low or "couldn't find" in low
    assert env["is_complete"] is True


def test_message_no_id_docs_says_so(monkeypatch):


    from vault_chat_result_cards import build_find_in_vault_envelope
    find_result = {
        "complete": True,
        "query_kind": "id_photo_visual",
        "hits": [],
        "candidate_id_docs_count": 0,
        "name_mismatch_count": 0,
        "requested_person_name": "Bob Smith",
    }
    env = json.loads(build_find_in_vault_envelope(
        query="find ID photo for Bob Smith",
        find_result=find_result,
        key=b"\x00" * 32,
        rows_by_id={},
        thumbnail_fetcher=lambda fid: None,
    ))
    assert env["message"] == (
        "I couldn't find any ID documents in your vault."
    )


def test_message_id_docs_exist_but_mismatch_person(monkeypatch):
    from vault_chat_result_cards import build_find_in_vault_envelope
    find_result = {
        "complete": True,
        "query_kind": "id_photo_visual",
        "hits": [],
        "candidate_id_docs_count": 1,
        "name_mismatch_count": 1,
        "requested_person_name": "Bob Smith",
    }
    env = json.loads(build_find_in_vault_envelope(
        query="find ID photo for Bob Smith",
        find_result=find_result,
        key=b"\x00" * 32,
        rows_by_id={},
        thumbnail_fetcher=lambda fid: None,
    ))
    assert env["message"] == (
        "I found ID documents in your vault, but none matched "
        "Bob Smith."
    )


def test_message_complete_with_matching_hit(monkeypatch):

    from vault_chat_result_cards import build_find_in_vault_envelope
    find_result = {
        "complete": True,
        "query_kind": "id_photo_visual",
        "hits": [{
            "file_id":       "h1",
            "file_name":     "dl.pdf",
            "file_kind":     "pdf",
            "evidence_type": "pdf_page_vision",
            "match_type":    "vision",
            "document_type": DOC_TYPE_DRIVER_LICENSE,
            "matched_name":  "Louis Iodato",
            "confidence":    0.86,
            "evidence":      "vision",
            "classification_strength": "visual_confirmed",
            "match_status": "fuzzy_name_match",
        }],
        "candidate_id_docs_count": 1,
        "name_mismatch_count": 0,
        "requested_person_name": "Louis Lodato",
    }
    env = json.loads(build_find_in_vault_envelope(
        query="find me a driver license for Louis Lodato",
        find_result=find_result,
        key=b"\x00" * 32,
        rows_by_id={"h1": {"content_type": "application/pdf"}},
        thumbnail_fetcher=lambda fid: None,
    ))
    assert env["message"] == "I found 1 matching ID photo."
    assert env["is_complete"] is True


def test_message_complete_false_now_means_system_error():


    from vault_chat_result_cards import _build_summary_message
    msg = _build_summary_message(
        results=[], is_complete=False, query="show ID photos",
        query_kind="id_photo_visual",
        candidate_id_docs_count=0,
        name_mismatch_count=0,
        requested_person_name="",
    )
    low = msg.lower()
    assert "something went wrong" in low or "please try again" in low
                                                  
    assert "still analyzing" not in low
    assert "ask again" not in low
    assert "search incomplete" not in low
    assert "search hit its limit" not in low


def test_coverage_surfaces_partial_inspection_flag(monkeypatch):
    import main as main_mod

    rows = [
        _row_image(file_id=f"img-{i}", file_name=f"id_{i}.jpg")
        for i in range(ID_CLASS_VISION_BUDGET + 3)
    ]
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: rows,
    )
    _patch_vision(
        monkeypatch,
        "This is a driver's license. The visible name is "
        "Kendra Chosen.",
    )

    raw = find_in_vault(
        vault_id="v", key=b"\x00" * 32,
        query="find me an ID photo for Bob Smith",
        doc_kind="id_photo",
    )
    result = json.loads(raw)
    cov = result["coverage"]
    assert cov["partial_inspection"] is True
    assert cov["vision_overflow"] is True
                                          
    assert cov["is_complete"] is True
