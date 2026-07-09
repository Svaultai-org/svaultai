

from __future__ import annotations

import json

from vault_complete_search import (
    DOC_TYPE_DRIVER_LICENSE,
    EVIDENCE_IMAGE_VISION,
    EVIDENCE_PDF_PAGE_VISION,
    MATCH_STATUS_EXACT_NAME_MATCH,
    MATCH_STATUS_FUZZY_NAME_MATCH,
    MATCH_STATUS_NAME_MISMATCH,
    MATCH_STATUS_NO_NAME_MATCH,
    PERSON_MATCH_ACCEPT,
    _compute_match_status,
    _pre_match_is_negated,
    extract_name_from_vision,
)


def test_name_extractor_picks_affirmative_name_not_negated_one():


    text = (
        "The visible name is Kendra Chosen. "
        "The document does not belong to Louis Lodato."
    )
    assert extract_name_from_vision(text) == "Kendra Chosen"


def test_name_extractor_skips_negated_belongs_to():
    text = (
        "This appears to be an ID document. The document does "
        "not belong to Louis Lodato."
    )
    assert extract_name_from_vision(text) is None


def test_name_extractor_skips_is_not_named():
    text = "The holder is not named Louis Lodato."
    assert extract_name_from_vision(text) is None


def test_name_extractor_skips_name_is_not():
    text = "The name on the card is not Louis Lodato."
    assert extract_name_from_vision(text) is None


def test_name_extractor_affirmative_belongs_to_still_works():
    text = "The card belongs to Louis Iodato."
    assert extract_name_from_vision(text) == "Louis Iodato"


def test_name_extractor_affirmative_after_negative_clause():


    text = (
        "This is not a US passport. "
        "The driver license belongs to Louis Iodato."
    )
    assert extract_name_from_vision(text) == "Louis Iodato"


def test_pre_match_negation_helper_window_stops_at_sentence_boundary():
    text = "Some random sentence. Holder: LOUIS IODATO"
                                                            
                                                             
    idx = text.index("LOUIS")
    assert _pre_match_is_negated(text, idx) is False


def test_pre_match_negation_helper_flags_does_not_belong_to():
    text = "Does not belong to Louis Lodato."
    idx = text.index("Louis")
    assert _pre_match_is_negated(text, idx) is True


def test_match_status_exact_when_names_equal():
    assert _compute_match_status(
        requested_name="Louis Lodato",
        visible_name="Louis Lodato",
        fuzzy_distance=2,
    ) == MATCH_STATUS_EXACT_NAME_MATCH


def test_match_status_exact_is_case_insensitive():
    assert _compute_match_status(
        requested_name="Louis Lodato",
        visible_name="LOUIS LODATO",
        fuzzy_distance=2,
    ) == MATCH_STATUS_EXACT_NAME_MATCH


def test_match_status_fuzzy_for_louis_iodato_vs_lodato():
    assert _compute_match_status(
        requested_name="Louis Lodato",
        visible_name="Louis Iodato",
        fuzzy_distance=2,
    ) == MATCH_STATUS_FUZZY_NAME_MATCH


def test_match_status_mismatch_when_completely_different():
    assert _compute_match_status(
        requested_name="Louis Lodato",
        visible_name="Kendra Chosen",
        fuzzy_distance=2,
    ) == MATCH_STATUS_NAME_MISMATCH


def test_match_status_no_name_when_visible_absent():
    assert _compute_match_status(
        requested_name="Louis Lodato",
        visible_name=None,
        fuzzy_distance=2,
    ) == MATCH_STATUS_NO_NAME_MATCH
    assert _compute_match_status(
        requested_name="Louis Lodato",
        visible_name="",
        fuzzy_distance=2,
    ) == MATCH_STATUS_NO_NAME_MATCH


def test_match_status_broad_search_returns_exact_when_name_present():


    assert _compute_match_status(
        requested_name="",
        visible_name="Kendra Chosen",
        fuzzy_distance=2,
    ) == MATCH_STATUS_EXACT_NAME_MATCH


