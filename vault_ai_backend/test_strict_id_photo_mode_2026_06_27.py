

from __future__ import annotations

from vault_complete_search import (
    DOC_TYPE_DRIVER_LICENSE,
    DOC_TYPE_ID_PHOTO,
    DOC_TYPE_PASSPORT,
    DOC_TYPE_UNKNOWN,
    EVIDENCE_EXTRACTED_TEXT,
    EVIDENCE_IMAGE_VISION,
    EVIDENCE_OCR_TEXT,
    EVIDENCE_PDF_PAGE_VISION,
    QUERY_KIND_GENERIC,
    QUERY_KIND_ID_PHOTO_VISUAL,
    QUERY_KIND_ID_REFERENCE_TEXT,
    STRENGTH_STRONG_OCR_DOCUMENT,
    STRENGTH_VISUAL_CONFIRMED,
    STRENGTH_WEAK_TEXT_REFERENCE,
    _classification_strength,
    _classify_query_kind,
    _strong_ocr_document_for_type,
    _text_looks_like_id_form,
)


def test_insurance_policy_text_is_a_form():
    text = (
        "Insurance Policy: SAFECO Auto. Policy number: 1234567. "
        "Premium: $850. Driver license number required for "
        "verification: please provide DL number on renewal."
    )
    assert _text_looks_like_id_form(text) is True


def test_tax_form_4506_is_a_form():
    text = (
        "Form 4506-C Request for Transcript of Tax Return. "
        "Tax year: 2023. Please attach a copy of your driver "
        "license for identification."
    )
    assert _text_looks_like_id_form(text) is True


def test_renewal_notice_is_a_form():
    text = (
        "Renewal notice — your home insurance policy expires "
        "next month. Premium due: $1,420. Policyholder: "
        "John Doe. Driver license number on file."
    )
    assert _text_looks_like_id_form(text) is True


def test_dmv_card_layout_is_not_a_form():

    text = (
        "STATE OF NEW YORK\n"
        "DRIVER LICENSE\n"
        "DL # 123-456-789\n"
        "DOB 01-01-1980\n"
        "EXP 01-01-2030\n"
        "CLASS D\n"
        "Department of Motor Vehicles\n"
        "Holder: LOUIS IODATO\n"
        "ENDORSEMENTS: NONE  RESTRICTIONS: NONE"
    )
    assert _text_looks_like_id_form(text) is False


def test_actual_drivers_license_text_passes_strong_ocr():
    text = (
        "STATE OF NEW YORK DRIVER LICENSE\n"
        "DL# 123-456-789  CLASS D\n"
        "DOB 01-01-1980  EXP 01-01-2030\n"
        "Holder: LOUIS IODATO\n"
        "Department of Motor Vehicles"
    )
    assert _strong_ocr_document_for_type(
        text, DOC_TYPE_DRIVER_LICENSE,
    ) is True


def test_actual_passport_text_passes_strong_ocr():
    text = (
        "UNITED STATES OF AMERICA PASSPORT\n"
        "Passport No. 1234567\n"
        "Surname: IODATO\n"
        "Given Names: LOUIS\n"
        "Nationality: USA\n"
        "Date of Birth: 01 JAN 1980\n"
        "Place of Birth: New York, USA\n"
        "Date of Expiration: 01 JAN 2030\n"
        "Department of State"
    )
    assert _strong_ocr_document_for_type(text, DOC_TYPE_PASSPORT) is True


def test_actual_id_card_text_passes_strong_ocr():
    text = (
        "STATE OF NEW YORK NON-DRIVER IDENTIFICATION CARD\n"
        "ID Number: 123-456-789\n"
        "DOB 01-01-1980\n"
        "Issued by Department of Motor Vehicles"
    )
    assert _strong_ocr_document_for_type(text, DOC_TYPE_ID_PHOTO) is True


def test_insurance_pdf_mentioning_license_fails_strong_ocr():


    text = (
        "Auto Insurance Policy — SAFECO\n"
        "Policy Number: ABC-12345\n"
        "Premium: $850.00\n"
        "Coverage period: 2026-01-01 to 2026-12-31\n"
        "Insured drivers: Louis Iodato (DL# 123-456-789)\n"
        "Please provide a copy of your driver license on renewal."
    )
    assert _strong_ocr_document_for_type(
        text, DOC_TYPE_DRIVER_LICENSE,
    ) is False


def test_form_4506_requesting_id_fails_strong_ocr():
    text = (
        "Form 4506-C Request for Transcript of Tax Return. "
        "Tax year: 2023. We need a copy of your driver license "
        "to verify your identity."
    )
    assert _strong_ocr_document_for_type(
        text, DOC_TYPE_DRIVER_LICENSE,
    ) is False


