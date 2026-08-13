import os
from unittest.mock import patch

import device_gate


def _enabled(**values):
    base = {
        "VAULTAI_ENV": "development",
        "VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST": "true",
        "VAULTAI_ISOLATED_QA": "true",
        "DATABASE_URL": "postgresql://qa@127.0.0.1:55432/qa_clone",
    }
    base.update(values)
    with patch.dict(os.environ, base, clear=True):
        return device_gate.is_dev_auto_trust_enabled()


def test_explicit_local_isolated_qa_can_auto_trust():
    assert _enabled() is True


def test_production_environment_cannot_auto_trust_even_with_flags():
    assert _enabled(VAULTAI_ENV="production") is False


def test_remote_or_production_database_cannot_auto_trust():
    assert _enabled(DATABASE_URL="postgresql://app@db.internal/prod") is False


def test_missing_isolated_qa_marker_cannot_auto_trust():
    assert _enabled(VAULTAI_ISOLATED_QA="false") is False


def test_auto_trust_flag_defaults_off():
    assert _enabled(VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST="false") is False


def test_chat_matrix_rate_override_is_guarded_in_source():
    from pathlib import Path

    source = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")
    assert "@limiter.limit(_CHAT_TURN_RATE_LIMIT)" in source
    assert "VAULTAI_CHAT_TURN_MAX_PER_MINUTE" in source
    assert "VAULTAI_ISOLATED_QA" in source
    assert '"@127.0.0.1:" in database_url' in source
