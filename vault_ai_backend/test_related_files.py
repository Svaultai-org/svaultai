

from __future__ import annotations

import inspect
import unittest
from datetime import datetime, timedelta, timezone

from related_files import (
    CONFIDENCE_MEDIUM,
    CONFIDENCE_STRONG,
    CONFIDENCE_WEAK,
    REASON_FRONT_BACK_PAIR,
    REASON_SAME_CONTENT_HASH,
    REASON_SAME_DOC_TYPE,
    REASON_SAME_FOLDER,
    REASON_SAME_IMPORT_BATCH,
    REASON_SAME_PERSON_TOKEN,
    REASON_SAME_UPLOAD_SESSION,
    REASON_SHARED_TOKEN,
    RELATED_RENDER_HARD_CAP,
    detect_front_or_back,
    extract_person_token,
    find_related_with_reasons,
    folder_of,
    format_related_reply,
    is_meaningful_token,
    tokenise_filename,
)


def _file(
    *,
    id: str,
    file_name: str,
    saved_name: str | None = None,
    relative_path: str | None = None,
    import_id: str | None = None,
    content_sha256: str | None = None,
    detected_type: str | None = None,
    created_at: datetime | None = None,
) -> dict:
    return {
        "id": id,
        "file_name": file_name,
        "saved_name": saved_name,
        "relative_path": relative_path,
        "import_id": import_id,
        "content_sha256": content_sha256,
        "detected_type": detected_type,
        "created_at": created_at,
    }


class TokeniseFilenameTests(unittest.TestCase):
    def test_splits_on_space_underscore_hyphen(self):
        self.assertEqual(
            tokenise_filename("maureen id back.jpg"),
            ["maureen", "id", "back"],
        )
        self.assertEqual(
            tokenise_filename("Maureen-ID-Front.JPG"),
            ["maureen", "id", "front"],
        )
        self.assertEqual(
            tokenise_filename("screenshot_2024_05_07.png"),
            ["screenshot", "2024", "05", "07"],
        )

    def test_drops_trailing_extension_only(self):
                                                              
                                                             
        self.assertEqual(
            tokenise_filename("report.final.pdf"),
            ["report.final"],
        )

    def test_empty(self):
        self.assertEqual(tokenise_filename(""), [])
        self.assertEqual(tokenise_filename(None), [])


class IsMeaningfulTokenTests(unittest.TestCase):
    def test_keeps_real_words(self):
        for t in ("maureen", "passport", "statement", "tokyo"):
            self.assertTrue(is_meaningful_token(t), t)

    def test_rejects_generic_stopwords(self):
        for t in ("doc", "file", "image", "scan", "front", "back",
                  "jpg", "png", "pdf", "the", "of"):
            self.assertFalse(is_meaningful_token(t), t)

    def test_rejects_short_tokens(self):
        for t in ("a", "id", "no"):
            self.assertFalse(is_meaningful_token(t), t)

    def test_rejects_pure_numbers(self):
        for t in ("2024", "1", "07"):
            self.assertFalse(is_meaningful_token(t), t)


class DetectFrontOrBackTests(unittest.TestCase):
    def test_detects_front(self):
        self.assertEqual(
            detect_front_or_back("maureen id front.jpg"), "front",
        )

    def test_detects_back(self):
        self.assertEqual(
            detect_front_or_back("maureen id back.jpg"), "back",
        )

    def test_none_when_absent(self):
        self.assertIsNone(detect_front_or_back("passport.jpg"))
        self.assertIsNone(detect_front_or_back(""))
        self.assertIsNone(detect_front_or_back(None))


class ExtractPersonTokenTests(unittest.TestCase):
    def test_picks_first_token_as_person(self):
        self.assertEqual(
            extract_person_token("maureen id back.jpg"),
            "maureen",
        )

    def test_rejects_doc_type_first_token(self):
                                                                 
        self.assertIsNone(extract_person_token("passport.jpg"))
        self.assertIsNone(extract_person_token("invoice april.pdf"))

    def test_rejects_too_short(self):
        self.assertIsNone(extract_person_token("id back.jpg"))

    def test_rejects_generic_first_token(self):
        self.assertIsNone(extract_person_token("scan_001.jpg"))
        self.assertIsNone(extract_person_token("screenshot.png"))


class FolderOfTests(unittest.TestCase):
    def test_picks_directory_portion(self):
        self.assertEqual(folder_of("Bank/statement.pdf"), "Bank")
        self.assertEqual(
            folder_of("Family/Photos/maureen.jpg"),
            "Family/Photos",
        )

    def test_none_when_no_folder(self):
        self.assertIsNone(folder_of("loose.pdf"))
        self.assertIsNone(folder_of(None))
        self.assertIsNone(folder_of(""))


