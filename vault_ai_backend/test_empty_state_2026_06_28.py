

from __future__ import annotations

import json

from vault_complete_search import (
    DOC_TYPE_DRIVER_LICENSE,
    EVIDENCE_IMAGE_VISION,
    MATCH_STATUS_EXACT_NAME_MATCH,
    MATCH_STATUS_NAME_MISMATCH,
)
from vault_chat_result_cards import (
    _build_summary_message,
    build_find_in_vault_envelope,
)


def _assert_no_still_analyzing(msg: str) -> None:
    low = (msg or "").lower()
    assert "still analyzing" not in low
    assert "ask again in a moment" not in low
    assert "no matches yet" not in low
    assert "wait" not in low or "waiting" in low                          


def test_complete_zero_hits_no_candidates_strict_mode():


    msg = _build_summary_message(
        results=[], is_complete=True, query="find ID photo for Bob",
        query_kind="id_photo_visual",
        candidate_id_docs_count=0,
        name_mismatch_count=0,
        requested_person_name="Bob Smith",
    )
    _assert_no_still_analyzing(msg)
    assert msg == "I couldn't find any ID documents in your vault."


def test_complete_zero_hits_no_candidates_strict_no_person():


    msg = _build_summary_message(
        results=[], is_complete=True, query="show ID photos",
        query_kind="id_photo_visual",
        candidate_id_docs_count=0,
        name_mismatch_count=0,
        requested_person_name="",
    )
    _assert_no_still_analyzing(msg)
    assert msg == "I couldn't find any ID documents in your vault."


def test_complete_zero_hits_name_mismatch_says_id_docs_exist():


    msg = _build_summary_message(
        results=[], is_complete=True,
        query="find ID photo for Louis Lodato",
        query_kind="id_photo_visual",
        candidate_id_docs_count=1,
        name_mismatch_count=1,
        requested_person_name="Louis Lodato",
    )
    _assert_no_still_analyzing(msg)
    low = msg.lower()
    assert "found id document" in low or "id documents" in low.lower()
    assert "louis lodato" in low
    assert "none matched" in low or "didn't match" in low


def test_complete_zero_hits_candidates_existed_but_no_person_given():


    msg = _build_summary_message(
        results=[], is_complete=True,
        query="show me all ID photos",
        query_kind="id_photo_visual",
        candidate_id_docs_count=2,
        name_mismatch_count=0,
        requested_person_name="",
    )
    _assert_no_still_analyzing(msg)
    assert "id documents" in msg.lower()


def test_incomplete_zero_hits_says_something_went_wrong():


    msg = _build_summary_message(
        results=[], is_complete=False,
        query="show me all ID photos",
        query_kind="id_photo_visual",
        candidate_id_docs_count=0,
        name_mismatch_count=0,
        requested_person_name="",
    )
    low = msg.lower()
    assert "something went wrong" in low
    assert "please try again" in low
                                              
    assert "still analyzing" not in low
    assert "ask again" not in low
    assert "moment" not in low
    assert "search incomplete" not in low
    assert "search hit its limit" not in low


def test_complete_zero_hits_weak_dropped_strict_says_no_actual_id():
    msg = _build_summary_message(
        results=[], is_complete=True,
        query="show ID photos",
        query_kind="id_photo_visual",
        weak_hits_dropped=4,
        candidate_id_docs_count=0,
        name_mismatch_count=0,
        requested_person_name="",
    )
    _assert_no_still_analyzing(msg)
    low = msg.lower()
    assert "no actual id" in low or "no actual" in low
    assert "mention" in low


def test_complete_with_hits_no_yet_word():

    msg = _build_summary_message(
        results=[{"document_type": "driver_license"}],
        is_complete=True, query="show ID photos",
        query_kind="id_photo_visual",
    )
    _assert_no_still_analyzing(msg)
    assert "yet" not in msg.lower()
    assert "moment" not in msg.lower()
    assert "still" not in msg.lower()


def test_strict_mode_hits_uses_id_photo_phrasing():


    msg = _build_summary_message(
        results=[{"document_type": "driver_license"}],
        is_complete=True, query="show ID photos",
        query_kind="id_photo_visual",
    )
    assert msg == "I found 1 matching ID photo."


def test_strict_mode_hits_pluralizes():
    msg = _build_summary_message(
        results=[
            {"document_type": "driver_license"},
            {"document_type": "passport"},
        ],
        is_complete=True, query="show ID photos",
        query_kind="id_photo_visual",
    )
    assert msg == "I found 2 matching ID photos."


