

from __future__ import annotations

import inspect
import json
import unittest
from unittest.mock import patch, MagicMock

import main


class EndpointRegistrationTests(unittest.TestCase):
    def test_route_registered_with_post(self):
        routes = [
            (r.path, sorted(list(r.methods)))
            for r in main.app.routes
            if hasattr(r, "path") and r.path == "/files/{file_id}/related"
        ]
        self.assertGreaterEqual(len(routes), 1)
        self.assertIn("POST", routes[0][1])

    def test_handler_uses_trusted_device_gate(self):
                                               
                                                     
        src = inspect.getsource(main.related_files_for_file_endpoint)
        self.assertIn("verify_trusted_device", src)

    def test_handler_verifies_pin(self):
        src = inspect.getsource(main.related_files_for_file_endpoint)
        self.assertIn("verify_vault_pin", src)

    def test_handler_takes_vault_id_from_principal(self):
        src = inspect.getsource(main.related_files_for_file_endpoint)
                                                            
                     
        self.assertIn('vault_id = principal["vault_id"]', src)

    def test_request_body_is_only_pin(self):
        src = inspect.getsource(main.RelatedFilesRequest)
                                                                 
                              
        self.assertIn("pin: str", src)
        self.assertNotIn("vault_id:", src)

    def test_handler_uses_compose_helper(self):
        src = inspect.getsource(main.related_files_for_file_endpoint)
        self.assertIn("_compose_related_files_envelope", src)

    def test_handler_uses_vault_scoped_anchor_loader(self):
        src = inspect.getsource(main.related_files_for_file_endpoint)
        self.assertIn("_load_safe_anchor_row", src)

    def test_handler_returns_404_on_missing_anchor(self):
        src = inspect.getsource(main.related_files_for_file_endpoint)
        self.assertIn("status_code=404", src)


class AnchorLoaderSourceGuardTests(unittest.TestCase):
    def _code_only(self) -> str:
                                                             
                                                            
        import ast
        src = inspect.getsource(main._load_safe_anchor_row)
        try:
            doc = ast.get_docstring(ast.parse(src.lstrip())) or ""
        except Exception:
            doc = ""
        return src.replace(doc, "") if doc else src

    def test_query_is_vault_scoped(self):
        src = inspect.getsource(main._load_safe_anchor_row)
        self.assertIn("WHERE vault_id = %s", src)
        self.assertIn("AND id = %s", src)

    def test_never_reads_encrypted_columns(self):
        code = self._code_only()
        for col in (
            "encrypted_file_data",
            "extracted_text",
            "summary_encrypted",
            "safe_preview_encrypted",
        ):
            self.assertNotIn(col, code)

    def test_never_decrypts(self):
        code = self._code_only()
        self.assertNotIn("decrypt_message", code)
        self.assertNotIn("decrypt_bytes", code)

    def test_empty_inputs_short_circuit(self):
                                                            
                                               
        with patch.object(
            main, "get_db",
            side_effect=AssertionError("should not be called"),
        ):
            self.assertIsNone(main._load_safe_anchor_row("", "x"))
            self.assertIsNone(main._load_safe_anchor_row("v", ""))


class ComposerSourceGuardTests(unittest.TestCase):
    def test_composer_uses_get_relationships_for_file(self):
        src = inspect.getsource(main._compose_related_files_envelope)
        self.assertIn("get_relationships_for_file", src)

    def test_composer_uses_load_safe_file_metadata(self):
        src = inspect.getsource(main._compose_related_files_envelope)
        self.assertIn("_load_safe_file_metadata", src)

    def test_composer_uses_envelope_builder(self):
        src = inspect.getsource(main._compose_related_files_envelope)
        self.assertIn("_build_related_files_graph_envelope", src)

    def test_composer_uses_sort_helper(self):
        src = inspect.getsource(main._compose_related_files_envelope)
        self.assertIn("_sort_relationship_rows", src)

    def test_composer_empty_state_message_matches_spec(self):
        src = inspect.getsource(main._compose_related_files_envelope)
        self.assertIn("don't see strong related files", src)
        self.assertIn("related items may appear", src)

    def test_composer_never_decrypts(self):
                                                            
                                                               
        src = inspect.getsource(main._compose_related_files_envelope)
        self.assertNotIn("decrypt_message", src)
        self.assertNotIn("decrypt_bytes", src)


