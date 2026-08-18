

from __future__ import annotations

import json

import pytest

from vault_complete_search import (
    DEFAULT_FUZZY_DISTANCE,
    MATCH_EXACT_TEXT,
    MATCH_FUZZY_TEXT,
    MATCH_VISION,
    MAX_VISION_INSPECTIONS,
    exact_substring_match,
    find_in_vault,
    fuzzy_token_match,
)


VAULT = "33333333-aaaa-bbbb-cccc-dddddddddddd"
KEY32 = b"\x00" * 32


def test_exact_substring_match_case_insensitive():
    assert exact_substring_match(
        "Louis Lodato",
        "Driver license issued to LOUIS LODATO on 2024-01-01",
    )
    assert exact_substring_match(
        "louis lodato",
        "Card holder: Louis Lodato",
    )
    assert not exact_substring_match(
        "Louis Lodato", "Mary Smith / Member ID 4421",
    )


def test_fuzzy_token_match_handles_ocr_l_vs_i_drift():


    assert fuzzy_token_match(
        "Louis Lodato",
        "Name on the card: Louis Iodato",
        max_distance=2,
    )
    assert fuzzy_token_match(
        "Louis Iodato",
        "Louis Lodato — driving license",
        max_distance=2,
    )


def test_fuzzy_token_match_rejects_distant_haystacks():


    assert not fuzzy_token_match(
        "Louis Lodato", "Marcus Pharmacy receipts", max_distance=2,
    )
    assert not fuzzy_token_match(
        "Louis Lodato", "Apple Card statement", max_distance=2,
    )


def test_fuzzy_token_match_requires_every_query_token():


    assert not fuzzy_token_match(
        "Louis Lodato", "Driver license for Louis Smith",
        max_distance=2,
    )


def test_fuzzy_token_match_ignores_short_tokens():


    assert not fuzzy_token_match("a", "Driver license for Louis Lodato")


_FAKE_FILES = {
    "happy_id_jpg": {
        "id": "img-1",
        "file_name": "drivers_license.jpg",
        "saved_name": "drivers_license.jpg",
        "content_type": "image/jpeg",
        "asset_type": "image",
        "extracted_text": (
            "State of New York Driver License. Holder: LOUIS LODATO. "
            "DOB: 01/01/1980. Class D."
        ),
        "relative_path": "",
        "created_at": None,
    },
    "ocr_drift_pdf": {
        "id": "pdf-1",
        "file_name": "scanned_id.pdf",
        "saved_name": "scanned_id.pdf",
        "content_type": "application/pdf",
        "asset_type": "document",
        "extracted_text": (
            "DRIVER LICENSE STATE OF NEW YORK Holder LOUIS IODATO "
            "DOB 1980-01-01"
        ),
        "relative_path": "",
        "created_at": None,
    },
    "unrelated_pdf": {
        "id": "pdf-2",
        "file_name": "tax_return.pdf",
        "saved_name": "tax_return.pdf",
        "content_type": "application/pdf",
        "asset_type": "document",
        "extracted_text": (
            "FORM 1040. TAXPAYER: SARAH O'BRIEN. WAGES: $42,000."
        ),
        "relative_path": "",
        "created_at": None,
    },
    "image_no_text": {
        "id": "img-2",
        "file_name": "passport_photo.png",
        "saved_name": "passport_photo.png",
        "content_type": "image/png",
        "asset_type": "image",
        "extracted_text": None,                 
        "relative_path": "",
        "created_at": None,
    },
    "audio_unrelated": {
        "id": "wav-1",
        "file_name": "meeting.wav",
        "saved_name": "meeting.wav",
        "content_type": "audio/wav",
        "asset_type": "audio",
        "extracted_text": "Transcript: Louis Lodato says hi.",
        "relative_path": "",
        "created_at": None,
    },
}


def _install_file_list(monkeypatch, rows: list[dict]):
    def _fake_list(vault_id, key):
        return [dict(r) for r in rows]
    monkeypatch.setattr(
        "main._list_uploaded_files_for_credential_search",
        _fake_list, raising=True,
    )


