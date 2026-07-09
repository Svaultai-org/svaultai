

from __future__ import annotations

import json

from vault_chat_result_cards import (
    COPY_VERSION,
    SCHEMA_VERSION,
    build_find_in_vault_envelope,
)


def test_find_in_vault_envelope_carries_version_markers_empty():
    find_result = {
        "complete": True,
        "hits": [],
        "query_kind": "id_photo_visual",
    }
    env = json.loads(build_find_in_vault_envelope(
        query="find me an ID photo for Bob Smith",
        find_result=find_result,
        key=b"\x00" * 32,
        rows_by_id={},
        thumbnail_fetcher=lambda fid: None,
    ))
    assert env["type"] == "file_search_results"
    assert env["schema_version"] == "file_search_results.v2"
    assert env["copy_version"] == "sharp_empty_state_2026_06_28"
                                                         
                         
    assert env["is_complete"] is True
    assert env["count"] == 0


def test_find_in_vault_envelope_version_markers_with_hits():
    find_result = {
        "complete": True,
        "hits": [{
            "file_id":       "h1",
            "file_name":     "scanned.pdf",
            "file_kind":     "pdf",
            "evidence_type": "pdf_page_vision",
            "match_type":    "vision",
            "document_type": "driver_license",
            "matched_name":  "Louis Iodato",
            "confidence":    0.86,
            "evidence":      "vision: driver license",
            "classification_strength": "visual_confirmed",
            "match_status": "exact_name_match",
        }],
        "query_kind": "id_photo_visual",
    }
    env = json.loads(build_find_in_vault_envelope(
        query="show me all ID photos",
        find_result=find_result,
        key=b"\x00" * 32,
        rows_by_id={"h1": {"content_type": "application/pdf"}},
        thumbnail_fetcher=lambda fid: None,
    ))
    assert env["schema_version"] == SCHEMA_VERSION
    assert env["copy_version"] == COPY_VERSION
    assert env["is_complete"] is True
    assert env["count"] == 1


def test_constants_are_singleton_source_of_truth():

    assert SCHEMA_VERSION == "file_search_results.v2"
    assert COPY_VERSION == "sharp_empty_state_2026_06_28"


def test_search_files_about_envelope_also_carries_versions():
    import main
    raw = main._build_file_search_envelope(
        query="ghost",
        results=[],
        message="I didn't find any files about \"ghost\".",
    )
    env = json.loads(raw)
    assert env["type"] == "file_search_results"
    assert env["schema_version"] == "file_search_results.v2"
    assert env["copy_version"] == "sharp_empty_state_2026_06_28"
                                                                   
                                                                
    assert env["is_complete"] is True


def test_search_files_about_envelope_with_results_keeps_versions():
    import main
    raw = main._build_file_search_envelope(
        query="wells",
        results=[{
            "file_id": "f1",
            "file_name": "doc.pdf",
            "match_type": "filename",
            "match_reason": "filename match: doc.pdf",
            "confidence": "weak",
        }],
        message="I found 1 file about \"wells\".",
    )
    env = json.loads(raw)
    assert env["schema_version"] == SCHEMA_VERSION
    assert env["copy_version"] == COPY_VERSION


def test_envelope_carries_all_log_line_fields():


    env = json.loads(build_find_in_vault_envelope(
        query="x",
        find_result={"complete": True, "hits": []},
        key=b"\x00" * 32,
        rows_by_id={},
        thumbnail_fetcher=lambda fid: None,
    ))
    for required in (
        "type", "schema_version", "copy_version",
        "is_complete", "count",
    ):
        assert required in env, f"missing wire field: {required}"