def _anchor_row(
    *, file_id="anchor-1", file_name="vacation.mp4",
    saved_name="Vacation", relative_path="/Trips/Qatar",
    content_type="video/mp4", asset_type="video",
) -> dict:
    return {
        "id":            file_id,
        "file_name":     file_name,
        "saved_name":    saved_name,
        "relative_path": relative_path,
        "content_type":  content_type,
        "asset_type":    asset_type,
    }


def _relationship_row(
    *, anchor_id="anchor-1", other_id="other-1",
    relationship_type="same_trip", confidence=0.85,
    reasons=("same trip: Qatar",),
) -> dict:
    return {
        "file_a_id":         anchor_id,
        "file_b_id":         other_id,
        "relationship_type": relationship_type,
        "confidence":        confidence,
        "reasons_jsonb":     list(reasons),
        "evidence_jsonb":    {},
        "updated_at":        None,
    }


class ComposerBehaviourTests(unittest.TestCase):
    def test_returns_envelope_dict_with_anchor(self):
        anchor = _anchor_row()
        rels = [
            _relationship_row(
                anchor_id="anchor-1", other_id="other-1",
                relationship_type="same_trip", confidence=0.85,
            ),
        ]
        meta = {
            "other-1": {
                "file_id":       "other-1",
                "file_name":     "boarding_pass.pdf",
                "saved_name":    "Boarding pass",
                "relative_path": "/Trips/Qatar",
                "content_type":  "application/pdf",
                "asset_type":    "file",
            },
        }
        with patch(
            "vault_relationship_graph.get_relationships_for_file",
            return_value=rels,
        ), patch.object(
            main, "_load_safe_file_metadata", return_value=meta,
        ):
            env = main._compose_related_files_envelope(
                vault_id="v-1", anchor_row=anchor,
            )
        self.assertEqual(env["type"], "related_files_graph")
        self.assertEqual(env["anchor"]["file_id"], "anchor-1")
        self.assertEqual(env["anchor"]["saved_name"], "Vacation")
        self.assertEqual(env["count"], 1)
        self.assertEqual(
            env["relationships"][0]["file"]["file_id"], "other-1",
        )
        self.assertIn(
            "related to",
            env["message"],
        )

    def test_empty_relationships_returns_spec_message(self):
        anchor = _anchor_row()
        with patch(
            "vault_relationship_graph.get_relationships_for_file",
            return_value=[],
        ), patch.object(
            main, "_load_safe_file_metadata", return_value={},
        ):
            env = main._compose_related_files_envelope(
                vault_id="v-1", anchor_row=anchor,
            )
        self.assertEqual(env["count"], 0)
        self.assertEqual(env["relationships"], [])
        self.assertIn("don't see strong related files", env["message"])
        self.assertIn("related items may appear", env["message"])

    def test_envelope_never_carries_extracted_text_or_summary(self):
                                                              
                                                              
        anchor = _anchor_row()
                                                            
                                                                
        hostile_rel = _relationship_row(
            anchor_id="anchor-1", other_id="other-1",
            reasons=("same trip: Qatar",),
        )
        hostile_rel["evidence_jsonb"] = {
                                     
            "shared_entity_names": ["Patrick"],
                                                                
            "summary":             "plaintext-summary-leak",
            "extracted_text":      "plaintext-content-leak",
            "password":            "hunter2",
            "token":               "SECRET-XYZ-123",
        }
        meta = {
            "other-1": {
                "file_id":       "other-1",
                "file_name":     "other.pdf",
                "saved_name":    "Other",
                "relative_path": "/x",
                "content_type":  "application/pdf",
                "asset_type":    "file",
                                                               
                         
                "summary":         "plaintext-summary-leak",
                "extracted_text":  "plaintext-content-leak",
                "password":        "hunter2",
            },
        }
        with patch(
            "vault_relationship_graph.get_relationships_for_file",
            return_value=[hostile_rel],
        ), patch.object(
            main, "_load_safe_file_metadata", return_value=meta,
        ):
            env = main._compose_related_files_envelope(
                vault_id="v-1", anchor_row=anchor,
            )
                                                       
                                             
        env_json = json.dumps(env)
        for sentinel in (
            "plaintext-summary-leak",
            "plaintext-content-leak",
            "hunter2",
            "SECRET-XYZ-123",
        ):
            self.assertNotIn(sentinel, env_json)
                                                          
        self.assertEqual(
            set(env["anchor"].keys()),
            {"file_id", "file_name", "saved_name",
             "relative_path", "mime_type", "asset_type"},
        )

    def test_anchor_with_empty_id_returns_empty_envelope(self):
                                                             
                                                            
        env = main._compose_related_files_envelope(
            vault_id="v-1", anchor_row={"id": ""},
        )
        self.assertEqual(env["type"], "related_files_graph")
        self.assertEqual(env["count"], 0)