def test_strict_incomplete_with_hits_says_search_incomplete():
    msg = _build_summary_message(
        results=[{"document_type": "driver_license"}],
        is_complete=False, query="show ID photos",
        query_kind="id_photo_visual",
    )
    low = msg.lower()
    assert "search incomplete" in low
    assert "1 matching id photo" in low
    assert "still analyzing" not in low


def test_incomplete_with_hits_keeps_partial_caveat():
    msg = _build_summary_message(
        results=[{"document_type": "driver_license"}],
        is_complete=False, query="show ID photos",
        query_kind="id_photo_visual",
    )
                                                                
                                                               
    low = msg.lower()
    assert "search incomplete" in low
    assert "1 matching id photo" in low
    assert "still scanning" not in low


def test_envelope_surfaces_counters_for_empty_complete():
    find_result = {
        "complete": True,
        "query_kind": "id_photo_visual",
        "hits": [],
        "candidate_id_docs_count": 1,
        "name_mismatch_count": 1,
        "requested_person_name": "Louis Lodato",
        "coverage": {"weak_hits_dropped": 0},
    }
    raw = build_find_in_vault_envelope(
        query="find ID photo for Louis Lodato",
        find_result=find_result,
        key=b"\x00" * 32,
        rows_by_id={},
        thumbnail_fetcher=lambda fid: None,
    )
    env = json.loads(raw)
    assert env["count"] == 0
    assert env["is_complete"] is True
    assert env["candidate_id_docs_count"] == 1
    assert env["name_mismatch_count"] == 1
    assert env["requested_person_name"] == "Louis Lodato"
                              
    low = env["message"].lower()
    assert "louis lodato" in low
    assert "still analyzing" not in low


def test_envelope_message_when_complete_and_strict_no_person():


    find_result = {
        "complete": True,
        "query_kind": "id_photo_visual",
        "hits": [],
        "candidate_id_docs_count": 0,
        "name_mismatch_count": 0,
        "requested_person_name": None,
        "coverage": {"weak_hits_dropped": 0},
    }
    env = json.loads(build_find_in_vault_envelope(
        query="show me all ID photos",
        find_result=find_result,
        key=b"\x00" * 32,
        rows_by_id={},
        thumbnail_fetcher=lambda fid: None,
    ))
    assert env["message"] == (
        "I couldn't find any ID documents in your vault."
    )


def test_envelope_incomplete_empty_says_system_error():


    find_result = {
        "complete": False,
        "query_kind": "id_photo_visual",
        "hits": [],
        "candidate_id_docs_count": 0,
        "name_mismatch_count": 0,
        "coverage": {"weak_hits_dropped": 0},
    }
    env = json.loads(build_find_in_vault_envelope(
        query="show me all ID photos",
        find_result=find_result,
        key=b"\x00" * 32,
        rows_by_id={},
        thumbnail_fetcher=lambda fid: None,
    ))
    assert env["is_complete"] is False
    low = env["message"].lower()
    assert "something went wrong" in low
    assert "please try again" in low
    assert "still analyzing" not in low
    assert "search incomplete" not in low


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


def _patch_vision(monkeypatch, response_text: str):
    import vault_inspection_tools as vit

    def _fake(*, vault_id, key, file_id, question):
        return json.dumps({"analysis": response_text})

    monkeypatch.setattr(vit, "read_image_with_vision", _fake)


def test_find_in_vault_emits_counters_on_name_mismatch(monkeypatch):


    import vault_complete_search as vcs
    import main as main_mod

    img = _row_image(file_id="img-x", file_name="image2.jpg")
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: [img],
    )
    _patch_vision(
        monkeypatch,
        "This is a driver's license. The visible name is "
        "Kendra Chosen.",
    )

    raw = vcs.find_in_vault(
        vault_id="v", key=b"\x00" * 32,
        query="find me any ID photo that has the person name "
              "Louis Lodato",
        doc_kind="id_photo",
    )
    result = json.loads(raw)
    assert result["hits"] == []
    assert result["complete"] is True
    assert result["candidate_id_docs_count"] == 1
    assert result["name_mismatch_count"] == 1
    assert result["requested_person_name"] == "Louis Lodato"


def test_find_in_vault_no_id_at_all_keeps_counters_zero(monkeypatch):
    import vault_complete_search as vcs
    import main as main_mod

    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: [],
    )

    raw = vcs.find_in_vault(
        vault_id="v", key=b"\x00" * 32,
        query="show me all ID photos",
        doc_kind="id_photo",
    )
    result = json.loads(raw)
    assert result["candidate_id_docs_count"] == 0
    assert result["name_mismatch_count"] == 0
