

from __future__ import annotations

import ast
import os
import pathlib
import unittest

import vault_config


BACKEND_DIR = pathlib.Path(__file__).parent


def _is_production_source(path: pathlib.Path) -> bool:


    name = path.name
    if not name.endswith(".py"):
        return False
    if name.startswith("test_"):
        return False
    if name in {
        "conftest.py",
        "check_db.py",
        "find_account_id.py",
        "inspect_db_connection.py",
        "inspect_duplicate_columns.py",
        "inspect_sub_columns.py",
        "inspect_tables.py",
        "inspect_vaults.py",
        "manual_backfill_item_id.py",
        "add_stripe_item_column.py",
        "reset_dev_db.py",
        "password_audit.py",
        "backfill_asset_tags.py",
        "backfill_billing_p0.py",
        "backfill_document_understanding.py",
        "backfill_semantic_index.py",
    }:
        return False
                                                                      
    if "migrations" in path.parts:
        return False
    return True


def _iter_production_sources():
    for p in BACKEND_DIR.glob("*.py"):
        if _is_production_source(p):
            yield p


class ProductionFailsClosedTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snapshot = dict(os.environ)
                                                                    
                                                                     
        for var in (
            "VAULT_SESSION_SECRET",
            "VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV",
            "CORS_ALLOWED_ORIGIN_REGEX", "CORS_ALLOWED_ORIGINS",
            "VAULTAI_DEBUG_ENDPOINTS_ENABLED",
            "STRIPE_WEBHOOK_SECRET",
            "VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST",
        ):
            os.environ.pop(var, None)
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._snapshot)
        vault_config.reset_for_tests()

    def test_prod_missing_session_secret_refuses_boot(self) -> None:
        os.environ["VAULTAI_ENV"] = "production"
        os.environ["CORS_ALLOWED_ORIGIN_REGEX"] = "https://example.com"
        with self.assertRaises(RuntimeError) as ctx:
            vault_config.get_config()
        self.assertIn("VAULT_SESSION_SECRET", str(ctx.exception))

    def test_prod_missing_cors_refuses_boot(self) -> None:
        os.environ["VAULTAI_ENV"] = "production"
        os.environ["VAULT_SESSION_SECRET"] = "x" * 48
        with self.assertRaises(RuntimeError) as ctx:
            vault_config.get_config()
        self.assertIn("CORS_ALLOWED", str(ctx.exception))

    def test_prod_with_required_config_boots(self) -> None:
        os.environ["VAULTAI_ENV"] = "production"
        os.environ["VAULT_SESSION_SECRET"] = "x" * 48
        os.environ["CORS_ALLOWED_ORIGIN_REGEX"] = "https://example.com"
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_stub"
        cfg = vault_config.get_config()
        self.assertTrue(cfg.is_production)

    def test_prod_with_debug_endpoints_enabled_refuses_boot(self) -> None:
        os.environ["VAULTAI_ENV"] = "production"
        os.environ["VAULT_SESSION_SECRET"] = "x" * 48
        os.environ["CORS_ALLOWED_ORIGIN_REGEX"] = "https://example.com"
        os.environ["VAULTAI_DEBUG_ENDPOINTS_ENABLED"] = "true"
        with self.assertRaises(RuntimeError) as ctx:
            vault_config.get_config()
        self.assertIn("VAULTAI_DEBUG_ENDPOINTS_ENABLED", str(ctx.exception))


class DevDefaultsWorkTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snapshot = dict(os.environ)
        for var in (
            "VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV",
            "CORS_ALLOWED_ORIGIN_REGEX", "CORS_ALLOWED_ORIGINS",
        ):
            os.environ.pop(var, None)
                                                                     
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._snapshot)
        vault_config.reset_for_tests()

    def test_no_env_token_is_dev(self) -> None:
        cfg = vault_config.get_config()
        self.assertFalse(cfg.is_production)
        self.assertTrue(vault_config.is_dev_or_local())

    def test_dev_default_ai_model(self) -> None:
        cfg = vault_config.get_config()
        self.assertEqual(cfg.ai.embedding_model, "text-embedding-3-small")
        self.assertEqual(cfg.ai.embedding_dim, 1536)

    def test_dev_default_brain_tunables(self) -> None:
        cfg = vault_config.get_config()
        self.assertEqual(cfg.brain.chunk_target_chars, 1500)
        self.assertEqual(cfg.brain.chunk_overlap_chars, 200)
        self.assertEqual(cfg.brain.max_chunk_chars, 8000)
        self.assertEqual(cfg.brain.retrieval_top_k, 8)
        self.assertAlmostEqual(cfg.brain.min_similarity, 0.20)
        self.assertEqual(cfg.brain.evidence_snippet_chars, 240)
        self.assertEqual(cfg.brain.read_file_excerpt_chars, 4000)

    def test_dev_default_upload_caps(self) -> None:
        cfg = vault_config.get_config()
        self.assertEqual(cfg.upload.max_upload_bytes, 100 * 1024 * 1024)
        self.assertEqual(cfg.upload.max_json_body_bytes, 1 * 1024 * 1024)

    def test_dev_default_media_caps(self) -> None:
        cfg = vault_config.get_config()
        self.assertEqual(cfg.media.max_audio_bytes, 25 * 1024 * 1024)
        self.assertEqual(cfg.media.max_video_bytes, 200 * 1024 * 1024)
        self.assertEqual(cfg.media.max_transcript_chars, 500_000)

    def test_dev_default_cache_ttls(self) -> None:
        cfg = vault_config.get_config()
        self.assertEqual(cfg.cache.vault_key_idle_ttl_secs, 30 * 60)
        self.assertEqual(cfg.cache.vault_key_hard_ttl_secs, 8 * 60 * 60)

    def test_dev_default_billing(self) -> None:
        cfg = vault_config.get_config()
        self.assertEqual(cfg.billing.free_included_bytes, 1_073_741_824)
        self.assertEqual(cfg.billing.storage_block_bytes, 53_687_091_200)
        self.assertEqual(cfg.billing.monthly_block_price_cents_usd, 2500)
        self.assertEqual(cfg.billing.self_service_max_blocks, 100)


class EnvOverrideTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snapshot = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._snapshot)
        vault_config.reset_for_tests()

    def test_chat_model_override(self) -> None:
        os.environ["VAULTAI_CHAT_MODEL"] = "gpt-fake-model"
        vault_config.reset_for_tests()
        self.assertEqual(vault_config.ai().chat_model, "gpt-fake-model")

    def test_chunk_target_chars_override(self) -> None:
        os.environ["VAULTAI_CHUNK_TARGET_CHARS"] = "777"
        vault_config.reset_for_tests()
        self.assertEqual(vault_config.brain().chunk_target_chars, 777)

    def test_min_similarity_override(self) -> None:
        os.environ["VAULTAI_MIN_SIMILARITY"] = "0.42"
        vault_config.reset_for_tests()
        self.assertAlmostEqual(vault_config.brain().min_similarity, 0.42)

    def test_max_upload_bytes_override(self) -> None:
        os.environ["MAX_UPLOAD_BYTES"] = str(7 * 1024 * 1024)
        vault_config.reset_for_tests()
        self.assertEqual(
            vault_config.upload().max_upload_bytes, 7 * 1024 * 1024,
        )

    def test_billing_block_price_override(self) -> None:
        os.environ["VAULTAI_MONTHLY_BLOCK_PRICE_CENTS_USD"] = "1234"
        vault_config.reset_for_tests()
        self.assertEqual(
            vault_config.billing().monthly_block_price_cents_usd, 1234,
        )


class DescribeIsSafeToLogTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snapshot = dict(os.environ)
        os.environ["VAULT_SESSION_SECRET"] = "supersecret-" + ("x" * 40)
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._snapshot)
        vault_config.reset_for_tests()

    def test_describe_does_not_leak_session_secret(self) -> None:
        described = repr(vault_config.describe())
        self.assertNotIn("supersecret", described)
        self.assertNotIn("VAULT_SESSION_SECRET", described)

    def test_describe_keys_are_closed_set(self) -> None:
        d = vault_config.describe()
        expected_top = {
            "env", "ai", "brain", "worker", "upload",
            "media", "cache", "billing",
        }
        self.assertEqual(set(d.keys()), expected_top)


class DoNotShipFallbackSecretGuard(unittest.TestCase):


    LEGACY_FALLBACK = "vaultai-dev-only-fallback-secret-do-not-ship"
    LEGACY_FRAGMENT = "do-not-ship"

    LEGACY_SECRET_LITERALS = (
                                                                 
                                   
        "vaultai-dev-only-fallback-secret-do-not-ship",
                                                               
        "vaultai-dev-only-fallback-secret",
    )

    def test_no_legacy_fallback_secret_literal(self) -> None:


        offenders: list[str] = []
        for path in _iter_production_sources():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant):
                    continue
                v = node.value
                if isinstance(v, bytes):
                    try:
                        v = v.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                if not isinstance(v, str):
                    continue
                for legacy in self.LEGACY_SECRET_LITERALS:
                    if v == legacy:
                        offenders.append(
                            f"{path.name}: legacy secret literal "
                            f"'{legacy}'",
                        )
        self.assertEqual(
            offenders, [],
            f"the do-not-ship legacy fallback secret appears as a "
            f"usable literal in: {offenders}",
        )

    def test_no_hardcoded_session_secret_literal(self) -> None:


        offenders: list[str] = []
        for path in _iter_production_sources():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    target_names = [
                        t.id for t in node.targets
                        if isinstance(t, ast.Name)
                    ]
                    if not any("secret" in name.lower()
                               for name in target_names):
                        continue
                    if isinstance(node.value, ast.Constant) and \
                       isinstance(node.value.value, (str, bytes)):
                        v = node.value.value
                                                                  
                                                                  
                        if (
                            isinstance(v, (bytes, str))
                            and len(v) >= 16
                        ):
                            offenders.append(
                                f"{path.name}: {target_names}",
                            )
        self.assertEqual(
            offenders, [],
            f"hardcoded session-secret-shaped literals found: {offenders}",
        )


class ModelNameSourceGuard(unittest.TestCase):


    KNOWN_MODELS = (
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4",
        "gpt-3.5-turbo",
        "text-embedding-3-small",
        "text-embedding-3-large",
    )
    ALLOWED_MODULES = {
                                                  
        "vault_config.py",
                                                                 
                                                            
        "brain_embedder.py",
        "semantic_embedder.py",
        "vault_brain_indexer.py",
        "vault_embedding.py",
        "service_resolver.py",
        "username_policy.py",
                                                               
                                                                
        "vault_reconciler.py",
    }

    def test_allowed_boundary_modules_actually_import_vault_config(self) -> None:


        bridging = self.ALLOWED_MODULES - {"vault_config.py"}
        offenders: list[str] = []
        for name in sorted(bridging):
            path = BACKEND_DIR / name
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                offenders.append(f"{name}: missing")
                continue
            if "from vault_config" not in content and \
               "import vault_config" not in content:
                offenders.append(f"{name}: no vault_config import")
        self.assertEqual(
            offenders, [],
            f"boundary modules must import vault_config: {offenders}",
        )

    def test_model_literals_only_in_allowed_modules(self) -> None:
        offenders: list[str] = []
        for path in _iter_production_sources():
            if path.name in self.ALLOWED_MODULES:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant):
                    continue
                if not isinstance(node.value, str):
                    continue
                for model in self.KNOWN_MODELS:
                    if node.value == model:
                        offenders.append(
                            f"{path.name}: inline '{model}'",
                        )
        self.assertEqual(
            offenders, [],
            f"model literals must come from vault_config.ai(): {offenders}",
        )


