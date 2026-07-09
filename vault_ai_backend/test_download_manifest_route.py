

from __future__ import annotations

import inspect
import unittest


class DownloadManifestRouteAlwaysRegisteredTests(unittest.TestCase):
    def test_manifest_endpoint_in_app_routes(self):


        import main
        paths = {
            getattr(r, "path", None) for r in main.app.routes
        }
        self.assertIn(
            "/download-file/manifest",
            paths,
            "manifest endpoint must be registered unconditionally; "
            "leaving it behind VAULTAI_CHUNKED_UPLOADS broke View for "
            "every inline file (the original bug report)",
        )

    def test_chunk_endpoint_in_app_routes(self):


        import main
        paths = {getattr(r, "path", None) for r in main.app.routes}
        self.assertIn("/download-file/chunk", paths)

    def test_main_registers_chunked_download_unconditionally(self):


        src = inspect.getsource(__import__("main"))
                                                              
                                                                    
        self.assertIn(
            "app.include_router(chunked_download_router)",
            src,
            "main.py must register the chunked_download router",
        )
                                                                       
                                                                      
        flag_idx = src.find(
            'os.getenv("VAULTAI_CHUNKED_UPLOADS"',
        )
                                                                 
                                                                  
        last_flag_idx = src.rfind(
            'os.getenv("VAULTAI_CHUNKED_UPLOADS"',
        )
        manifest_reg_idx = src.find(
            "app.include_router(chunked_download_router)",
        )
        self.assertGreater(flag_idx, -1)
        self.assertGreater(manifest_reg_idx, -1)
        self.assertLess(
            manifest_reg_idx,
            last_flag_idx,
            "chunked_download router must be registered BEFORE the "
            "VAULTAI_CHUNKED_UPLOADS flag check (always-on)",
        )


class DownloadManifestSchemaTests(unittest.TestCase):


    def test_file_id_field_is_string(self):
        from routes.chunked_download_routes import DownloadManifestRequest
        schema = DownloadManifestRequest.model_json_schema()
                                                                     
                                                                     
        file_id_schema = schema["properties"]["file_id"]
        self.assertEqual(file_id_schema.get("type"), "string")
        self.assertNotEqual(file_id_schema.get("format"), "uuid")

    def test_manifest_response_includes_legacy_fallback_hint(self):


        src = inspect.getsource(
            __import__("routes.chunked_download_routes", fromlist=["x"])
        )
        self.assertIn('"next": "legacy"', src)
        self.assertIn('"next": "chunked"', src)

    def test_manifest_does_not_404_when_storage_mode_is_inline(self):


        src = inspect.getsource(
            __import__("routes.chunked_download_routes", fromlist=["x"])
        )
                                                             
                              
        inline_block_idx = src.find('if storage_mode == "inline":')
        self.assertGreater(inline_block_idx, -1)
                                                                   
                                                       
        inline_block = src[inline_block_idx:inline_block_idx + 800]
        self.assertNotIn("status_code=404", inline_block)


if __name__ == "__main__":
    unittest.main()