def _install_vision_stub(monkeypatch, response_by_file_id: dict[str, str]):


    def _fake_vision(*, vault_id, key, file_id, question):
        text = response_by_file_id.get(file_id, "")
        return json.dumps({
            "file_id":   file_id,
            "file_name": "",
            "analysis":  text,
            "model":     "fake-vision",
        })
    monkeypatch.setattr(
        "vault_inspection_tools.read_image_with_vision",
        _fake_vision, raising=True,
    )


def test_find_in_vault_finds_exact_text_match(monkeypatch):


    _install_file_list(monkeypatch, [_FAKE_FILES["happy_id_jpg"]])
    _install_vision_stub(monkeypatch, {})
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="Louis Lodato", doc_kind="id_photo",
    ))
    assert out["complete"] is True
    assert len(out["hits"]) == 1
    hit = out["hits"][0]
    assert hit["file_id"] == "img-1"
    assert hit["match_type"] == MATCH_EXACT_TEXT
    assert hit["file_name"] == "drivers_license.jpg"
    assert "LOUIS LODATO" in hit["evidence"]


def test_find_in_vault_finds_fuzzy_match_on_ocr_drift(monkeypatch):


    _install_file_list(monkeypatch, [_FAKE_FILES["ocr_drift_pdf"]])
    _install_vision_stub(monkeypatch, {})
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="Louis Lodato", doc_kind="id",
    ))
    assert out["complete"] is True
    assert len(out["hits"]) == 1
    hit = out["hits"][0]
    assert hit["match_type"] == MATCH_FUZZY_TEXT
    assert hit["file_name"] == "scanned_id.pdf"


def test_find_in_vault_falls_back_to_vision_for_image_with_no_text(monkeypatch):


    _install_file_list(monkeypatch, [_FAKE_FILES["image_no_text"]])
    _install_vision_stub(monkeypatch, {
        "img-2": (
            "Yes — the image is a passport photo for "
            "Louis Lodato. Date of birth visible."
        ),
    })
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="Louis Lodato", doc_kind="photo",
    ))
    assert out["complete"] is True
    assert len(out["hits"]) == 1
    hit = out["hits"][0]
    assert hit["file_id"] == "img-2"
    assert hit["match_type"] == MATCH_VISION
    assert "Louis Lodato" in hit["evidence"]
    assert out["files_via_vision"] == 1


def test_find_in_vault_vision_rejects_negated_response(monkeypatch):


    _install_file_list(monkeypatch, [_FAKE_FILES["image_no_text"]])
    _install_vision_stub(monkeypatch, {
        "img-2": (
            "I do not see Louis Lodato in this image. "
            "It appears to be a stock photo."
        ),
    })
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="Louis Lodato", doc_kind="photo",
    ))
    assert out["hits"] == []
    assert out["complete"] is True
    assert out["files_via_vision"] == 0
    assert out["coverage"]["vision_budget_used"] == 1


def test_find_in_vault_dedupes_by_file_id(monkeypatch):


    _install_file_list(monkeypatch, [_FAKE_FILES["happy_id_jpg"]])
    _install_vision_stub(monkeypatch, {
        "img-1": "yes Louis Lodato is in the image",
    })
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="Louis Lodato", doc_kind="id_photo",
    ))
    assert len(out["hits"]) == 1
    assert out["files_via_text"] == 1
    assert out["files_via_vision"] == 0


def test_find_in_vault_skips_unrelated_kinds(monkeypatch):


    _install_file_list(monkeypatch, [
        _FAKE_FILES["audio_unrelated"],
        _FAKE_FILES["unrelated_pdf"],
    ])
    _install_vision_stub(monkeypatch, {})
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="Louis Lodato", doc_kind="id_photo",
    ))
                                                        
    assert out["hits"] == []
    assert out["coverage"]["skipped_unrelated"] == 1
    assert out["complete"] is True