class BrainTunablesFromConfigTests(unittest.TestCase):


    def test_chunker_defaults_match_config(self) -> None:
        from vault_chunker import (
            DEFAULT_TARGET_CHARS, DEFAULT_OVERLAP_CHARS, MAX_CHUNK_CHARS,
        )
        cfg = vault_config.brain()
        self.assertEqual(DEFAULT_TARGET_CHARS, cfg.chunk_target_chars)
        self.assertEqual(DEFAULT_OVERLAP_CHARS, cfg.chunk_overlap_chars)
        self.assertEqual(MAX_CHUNK_CHARS, cfg.max_chunk_chars)

    def test_retrieval_defaults_match_config(self) -> None:
        from vault_brain_retrieval import (
            DEFAULT_TOP_K,
            DEFAULT_MIN_SIMILARITY,
            DEFAULT_LEXICAL_FALLBACK_LIMIT,
        )
        cfg = vault_config.brain()
        self.assertEqual(DEFAULT_TOP_K, cfg.retrieval_top_k)
        self.assertAlmostEqual(DEFAULT_MIN_SIMILARITY, cfg.min_similarity)
        self.assertEqual(
            DEFAULT_LEXICAL_FALLBACK_LIMIT, cfg.lexical_fallback_limit,
        )

    def test_answerer_defaults_match_config(self) -> None:
        from vault_brain_answerer import (
            DEFAULT_MAX_EVIDENCE_ROWS, DEFAULT_SNIPPET_CHARS,
        )
        cfg = vault_config.brain()
        self.assertEqual(
            DEFAULT_MAX_EVIDENCE_ROWS, cfg.max_context_chunks,
        )
        self.assertEqual(
            DEFAULT_SNIPPET_CHARS, cfg.evidence_snippet_chars,
        )

    def test_brain_embedder_constants_match_config(self) -> None:
        from brain_embedder import EMBED_MODEL, EMBED_DIM, MAX_INPUT_CHARS
        cfg = vault_config.ai()
        self.assertEqual(EMBED_MODEL, cfg.embedding_model)
        self.assertEqual(EMBED_DIM, cfg.embedding_dim)
        self.assertEqual(MAX_INPUT_CHARS, cfg.brain_query_embed_cap_chars)

    def test_brain_indexer_constants_match_config(self) -> None:
        from vault_brain_indexer import (
            EMBEDDING_DIM, EMBED_MODEL, DEFAULT_INDEXER_BATCH,
        )
        ai = vault_config.ai()
        brain = vault_config.brain()
        self.assertEqual(EMBEDDING_DIM, ai.embedding_dim)
        self.assertEqual(EMBED_MODEL, ai.embedding_model)
        self.assertEqual(DEFAULT_INDEXER_BATCH, brain.indexer_batch)


class WorkerTunablesFromConfigTests(unittest.TestCase):
    def test_daemon_constants_match_config(self) -> None:
        from vault_analysis_daemon import (
            ITERATION_INTERVAL_SECONDS,
            DRAIN_BUDGET_PER_VAULT_PER_ITER,
            SHUTDOWN_GRACE_SECONDS,
        )
        cfg = vault_config.worker()
        self.assertAlmostEqual(
            ITERATION_INTERVAL_SECONDS,
            cfg.daemon_iteration_sleep_secs,
        )
        self.assertEqual(
            DRAIN_BUDGET_PER_VAULT_PER_ITER, cfg.drain_budget_per_iter,
        )
        self.assertAlmostEqual(
            SHUTDOWN_GRACE_SECONDS, cfg.daemon_shutdown_grace_secs,
        )

    def test_deep_answer_constants_match_config(self) -> None:
        from vault_deep_answer import (
            DEFAULT_MAX_WALLCLOCK_SECONDS,
            DEFAULT_DRAIN_BUDGET_PER_REQUEST,
        )
        cfg = vault_config.worker()
        self.assertAlmostEqual(
            DEFAULT_MAX_WALLCLOCK_SECONDS,
            cfg.deep_answer_max_wallclock_secs,
        )
        self.assertEqual(
            DEFAULT_DRAIN_BUDGET_PER_REQUEST, cfg.drain_budget_per_iter,
        )