def test_match_status_broad_search_no_name_when_none_extracted():
    assert _compute_match_status(
        requested_name="",
        visible_name=None,
        fuzzy_distance=2,
    ) == MATCH_STATUS_NO_NAME_MATCH


def test_person_match_accept_only_strong_bands():
    assert MATCH_STATUS_EXACT_NAME_MATCH in PERSON_MATCH_ACCEPT
    assert MATCH_STATUS_FUZZY_NAME_MATCH in PERSON_MATCH_ACCEPT
    assert MATCH_STATUS_NO_NAME_MATCH not in PERSON_MATCH_ACCEPT
    assert MATCH_STATUS_NAME_MISMATCH not in PERSON_MATCH_ACCEPT


def _stub_rows(*rows):
    return list(rows)


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


    from vault_inspection_tools import read_image_with_vision        
    import vault_inspection_tools as vit

    def _fake(*, vault_id, key, file_id, question):
        return json.dumps({"analysis": response_text})

    monkeypatch.setattr(vit, "read_image_with_vision", _fake)


def test_kendra_chosen_id_is_rejected_for_louis_lodato_query(monkeypatch):
    import vault_complete_search as vcs
    import main as main_mod

    img = _row_image(file_id="img-1", file_name="image2 (1).jpg")
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: _stub_rows(img),
    )
    _patch_vision(
        monkeypatch,
        "This is a driver's license. The visible name is "
        "Kendra Chosen. The document does not belong to Louis Lodato.",
    )

    raw = vcs.find_in_vault(
        vault_id="v", key=b"\x00" * 32,
        query="find me any ID photo that has the person name "
              "Louis Lodato",
        doc_kind="id_photo",
    )
    result = json.loads(raw)
    file_ids = {h["file_id"] for h in result["hits"]}
    assert "img-1" not in file_ids, (
        "Kendra Chosen's ID must NOT be returned for a "
        "'Louis Lodato' person-specific search"
    )


def test_kendra_chosen_id_surfaces_for_broad_search(monkeypatch):


    import vault_complete_search as vcs
    import main as main_mod

    img = _row_image(file_id="img-2", file_name="image2 (1).jpg")
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: _stub_rows(img),
    )
    _patch_vision(
        monkeypatch,
        "This is a driver's license. The visible name is "
        "Kendra Chosen.",
    )

    raw = vcs.find_in_vault(
        vault_id="v", key=b"\x00" * 32,
        query="show me all ID photos I have in my vault",
        doc_kind="id_photo",
    )
    result = json.loads(raw)
    surviving = [h for h in result["hits"] if h["file_id"] == "img-2"]
    assert len(surviving) == 1
    assert surviving[0]["matched_name"] == "Kendra Chosen"
    assert surviving[0]["match_status"] == MATCH_STATUS_EXACT_NAME_MATCH


def test_louis_iodato_id_accepted_for_louis_lodato_query(monkeypatch):


    import vault_complete_search as vcs
    import main as main_mod

    img = _row_image(file_id="img-3", file_name="real_dl.jpg")
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: _stub_rows(img),
    )
    _patch_vision(
        monkeypatch,
        "This is a driver's license. The name visible on it is "
        "LOUIS IODATO.",
    )

    raw = vcs.find_in_vault(
        vault_id="v", key=b"\x00" * 32,
        query="find ID photo for Louis Lodato",
        doc_kind="id_photo",
    )
    result = json.loads(raw)
    surviving = [h for h in result["hits"] if h["file_id"] == "img-3"]
    assert len(surviving) == 1
    assert surviving[0]["matched_name"] == "Louis Iodato"
    assert surviving[0]["match_status"] == MATCH_STATUS_FUZZY_NAME_MATCH