def test_email_asking_to_provide_id_fails_strong_ocr():
    text = (
        "Dear customer, please send a scan of your driver "
        "license to verify your account. Best regards, Support."
    )
    assert _strong_ocr_document_for_type(
        text, DOC_TYPE_DRIVER_LICENSE,
    ) is False


def test_random_text_file_with_id_words_fails_strong_ocr():
    text = (
        "Random notes about driver license rules and ID "
        "requirements for renting a car."
    )
    assert _strong_ocr_document_for_type(
        text, DOC_TYPE_DRIVER_LICENSE,
    ) is False


def test_unknown_doc_type_always_fails_strong_ocr():
    text = (
        "STATE OF NEW YORK DRIVER LICENSE\n"
        "DOB 01-01-1980\n"
        "Department of Motor Vehicles"
    )
    assert _strong_ocr_document_for_type(
        text, DOC_TYPE_UNKNOWN,
    ) is False


def test_image_vision_with_id_class_doc_type_is_visual_confirmed():
    s = _classification_strength(
        evidence_type=EVIDENCE_IMAGE_VISION,
        doc_type=DOC_TYPE_DRIVER_LICENSE,
    )
    assert s == STRENGTH_VISUAL_CONFIRMED


def test_pdf_page_vision_with_id_class_doc_type_is_visual_confirmed():
    s = _classification_strength(
        evidence_type=EVIDENCE_PDF_PAGE_VISION,
        doc_type=DOC_TYPE_PASSPORT,
    )
    assert s == STRENGTH_VISUAL_CONFIRMED


def test_image_vision_with_unknown_doc_type_is_weak():
    s = _classification_strength(
        evidence_type=EVIDENCE_IMAGE_VISION,
        doc_type=DOC_TYPE_UNKNOWN,
    )
    assert s == STRENGTH_WEAK_TEXT_REFERENCE


def test_extracted_text_with_strong_ocr_text_is_strong_ocr():
    text = (
        "STATE OF NEW YORK DRIVER LICENSE\n"
        "DL# 123-456-789  DOB 01-01-1980  EXP 01-01-2030\n"
        "Department of Motor Vehicles"
    )
    s = _classification_strength(
        evidence_type=EVIDENCE_EXTRACTED_TEXT,
        doc_type=DOC_TYPE_DRIVER_LICENSE,
        text_for_strength_check=text,
    )
    assert s == STRENGTH_STRONG_OCR_DOCUMENT


def test_extracted_text_insurance_pdf_is_weak_reference():
    text = (
        "Auto Insurance Policy. Policy Number: ABC-12345. "
        "Premium: $850. Driver license number: 123-456-789. "
        "Please provide a copy on renewal."
    )
    s = _classification_strength(
        evidence_type=EVIDENCE_EXTRACTED_TEXT,
        doc_type=DOC_TYPE_DRIVER_LICENSE,
        text_for_strength_check=text,
    )
    assert s == STRENGTH_WEAK_TEXT_REFERENCE


def test_extracted_text_without_body_is_weak_reference():
    s = _classification_strength(
        evidence_type=EVIDENCE_EXTRACTED_TEXT,
        doc_type=DOC_TYPE_DRIVER_LICENSE,
        text_for_strength_check=None,
    )
    assert s == STRENGTH_WEAK_TEXT_REFERENCE


def test_show_all_id_photos_routes_to_strict_visual():
    qk = _classify_query_kind(
        query="show me all ID photos I have in my vault",
        is_id_class=True,
    )
    assert qk == QUERY_KIND_ID_PHOTO_VISUAL


def test_find_my_passport_routes_to_strict_visual():
    qk = _classify_query_kind(
        query="find passport image", is_id_class=True,
    )
    assert qk == QUERY_KIND_ID_PHOTO_VISUAL


def test_show_my_driver_license_routes_to_strict_visual():
    qk = _classify_query_kind(
        query="show my driver license", is_id_class=True,
    )
    assert qk == QUERY_KIND_ID_PHOTO_VISUAL


def test_find_identity_card_routes_to_strict_visual():
    qk = _classify_query_kind(
        query="find identity card", is_id_class=True,
    )
    assert qk == QUERY_KIND_ID_PHOTO_VISUAL


def test_documents_that_mention_license_routes_to_reference_mode():
    qk = _classify_query_kind(
        query="documents that mention my driver license",
        is_id_class=True,
    )
    assert qk == QUERY_KIND_ID_REFERENCE_TEXT


def test_files_referencing_id_routes_to_reference_mode():
    qk = _classify_query_kind(
        query="files referencing my license number",
        is_id_class=True,
    )
    assert qk == QUERY_KIND_ID_REFERENCE_TEXT


def test_non_id_query_routes_to_generic():
    qk = _classify_query_kind(
        query="show me my tax returns", is_id_class=False,
    )
    assert qk == QUERY_KIND_GENERIC