class EndpointBehaviourTests(unittest.TestCase):


    def setUp(self):
        from fastapi.testclient import TestClient
        self.principal = {"vault_id": "v-trusted", "device_id": "d-1"}
                                                              
                                                  
        main.app.dependency_overrides[
            main.verify_trusted_device
        ] = lambda: self.principal
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.clear()

    def test_happy_path_returns_envelope(self):
        anchor = _anchor_row()
        with patch.object(
            main, "verify_vault_pin", return_value=None,
        ), patch.object(
            main, "_load_safe_anchor_row", return_value=anchor,
        ), patch.object(
            main, "_compose_related_files_envelope",
            return_value={
                "type":          "related_files_graph",
                "anchor":        {
                    "file_id": "anchor-1",
                    "file_name": "x.pdf",
                    "saved_name": "X",
                    "relative_path": None,
                    "mime_type": "application/pdf",
                    "asset_type": "file",
                },
                "count":         0,
                "message":       "ok",
                "relationships": [],
            },
        ):
            resp = self.client.post(
                "/files/anchor-1/related", json={"pin": "1234"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["type"], "related_files_graph")
        self.assertEqual(body["anchor"]["file_id"], "anchor-1")

    def test_unknown_file_id_returns_404(self):
        with patch.object(
            main, "verify_vault_pin", return_value=None,
        ), patch.object(
            main, "_load_safe_anchor_row", return_value=None,
        ):
            resp = self.client.post(
                "/files/unknown-id/related", json={"pin": "1234"},
            )
        self.assertEqual(resp.status_code, 404)

    def test_cross_vault_file_id_returns_404_same_as_unknown(self):
                                                               
                                                            
        with patch.object(
            main, "verify_vault_pin", return_value=None,
        ), patch.object(
            main, "_load_safe_anchor_row", return_value=None,
        ):
            unknown = self.client.post(
                "/files/unknown-id/related", json={"pin": "1234"},
            )
            cross = self.client.post(
                "/files/cross-vault-id/related", json={"pin": "1234"},
            )
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(cross.status_code, 404)
        self.assertEqual(unknown.json(), cross.json())

    def test_handler_never_calls_llm(self):
                                                           
                                    
        src = inspect.getsource(main.related_files_for_file_endpoint)
        self.assertNotIn("classify_chat_intent", src)
        self.assertNotIn("call_llm", src)
        self.assertNotIn("send_chat", src)

    def test_handler_never_calls_resolver(self):
                                                              
                                           
        src = inspect.getsource(main.related_files_for_file_endpoint)
        self.assertNotIn("_resolve_file_for_analysis", src)


class ChatHandlerStillWorksTests(unittest.TestCase):
    def test_chat_handler_branch_still_exists(self):
        src = inspect.getsource(main.chat_endpoint)
        self.assertIn('intent == "related_files"', src)

    def test_chat_handler_uses_compose_helper(self):
        src = inspect.getsource(main.chat_endpoint)
        idx = src.find('intent == "related_files"')
        body = src[idx:idx + 6000]
        self.assertIn("_compose_related_files_envelope", body)


if __name__ == "__main__":
    unittest.main()
