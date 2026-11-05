"""Guard against production diagnostics becoming an offline PIN oracle."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BACKEND_MAIN = ROOT / "vault_ai_backend" / "main.py"
FRONTEND_MAIN = ROOT / "vault_ai_frontend" / "lib" / "main.dart"


def test_runtime_does_not_log_pin_derived_key_fingerprints():
    backend = BACKEND_MAIN.read_text()
    frontend = FRONTEND_MAIN.read_text()
    for source in (backend, frontend):
        assert "key_fp12" not in source
        assert "server_key_fp12" not in source
    assert "cryptoFingerprintForKey(" not in frontend
    assert "key_fingerprint(key)" not in backend


def test_chat_error_diagnostics_do_not_emit_exception_payloads():
    backend = BACKEND_MAIN.read_text()
    assert "post_decrypt_traceback" not in backend
    assert "traceback.format_exc()" not in backend
    for label in (
        "verify_pin_failed", "decrypt_failed", "openai_stream_failed",
        "memory_failed", "intent_failed", "semantic_failed",
        "post_decrypt_caught",
    ):
        assert not any(
            label in line and ("repr=" in line or "detail=" in line)
            for line in backend.splitlines()
        )