class FindRelatedScenariosTests(unittest.TestCase):

    def test_front_back_pair_is_strong(self):
        anchor = _file(id="a", file_name="maureen id back.jpg")
        other = _file(id="b", file_name="maureen id front.jpg")
        results = find_related_with_reasons(
            [anchor, other], anchor=anchor,
        )
        self.assertEqual(len(results), 1)
        r = results[0]
        codes = {x.code for x in r.reasons}
        self.assertIn(REASON_FRONT_BACK_PAIR, codes)
        self.assertEqual(r.confidence(), CONFIDENCE_STRONG)

    def test_front_back_pair_with_different_doc_does_not_fire(self):
                                                                  
                                                                  
        anchor = _file(id="a", file_name="id front.jpg")
        other = _file(id="b", file_name="passport back.jpg")
        results = find_related_with_reasons(
            [anchor, other], anchor=anchor,
        )
                                    
        codes_per_result = [
            {x.code for x in r.reasons} for r in results
        ]
                                        
        for codes in codes_per_result:
            self.assertNotIn(REASON_FRONT_BACK_PAIR, codes)

    def test_same_content_hash_is_strong(self):
        anchor = _file(
            id="a", file_name="statement.pdf",
            content_sha256="a" * 64,
        )
        other = _file(
            id="b", file_name="copy.pdf",
            content_sha256="a" * 64,
        )
        results = find_related_with_reasons(
            [anchor, other], anchor=anchor,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].confidence(), CONFIDENCE_STRONG)
        self.assertIn(
            REASON_SAME_CONTENT_HASH,
            {x.code for x in results[0].reasons},
        )

    def test_shared_person_token_is_medium(self):
        anchor = _file(id="a", file_name="maureen id back.jpg")
        other = _file(id="b", file_name="maureen passport.jpg")
        results = find_related_with_reasons(
            [anchor, other], anchor=anchor,
        )
        self.assertEqual(len(results), 1)
        codes = {x.code for x in results[0].reasons}
        self.assertIn(REASON_SAME_PERSON_TOKEN, codes)
        self.assertEqual(results[0].confidence(), CONFIDENCE_MEDIUM)

    def test_same_import_batch_alone_is_weak(self):
                                                                    
                                                                 
        anchor = _file(
            id="a", file_name="07f95dc4.jpg",
            import_id="batch-1",
        )
        other = _file(
            id="b", file_name="9b1de2af.png",
            import_id="batch-1",
        )
        results = find_related_with_reasons(
            [anchor, other], anchor=anchor,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].confidence(), CONFIDENCE_WEAK)
        self.assertEqual(
            {x.code for x in results[0].reasons},
            {REASON_SAME_IMPORT_BATCH},
        )

    def test_no_signal_no_result(self):
                                                              
                                                                     
        anchor = _file(
            id="a", file_name="07f95dc4.jpg",
            content_sha256="a" * 64,
        )
        other = _file(
            id="b", file_name="dac910b1.png",
            content_sha256="b" * 64,
        )
        results = find_related_with_reasons(
            [anchor, other], anchor=anchor,
        )
        self.assertEqual(results, [])

    def test_anchor_excluded_from_results(self):
        anchor = _file(id="a", file_name="maureen id back.jpg")
        results = find_related_with_reasons(
            [anchor], anchor=anchor,
        )
        self.assertEqual(results, [])

    def test_same_folder_signal(self):
        anchor = _file(
            id="a", file_name="maureen id back.jpg",
            relative_path="Family/Maureen/maureen id back.jpg",
        )
        other = _file(
            id="b", file_name="alex passport.jpg",
            relative_path="Family/Maureen/alex passport.jpg",
        )
        results = find_related_with_reasons(
            [anchor, other], anchor=anchor,
        )
        self.assertEqual(len(results), 1)
        self.assertIn(
            REASON_SAME_FOLDER,
            {x.code for x in results[0].reasons},
        )

    def test_same_upload_session_within_window(self):
                                                             
                        
        t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        anchor = _file(
            id="a", file_name="07f95dc4.jpg", created_at=t0,
        )
        within = _file(
            id="b", file_name="9b1de2af.png",
            created_at=t0 + timedelta(minutes=2),
        )
        too_far = _file(
            id="c", file_name="ccc12345.gif",
            created_at=t0 + timedelta(hours=2),
        )
        results = find_related_with_reasons(
            [anchor, within, too_far], anchor=anchor,
        )
        ids = {r.file_id for r in results}
        self.assertIn("b", ids)
        self.assertNotIn("c", ids)
        for r in results:
            if r.file_id == "b":
                self.assertIn(
                    REASON_SAME_UPLOAD_SESSION,
                    {x.code for x in r.reasons},
                )

    def test_id_back_scenario_from_spec(self):
                                                                
                                         
        batch = "import-1"
        anchor = _file(
            id="a", file_name="maureen id back.jpg",
            import_id=batch,
        )
        front = _file(
            id="front", file_name="maureen id front.jpg",
            import_id=batch,
        )
        passport = _file(
            id="passport", file_name="maureen passport.jpg",
            import_id=batch,
        )
        selfie = _file(
            id="selfie", file_name="maureen selfie.png",
            import_id=batch,
        )
        random_media = [
            _file(
                id=f"rm-{i}",
                file_name=f"07f95dc4-{i}.jpg",
                import_id=batch,
            )
            for i in range(54)
        ]
        all_rows = [anchor, front, passport, selfie, *random_media]
        results = find_related_with_reasons(all_rows, anchor=anchor)

                                          
        ids = [r.file_id for r in results]
        self.assertIn("front", ids)
        self.assertIn("passport", ids)
        self.assertIn("selfie", ids)
                                                                    
                                                            
        for r in results:
            if r.file_id == "front":
                self.assertEqual(r.confidence(), CONFIDENCE_STRONG)
            elif r.file_id in {"passport", "selfie"}:
                self.assertEqual(r.confidence(), CONFIDENCE_MEDIUM)
            elif r.file_id.startswith("rm-"):
                self.assertEqual(r.confidence(), CONFIDENCE_WEAK)