def test_find_in_vault_empty_vault_returns_complete_no_hits(monkeypatch):


    _install_file_list(monkeypatch, [])
    _install_vision_stub(monkeypatch, {})
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32, query="Louis Lodato",
    ))
    assert out["hits"] == []
    assert out["complete"] is True
    assert out["coverage"]["total_relevant_files"] == 0


def test_find_in_vault_locks_on_bad_key():
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=b"short", query="Louis Lodato",
    ))
    assert out == {"error": "vault_locked"}


def test_find_in_vault_rejects_empty_query():
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32, query="   ",
    ))
    assert out == {"error": "empty_query"}


def test_find_in_vault_vision_budget_overflow_keeps_complete_true(monkeypatch):


    many_images = []
    for i in range(MAX_VISION_INSPECTIONS + 4):
        many_images.append({
            "id":            f"img-{i}",
            "file_name":     f"photo_{i}.jpg",
            "saved_name":    f"photo_{i}.jpg",
            "content_type":  "image/jpeg",
            "asset_type":    "image",
            "extracted_text": None,
            "relative_path": "",
            "created_at":    None,
        })
    _install_file_list(monkeypatch, many_images)
                                            
    _install_vision_stub(monkeypatch, {
        f"img-{i}": "no — this image does not show Louis Lodato"
        for i in range(len(many_images))
    })
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32, query="Louis Lodato",
        doc_kind="photo",
    ))
    assert out["hits"] == []
    assert out["coverage"]["vision_budget_used"] == MAX_VISION_INSPECTIONS
    assert out["coverage"]["total_relevant_files"] == (
        MAX_VISION_INSPECTIONS + 4
    )
                                                             
                                                          
    assert out["complete"] is True
    assert out["partial_inspection"] is True
    assert out["coverage"]["partial_inspection"] is True


def test_find_in_vault_early_exits_after_text_hit_when_no_image_text(monkeypatch):


    rows = [
        _FAKE_FILES["happy_id_jpg"],
                                                            
                                                            
        _FAKE_FILES["ocr_drift_pdf"],
    ]
    _install_file_list(monkeypatch, rows)
    _install_vision_stub(monkeypatch, {})
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32, query="Louis Lodato",
        doc_kind="id_photo",
    ))
    assert {h["file_id"] for h in out["hits"]} == {"img-1", "pdf-1"}
    assert out["files_via_vision"] == 0
    assert out["complete"] is True


def test_planner_allows_find_in_vault():
    from vault_planner import _VALID_TOOL_NAMES
    assert "find_in_vault" in _VALID_TOOL_NAMES


def test_planner_prompt_emits_find_in_vault_for_document_search():
    from vault_planner import PLANNER_SYSTEM_PROMPT
    assert "find_in_vault" in PLANNER_SYSTEM_PROMPT


def test_inspection_dispatch_carries_find_in_vault():
    from vault_inspection_tools import INSPECTION_DISPATCH
    assert "find_in_vault" in INSPECTION_DISPATCH
    assert callable(INSPECTION_DISPATCH["find_in_vault"])


def test_inspection_schema_carries_find_in_vault():
    from vault_inspection_tools import INSPECTION_FUNCTIONS
    names = [
        fn.get("function", {}).get("name") for fn in INSPECTION_FUNCTIONS
    ]
    assert "find_in_vault" in names
    schema = next(
        fn for fn in INSPECTION_FUNCTIONS
        if fn["function"]["name"] == "find_in_vault"
    )["function"]
    assert "query" in schema["parameters"]["properties"]
    assert schema["parameters"]["required"] == ["query"]


def test_find_in_vault_is_never_cacheable():


    from vault_tool_result_cache import (
        CACHEABLE_TOOLS, NEVER_CACHEABLE_TOOLS,
    )
    assert "find_in_vault" in NEVER_CACHEABLE_TOOLS
    assert "find_in_vault" not in CACHEABLE_TOOLS


def test_system_prompt_teaches_find_in_vault_flow():


    from tools import STATIC_VAULT_SYSTEM_PROMPT
    assert "find_in_vault" in STATIC_VAULT_SYSTEM_PROMPT
    assert "review is still in progress" in STATIC_VAULT_SYSTEM_PROMPT
                                                       
                                                         
    assert "complete: true" in STATIC_VAULT_SYSTEM_PROMPT