class MediaTunablesFromConfigTests(unittest.TestCase):
    def test_audio_constants_match_config(self) -> None:
        from vault_audio_transcription import (
            MAX_AUDIO_BYTES, MAX_TRANSCRIPT_CHARS,
        )
        cfg = vault_config.media()
        self.assertEqual(MAX_AUDIO_BYTES, cfg.max_audio_bytes)
        self.assertEqual(MAX_TRANSCRIPT_CHARS, cfg.max_transcript_chars)

    def test_video_constants_match_config(self) -> None:
        from vault_video_transcription import (
            MAX_VIDEO_BYTES, MAX_TRANSCRIPT_CHARS,
        )
        cfg = vault_config.media()
        self.assertEqual(MAX_VIDEO_BYTES, cfg.max_video_bytes)
        self.assertEqual(MAX_TRANSCRIPT_CHARS, cfg.max_transcript_chars)


class CacheTunablesFromConfigTests(unittest.TestCase):
    def test_vault_key_cache_ttls_match_config(self) -> None:
        from vault_key_cache import (
            _DEFAULT_IDLE_TTL_SECONDS, _DEFAULT_HARD_TTL_SECONDS,
        )
        cfg = vault_config.cache()
        self.assertAlmostEqual(
            _DEFAULT_IDLE_TTL_SECONDS, cfg.vault_key_idle_ttl_secs,
        )
        self.assertAlmostEqual(
            _DEFAULT_HARD_TTL_SECONDS, cfg.vault_key_hard_ttl_secs,
        )


class BillingTunablesFromConfigTests(unittest.TestCase):
    def test_billing_defaults_match_config(self) -> None:
        from billing import (
            DEFAULT_INCLUDED_BYTES, DEFAULT_BLOCK_BYTES,
            DEFAULT_BLOCK_PRICE_CENTS_USD,
            DEFAULT_SELF_SERVICE_MAX_BLOCKS,
        )
        cfg = vault_config.billing()
        self.assertEqual(DEFAULT_INCLUDED_BYTES, cfg.free_included_bytes)
        self.assertEqual(DEFAULT_BLOCK_BYTES, cfg.storage_block_bytes)
        self.assertEqual(
            DEFAULT_BLOCK_PRICE_CENTS_USD,
            cfg.monthly_block_price_cents_usd,
        )
        self.assertEqual(
            DEFAULT_SELF_SERVICE_MAX_BLOCKS, cfg.self_service_max_blocks,
        )


class UploadTunablesFromConfigTests(unittest.TestCase):
    def test_upload_constants_match_config(self) -> None:
        from main import MAX_UPLOAD_BYTES, MAX_JSON_BODY_BYTES
        cfg = vault_config.upload()
        self.assertEqual(MAX_UPLOAD_BYTES, cfg.max_upload_bytes)
        self.assertEqual(MAX_JSON_BODY_BYTES, cfg.max_json_body_bytes)


class ReadFileExcerptFromConfigTests(unittest.TestCase):
    def test_read_file_excerpt_matches_config(self) -> None:
        from vault_read_file import _DEFAULT_CHAT_EXCERPT_CHARS
        cfg = vault_config.brain()
        self.assertEqual(
            _DEFAULT_CHAT_EXCERPT_CHARS, cfg.read_file_excerpt_chars,
        )


if __name__ == "__main__":
    unittest.main()