def _stub_rows(*rows):


    return list(rows)


def _row(*, file_id, file_name, extracted_text,
         content_type="application/pdf",
         saved_name=None):
    return {
        "id": file_id,
        "file_name": file_name,
        "saved_name": saved_name or file_name,
        "extracted_text": extracted_text,
        "extracted_text_status": "complete",
        "content_type": content_type,
        "encrypted_file_data": None,
        "storage_mode": "inline",
    }


def test_strict_mode_drops_insurance_pdf_keeps_real_dl(monkeypatch):


    import vault_complete_search as vcs

    insurance = _row(
        file_id="ins-1",
        file_name="auto insurance.pdf",
        extracted_text=(
            "Auto Insurance Policy — SAFECO\n"
            "Policy Number: ABC-12345\n"
            "Premium: $850.00\n"
            "Insured drivers: Louis Iodato (DL# 123-456-789)\n"
            "Please provide a copy of your driver license on renewal."
        ),
    )
    real_dl = _row(
        file_id="dl-1",
        file_name="scanned_dl.pdf",
        extracted_text=(
            "STATE OF NEW YORK DRIVER LICENSE\n"
            "DL# 123-456-789  CLASS D\n"
            "DOB 01-01-1980  EXP 01-01-2030\n"
            "Holder: LOUIS IODATO\n"
            "Department of Motor Vehicles"
        ),
    )

    monkeypatch.setattr(
        vcs, "_decrypt_pdf_bytes",
        lambda row, key: None,                             
    )

                                                                  
    import main as main_mod
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: _stub_rows(insurance, real_dl),
    )

    import json as _json
    raw = vcs.find_in_vault(
        vault_id="v-x", key=b"\x00" * 32,
        query="show me all ID photos I have in my vault",
        doc_kind="id_photo",
    )
    result = _json.loads(raw)
    assert result["query_kind"] == QUERY_KIND_ID_PHOTO_VISUAL
    surviving_ids = {h["file_id"] for h in result["hits"]}
    assert "ins-1" not in surviving_ids, (
        "auto insurance.pdf must be dropped by strict id_photo_visual filter"
    )
    assert "dl-1" in surviving_ids
    assert result["coverage"]["weak_hits_dropped"] >= 1


def test_reference_mode_keeps_insurance_pdf(monkeypatch):


    import vault_complete_search as vcs
    import main as main_mod

    insurance = _row(
        file_id="ins-2",
        file_name="auto insurance.pdf",
        extracted_text=(
            "Auto Insurance Policy. Policy Number: ABC-12345. "
            "Premium: $850. Insured driver license number: "
            "123-456-789. Please provide a copy on renewal."
        ),
    )
    monkeypatch.setattr(
        vcs, "_decrypt_pdf_bytes",
        lambda row, key: None,
    )
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: _stub_rows(insurance),
    )

    import json as _json
    raw = vcs.find_in_vault(
        vault_id="v-x", key=b"\x00" * 32,
        query="documents that mention my driver license",
        doc_kind="driver_license",
    )
    result = _json.loads(raw)
    assert result["query_kind"] == QUERY_KIND_ID_REFERENCE_TEXT
    surviving_ids = {h["file_id"] for h in result["hits"]}
    assert "ins-2" in surviving_ids


def test_strict_mode_drops_text_file_mentioning_id(monkeypatch):
    import vault_complete_search as vcs
    import main as main_mod

    text_file = _row(
        file_id="txt-1",
        file_name="my_notes.txt",
        extracted_text=(
            "Reminder: pack driver license and passport for the trip."
        ),
        content_type="text/plain",
    )
    monkeypatch.setattr(
        vcs, "_decrypt_pdf_bytes",
        lambda row, key: None,
    )
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: _stub_rows(text_file),
    )

    import json as _json
    raw = vcs.find_in_vault(
        vault_id="v-x", key=b"\x00" * 32,
        query="show me all ID photos I have in my vault",
        doc_kind="id_photo",
    )
    result = _json.loads(raw)
    surviving_ids = {h["file_id"] for h in result["hits"]}
    assert "txt-1" not in surviving_ids