def test_ai_stream_forces_find_in_vault_for_document_search():


    with open("main.py", encoding="utf-8") as f:
        src = f.read()
    assert 'intent == "document_search"' in src
    assert '_forced_tool_name = "find_in_vault"' in src


from vault_complete_search import (
    DOC_TYPE_DRIVER_LICENSE,
    DOC_TYPE_ID_PHOTO,
    DOC_TYPE_PASSPORT,
    DOC_TYPE_UNKNOWN,
    EVIDENCE_EXTRACTED_TEXT,
    EVIDENCE_IMAGE_VISION,
    classify_document_type_from_text,
    classify_document_type_from_vision,
    extract_name_from_text,
    extract_name_from_vision,
)


_TEXT_FILE_FIXTURES = [
    {
        "id": "txt-crypt",
        "file_name": "crypt.txt",
        "saved_name": "crypt.txt",
        "content_type": "text/plain",
        "asset_type": None,
        "extracted_text": (
            "John Doe ID: 9988-2211-7766\n"
            "Password hash: $argon2id$..."
        ),
        "relative_path": "", "created_at": None,
    },
    {
        "id": "txt-aol",
        "file_name": "aolreal_emails-unchecked.txt",
        "saved_name": "aolreal_emails-unchecked.txt",
        "content_type": "text/plain",
        "asset_type": None,
        "extracted_text": (
            "userid_42@aol.com\n"
            "another.id@aol.com — Louis Lodato\n"
        ),
        "relative_path": "", "created_at": None,
    },
    {
        "id": "txt-swift",
        "file_name": "swiftmail.txt",
        "saved_name": "swiftmail.txt",
        "content_type": "text/plain",
        "asset_type": None,
        "extracted_text": (
            "Swift ID: AAAABBCC-1234\n"
            "Beneficiary: Louis Iodato\n"
        ),
        "relative_path": "", "created_at": None,
    },
]


def test_show_all_id_photos_rejects_text_files(monkeypatch):


    _install_file_list(monkeypatch, _TEXT_FILE_FIXTURES)
    _install_vision_stub(monkeypatch, {})
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="show me all ID photos I have in my vault",
                                                            
                                                    
    ))
    assert out["is_id_class_search"] is True
    assert out["doc_kind"] == "id_photo"
    assert out["hits"] == []
    assert out["complete"] is True
                                                       
    assert out["coverage"]["skipped_unrelated"] == len(_TEXT_FILE_FIXTURES)


def test_id_photo_query_rejects_text_files_even_with_name_match(monkeypatch):


    _install_file_list(monkeypatch, [_TEXT_FILE_FIXTURES[2]])
    _install_vision_stub(monkeypatch, {})
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="find ID photo for Louis Lodato",
    ))
    assert out["hits"] == []
    assert out["is_id_class_search"] is True


def test_id_photo_query_accepts_classified_id_text(monkeypatch):


    _install_file_list(monkeypatch, [_FAKE_FILES["happy_id_jpg"]])
    _install_vision_stub(monkeypatch, {})
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="show me all ID photos",
    ))
    assert len(out["hits"]) == 1
    hit = out["hits"][0]
    assert hit["file_kind"] == "image"
    assert hit["document_type"] == DOC_TYPE_DRIVER_LICENSE
    assert hit["evidence_type"] == EVIDENCE_EXTRACTED_TEXT
                                                         
    assert hit["matched_name"] == "Louis Lodato"


def test_doc_kind_auto_inferred_from_category_keywords():


    from vault_complete_search import _infer_doc_kind_from_query
    assert _infer_doc_kind_from_query("show me all ID photos") == "id_photo"
    assert _infer_doc_kind_from_query("find my passport") == "id_photo"
    assert _infer_doc_kind_from_query("driver license please") == "id_photo"
    assert _infer_doc_kind_from_query(
        "find me DL of the name Louis Lodato"
    ) == "id_photo"
    assert _infer_doc_kind_from_query(
        "driving licence for Louis Lodato"
    ) == "id_photo"
    assert _infer_doc_kind_from_query("ID card for Louis") == "id_photo"