class FormatRelatedReplyTests(unittest.TestCase):
    def test_empty_results_friendly_message(self):
        out = format_related_reply("maureen id back.jpg", [])
        self.assertIn("couldn't find", out)
        self.assertIn("maureen id back.jpg", out)

    def test_weak_only_disclaimer(self):
                                                                   
                                                      
        anchor = _file(
            id="a", file_name="anchor.jpg", import_id="b1",
        )
        weaks = [
            _file(id="x", file_name="x.jpg", import_id="b1"),
        ]
        results = find_related_with_reasons(
            [anchor, *weaks], anchor=anchor,
        )
        reply = format_related_reply("anchor.jpg", results)
                                    
        self.assertIn("not sure they're actually related", reply)

    def test_renders_per_file_reasons(self):
        anchor = _file(id="a", file_name="maureen id back.jpg")
        other = _file(id="b", file_name="maureen id front.jpg")
        results = find_related_with_reasons(
            [anchor, other], anchor=anchor,
        )
        reply = format_related_reply("maureen id back.jpg", results)
                                                           
        self.assertIn("maureen id front.jpg", reply)
        self.assertIn("front/back filename pair", reply)

    def test_caps_at_render_max_with_refine_footer(self):
                                                                 
                                                
        anchor = _file(
            id="a", file_name="anchor.jpg", import_id="b1",
        )
        weaks = [
            _file(id=f"w{i}", file_name=f"w{i}.jpg", import_id="b1")
            for i in range(50)
        ]
        results = find_related_with_reasons(
            [anchor, *weaks], anchor=anchor,
        )
        reply = format_related_reply("anchor.jpg", results)
                                        
        rendered_files = reply.count("\n- ")
        self.assertLessEqual(rendered_files, RELATED_RENDER_HARD_CAP)
                                          
        self.assertIn("more", reply)
        self.assertIn("refine", reply)

    def test_suppresses_weak_group_when_strong_or_medium_present(self):
                                                                  
                                                              
        batch = "b1"
        anchor = _file(
            id="a", file_name="maureen id back.jpg", import_id=batch,
        )
        strong = _file(
            id="s", file_name="maureen id front.jpg", import_id=batch,
        )
        weaks = [
            _file(id=f"w{i}", file_name=f"random_{i}.jpg",
                  import_id=batch)
            for i in range(5)
        ]
        results = find_related_with_reasons(
            [anchor, strong, *weaks], anchor=anchor,
        )
        reply = format_related_reply("maureen id back.jpg", results)
                                  
        self.assertIn("Strong matches", reply)
                                                               
        self.assertNotIn("Weak matches", reply)


class ChatDispatcherWiringTests(unittest.TestCase):


    def test_reasoned_runs_before_legacy(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
                                                                     
                                                                   
        reasoned_idx = max(
            src.find("handle_related_items_with_reasons"),
            src.find("handle_related_items_envelope_payload"),
        )
        legacy_idx = src.find("from relationship_builder import handle_related_items\n")
        self.assertGreater(reasoned_idx, -1,
            "chat_endpoint must call the reasoned handler")
        self.assertGreater(legacy_idx, -1,
            "legacy handler must remain as fallback")
        self.assertLess(
            reasoned_idx, legacy_idx,
            "reasoned handler must run BEFORE the legacy graph handler",
        )


class SafetyGuardsTests(unittest.TestCase):
    def test_random_media_with_no_signal_never_returned(self):
                                                                   
                                                                     
        anchor = _file(id="a", file_name="anchor.jpg")
        unrelated = [
            _file(id=f"u{i}", file_name=f"random_{i}.jpg")
            for i in range(100)
        ]
        results = find_related_with_reasons(
            [anchor, *unrelated], anchor=anchor,
        )
        self.assertEqual(results, [])

    def test_no_more_than_render_cap_in_strong_medium(self):
                                                                
                                                       
        batch = "b1"
        anchor = _file(
            id="a", file_name="maureen id back.jpg", import_id=batch,
        )
        many = [
            _file(
                id=f"m{i}",
                file_name=f"maureen note {i}.jpg",
                import_id=batch,
            )
            for i in range(20)
        ]
        results = find_related_with_reasons(
            [anchor, *many], anchor=anchor,
        )
        reply = format_related_reply("maureen id back.jpg", results)
        rendered_files = reply.count("\n- ")
        self.assertLessEqual(rendered_files, RELATED_RENDER_HARD_CAP)


if __name__ == "__main__":
    unittest.main()