def test_strict_mode_accepts_visual_confirmed_pdf_page_vision_hit(monkeypatch):


    import vault_complete_search as vcs
    import main as main_mod
    import vault_pdf_page_vision as vpv

    scanned_dl = _row(
        file_id="pdf-1",
        file_name="scanned_dl.pdf",
        extracted_text=None,
        content_type="application/pdf",
    )
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: _stub_rows(scanned_dl),
    )
                                                         
    monkeypatch.setattr(
        vcs, "_decrypt_pdf_bytes",
        lambda row, key: b"%PDF-stubbed",
    )
                                                                
                                       
    def _fake_inspect(*, file_id, pdf_bytes, question,
                     max_pages, dpi=144, vision_callable=None):
        return {
            "pages_inspected": 1,
            "total_pages":     1,
            "budget_exceeded": False,
            "page_results": [{
                "page_index": 0,
                "analysis": (
                    "This is a driver's license. "
                    "The name visible on it is LOUIS IODATO."
                ),
            }],
        }
    monkeypatch.setattr(
        vpv, "inspect_pdf_pages_with_vision", _fake_inspect,
    )

    import json as _json
    raw = vcs.find_in_vault(
        vault_id="v-x", key=b"\x00" * 32,
        query="show me all ID photos I have in my vault",
        doc_kind="id_photo",
    )
    result = _json.loads(raw)
    surviving_ids = {h["file_id"] for h in result["hits"]}
    assert "pdf-1" in surviving_ids
    pdf_hit = next(h for h in result["hits"] if h["file_id"] == "pdf-1")
    assert pdf_hit["classification_strength"] == STRENGTH_VISUAL_CONFIRMED
    assert pdf_hit["evidence_type"] == EVIDENCE_PDF_PAGE_VISION


def test_strict_mode_accepts_strong_ocr_dl_text_hit(monkeypatch):


    import vault_complete_search as vcs
    import main as main_mod

    dl_text = _row(
        file_id="ocr-dl-1",
        file_name="dl_text.pdf",
        extracted_text=(
            "STATE OF NEW YORK DRIVER LICENSE\n"
            "DL# 123-456-789  CLASS D\n"
            "DOB 01-01-1980  EXP 01-01-2030\n"
            "Holder: LOUIS IODATO\n"
            "Department of Motor Vehicles"
        ),
    )
    monkeypatch.setattr(
        vcs, "_decrypt_pdf_bytes",
        lambda row, key: None,
    )
    monkeypatch.setattr(
        main_mod, "_list_uploaded_files_for_credential_search",
        lambda vid, k: _stub_rows(dl_text),
    )

    import json as _json
    raw = vcs.find_in_vault(
        vault_id="v-x", key=b"\x00" * 32,
        query="show me all ID photos I have in my vault",
        doc_kind="id_photo",
    )
    result = _json.loads(raw)
    surviving_ids = {h["file_id"] for h in result["hits"]}
    assert "ocr-dl-1" in surviving_ids
    hit = next(h for h in result["hits"] if h["file_id"] == "ocr-dl-1")
    assert hit["classification_strength"] == STRENGTH_STRONG_OCR_DOCUMENT


def test_envelope_carries_query_kind_and_strength():
    import json
    from vault_chat_result_cards import build_find_in_vault_envelope

    find_result = {
        "complete": True,
        "query_kind": QUERY_KIND_ID_PHOTO_VISUAL,
        "hits": [{
            "file_id":       "dl-1",
            "file_name":     "scanned_dl.pdf",
            "file_kind":     "pdf",
            "evidence_type": EVIDENCE_PDF_PAGE_VISION,
            "match_type":    "vision",
            "document_type": DOC_TYPE_DRIVER_LICENSE,
            "matched_name":  "Louis Iodato",
            "confidence":    0.86,
            "evidence":      "vision: driver license, name Louis Iodato",
            "classification_strength": STRENGTH_VISUAL_CONFIRMED,
        }],
        "coverage": {"weak_hits_dropped": 0},
    }
    env = json.loads(build_find_in_vault_envelope(
        query="show me all ID photos I have in my vault",
        find_result=find_result,
        key=b"\x00" * 32,
        rows_by_id={"dl-1": {
            "content_type": "application/pdf",
            "saved_name":   "scanned_dl.pdf",
        }},
        thumbnail_fetcher=lambda fid: None,
    ))
    assert env["query_kind"] == QUERY_KIND_ID_PHOTO_VISUAL
    assert env["results"][0]["classification_strength"] == \
        STRENGTH_VISUAL_CONFIRMED


def test_envelope_summary_handles_weak_only_empty_state():


    import json
    from vault_chat_result_cards import build_find_in_vault_envelope

    find_result = {
        "complete": True,
        "query_kind": QUERY_KIND_ID_PHOTO_VISUAL,
        "hits": [],
        "coverage": {"weak_hits_dropped": 16},
    }
    env = json.loads(build_find_in_vault_envelope(
        query="show me all ID photos I have in my vault",
        find_result=find_result,
        key=b"\x00" * 32,
        rows_by_id={},
        thumbnail_fetcher=lambda fid: None,
    ))
    msg = env["message"].lower()
                                                           
                                                               
    assert (
        "actual id" in msg
        or "couldn't find" in msg
        or "no matching id" in msg
    )
    assert "mention" in msg or "documents" in msg