def test_doc_kind_not_inferred_for_plain_text_search():


    from vault_complete_search import _infer_doc_kind_from_query
    assert _infer_doc_kind_from_query("find Louis Lodato") is None
    assert _infer_doc_kind_from_query("show me my tax return") is None
    assert _infer_doc_kind_from_query("Union Bank statement") is None


def test_entity_extraction_strips_category_words():


    from vault_complete_search import _extract_entity_from_query
    out = _extract_entity_from_query(
        "find ID photo for Louis Lodato",
        is_id_class_search=True,
    )
    assert out == "louis lodato"


def test_driver_license_aliases_do_not_pollute_person_query():
    from vault_complete_search import _extract_entity_from_query

    for query in (
        "find me DL of the name Louis Lodato",
        "find the driver's license for Louis Lodato",
        "find the driving licence for Louis Lodato",
    ):
        assert _extract_entity_from_query(
            query,
            is_id_class_search=True,
        ) == "louis lodato"


def test_entity_extraction_yields_empty_for_broad_query():


    from vault_complete_search import _extract_entity_from_query
    out = _extract_entity_from_query(
        "show me all ID photos I have in my vault",
        is_id_class_search=True,
    )
    assert out == ""


def test_entity_extraction_passes_through_for_generic_search():

    from vault_complete_search import _extract_entity_from_query
    out = _extract_entity_from_query(
        "find Louis Lodato", is_id_class_search=False,
    )
    assert out == "find Louis Lodato"


def test_classify_driver_license_text():
    text = (
        "STATE OF NEW YORK Driver License Holder: LOUIS LODATO "
        "DOB: 01/01/1980 License Class D"
    )
    assert classify_document_type_from_text(text) == DOC_TYPE_DRIVER_LICENSE


def test_classify_passport_text():
    text = (
        "UNITED STATES OF AMERICA Passport Number: 123456789 "
        "Place of birth: New York"
    )
    assert classify_document_type_from_text(text) == DOC_TYPE_PASSPORT


def test_classify_id_card_text():
    text = (
        "National ID Card. ID Number: 0000-1111-2222. "
        "Holder: Louis Lodato."
    )
    assert classify_document_type_from_text(text) == DOC_TYPE_ID_PHOTO


def test_classify_unknown_for_random_text_files():


    for fixture in _TEXT_FILE_FIXTURES:
        assert classify_document_type_from_text(
            fixture["extracted_text"]
        ) == DOC_TYPE_UNKNOWN, (
            f"{fixture['file_name']} should classify as unknown"
        )


def test_classify_unknown_for_tax_return_text():


    text = "FORM 1040. TAXPAYER: SARAH O'BRIEN. WAGES: $42,000."
    assert classify_document_type_from_text(text) == DOC_TYPE_UNKNOWN


def test_extract_name_from_holder_label():
    text = "Driver License. Holder: LOUIS LODATO. DOB: 1980."
    assert extract_name_from_text(text) == "Louis Lodato"


def test_extract_name_from_issued_to_label():
    text = "Identity Card issued to Mary O'Brien. State: NY."
    assert extract_name_from_text(text) == "Mary O'brien"


def test_extract_name_from_name_label():
    text = "Passport. Name: Carlos Méndez. Country: MX."
                                                     
                    
    assert extract_name_from_text(text) == "Carlos Méndez"


def test_extract_name_returns_none_for_random_text():
    text = "Just a regular email between two people about lunch."
    assert extract_name_from_text(text) is None


def test_classify_vision_passport():
    text = "Yes, this image is a US passport for Louis Lodato."
    assert classify_document_type_from_vision(text) == DOC_TYPE_PASSPORT


def test_classify_vision_driver_license():
    text = "This is a driver's license. The name reads Louis Lodato."
    assert classify_document_type_from_vision(text) == DOC_TYPE_DRIVER_LICENSE