def test_nameless_dl_returns_no_hit_for_person_search(monkeypatch):


    import vault_complete_search as vcs
    import main as main_mod

    img = _row_image(file_id="img-4", file_name="unclear.jpg")
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: _stub_rows(img),
    )
    _patch_vision(
        monkeypatch,
        "This is a driver's license. The photo and details are "
        "too obscured to extract a name verbatim.",
    )

    raw = vcs.find_in_vault(
        vault_id="v", key=b"\x00" * 32,
        query="find ID photo for Louis Lodato",
        doc_kind="id_photo",
    )
    result = json.loads(raw)
    file_ids = {h["file_id"] for h in result["hits"]}
    assert "img-4" not in file_ids


def test_nameless_dl_surfaces_for_broad_search(monkeypatch):


    import vault_complete_search as vcs
    import main as main_mod

    img = _row_image(file_id="img-5", file_name="unclear.jpg")
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: _stub_rows(img),
    )
    _patch_vision(
        monkeypatch,
        "This is a driver's license. The photo and details are "
        "too obscured to extract a name verbatim.",
    )

    raw = vcs.find_in_vault(
        vault_id="v", key=b"\x00" * 32,
        query="show me all ID photos I have in my vault",
        doc_kind="id_photo",
    )
    result = json.loads(raw)
    surviving = [h for h in result["hits"] if h["file_id"] == "img-5"]
    assert len(surviving) == 1
    assert surviving[0]["matched_name"] is None
    assert surviving[0]["match_status"] == MATCH_STATUS_NO_NAME_MATCH


def test_matched_name_is_never_copied_from_query(monkeypatch):


    import vault_complete_search as vcs
    import main as main_mod

    img = _row_image(file_id="img-6", file_name="real_dl.jpg")
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: _stub_rows(img),
    )
    _patch_vision(
        monkeypatch,
        "This is a driver's license. The visible name is "
        "LOUIS IODATO.",
    )

    raw = vcs.find_in_vault(
        vault_id="v", key=b"\x00" * 32,
        query="find ID photo for Louis Lodato",
        doc_kind="id_photo",
    )
    result = json.loads(raw)
    surviving = [h for h in result["hits"] if h["file_id"] == "img-6"]
    assert len(surviving) == 1
                                                           
    assert surviving[0]["matched_name"] == "Louis Iodato"
    assert surviving[0]["matched_name"] != "Louis Lodato"


def test_envelope_surfaces_match_status_field():
    from vault_chat_result_cards import build_find_in_vault_envelope

    find_result = {
        "complete": True,
        "query_kind": "id_photo_visual",
        "hits": [{
            "file_id":       "img-7",
            "file_name":     "real_dl.jpg",
            "file_kind":     "image",
            "evidence_type": EVIDENCE_IMAGE_VISION,
            "match_type":    "vision",
            "document_type": DOC_TYPE_DRIVER_LICENSE,
            "matched_name":  "Louis Iodato",
            "confidence":    0.88,
            "evidence":      "vision: driver license",
            "classification_strength": "visual_confirmed",
            "match_status":  MATCH_STATUS_FUZZY_NAME_MATCH,
        }],
        "coverage": {"weak_hits_dropped": 0},
    }
    raw = build_find_in_vault_envelope(
        query="find ID photo for Louis Lodato",
        find_result=find_result,
        key=b"\x00" * 32,
        rows_by_id={"img-7": {"content_type": "image/jpeg"}},
        thumbnail_fetcher=lambda fid: None,
    )
    env = json.loads(raw)
    row = env["results"][0]
    assert row["match_status"] == MATCH_STATUS_FUZZY_NAME_MATCH
                                      
    assert row["matched_name"] == "Louis Iodato"


def test_contrastive_vision_blocked_by_negation_list(monkeypatch):


    from vault_complete_search import _vision_hit_phrase_matched
    text = (
        "This is a driver's license. The document does not "
        "belong to Louis Lodato."
    )
    assert _vision_hit_phrase_matched(text, "Louis Lodato") is False


def test_contrastive_is_not_named_blocked():
    from vault_complete_search import _vision_hit_phrase_matched
    text = "The holder is not named Louis Lodato."
    assert _vision_hit_phrase_matched(text, "Louis Lodato") is False