def test_classify_vision_negation_returns_unknown():
    text = "No, I do not see any ID document in this image."
    assert classify_document_type_from_vision(text) == DOC_TYPE_UNKNOWN


def test_classify_vision_unrelated_returns_unknown():
    text = "This appears to be a landscape photo of a beach."
    assert classify_document_type_from_vision(text) == DOC_TYPE_UNKNOWN


def test_extract_name_from_vision_text():
    text = "The driver license belongs to Louis Lodato."
    assert extract_name_from_vision(text) == "Louis Lodato"


def test_hit_carries_every_required_field(monkeypatch):


    _install_file_list(monkeypatch, [_FAKE_FILES["happy_id_jpg"]])
    _install_vision_stub(monkeypatch, {})
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="Louis Lodato", doc_kind="id_photo",
    ))
    assert len(out["hits"]) == 1
    hit = out["hits"][0]
    for f in (
        "file_id", "file_name", "file_kind",
        "evidence_type", "document_type",
        "matched_name", "confidence",
    ):
        assert f in hit, f"missing field {f!r}"
    assert isinstance(hit["confidence"], float)
    assert 0.0 <= hit["confidence"] <= 1.0


def test_id_class_search_in_envelope():


    pass                                                         


def test_doc_kind_explicit_id_photo_restricts_candidates(monkeypatch):


    rows = _TEXT_FILE_FIXTURES + [_FAKE_FILES["happy_id_jpg"]]
    _install_file_list(monkeypatch, rows)
    _install_vision_stub(monkeypatch, {})
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="Louis Lodato", doc_kind="id_photo",
    ))
    file_names = {h["file_name"] for h in out["hits"]}
    assert file_names == {"drivers_license.jpg"}
                                                        
    assert out["coverage"]["skipped_unrelated"] == 3


def test_broad_search_returns_all_classified_id_docs(monkeypatch):


    rows = [_FAKE_FILES["happy_id_jpg"], _FAKE_FILES["ocr_drift_pdf"]]
    _install_file_list(monkeypatch, rows)
    _install_vision_stub(monkeypatch, {})
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="show me all my ID photos",
    ))
    assert len(out["hits"]) == 2
    file_names = {h["file_name"] for h in out["hits"]}
    assert file_names == {"drivers_license.jpg", "scanned_id.pdf"}


def test_image_with_vision_passport_match(monkeypatch):


    _install_file_list(monkeypatch, [_FAKE_FILES["image_no_text"]])
    _install_vision_stub(monkeypatch, {
        "img-2": (
            "Yes — this image is a US passport. "
            "The name on the document is Louis Lodato. "
            "Date of birth visible."
        ),
    })
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="Louis Lodato", doc_kind="id_photo",
    ))
    assert len(out["hits"]) == 1
    hit = out["hits"][0]
    assert hit["file_kind"] == "image"
    assert hit["evidence_type"] == EVIDENCE_IMAGE_VISION
    assert hit["document_type"] == DOC_TYPE_PASSPORT
    assert hit["matched_name"] == "Louis Lodato"
    assert hit["confidence"] >= 0.85


def test_vision_must_classify_as_id_for_id_class_query(monkeypatch):


    _install_file_list(monkeypatch, [_FAKE_FILES["image_no_text"]])
    _install_vision_stub(monkeypatch, {
        "img-2": (
            "I see a landscape photo featuring Louis Lodato "
            "standing in front of a mountain."
        ),
    })
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="Louis Lodato", doc_kind="id_photo",
    ))
                                         
    assert out["hits"] == []
    assert out["complete"] is True


def test_no_id_photos_returns_complete_not_found(monkeypatch):


    _install_file_list(monkeypatch, _TEXT_FILE_FIXTURES)
    _install_vision_stub(monkeypatch, {})
    out = json.loads(find_in_vault(
        vault_id=VAULT, key=KEY32,
        query="show me my ID photos",
    ))
    assert out["hits"] == []
    assert out["complete"] is True
    assert out["is_id_class_search"] is True
