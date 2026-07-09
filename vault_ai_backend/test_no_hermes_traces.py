

from __future__ import annotations

import os
import re
import unittest


_FORBIDDEN_NEEDLES = (
    "PROVIDER_HERMES",
    "hermes_chat_model",
    "hermes_intent_model",
    "hermes_base_url",
    "hermes_api_key_env",
    "hermes_resident_enabled",
    "_hermes_client",
    "hermes_resident_agent",
    "hermes_resident_agent_tools",
    "hermes_resident_chat_dispatcher",
    "hermes_resident_daemon",
    "hermes_resident_enqueuer",
    "hermes_resident_memory",
    "hermes_resident_prose_composer",
    "hermes_resident_reader",
    "hermes_resident_rollup",
    "hermes_resident_router",
    "hermes_resident_worker",
    "run_resident_agent_turn",
    "compose_resident_prose",
    "dispatch_resident_question",
    "RESIDENT_QUESTION_",
    "VAULTAI_HERMES_",
    "NOUS_API_KEY",
    "nousresearch",
    "Hermes-3-Llama",
)


def _iter_runtime_py_files() -> list[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    out: list[str] = []
    for entry in os.listdir(here):
        if not entry.endswith(".py"):
            continue
        if entry.startswith("test_"):
            continue
        if entry == os.path.basename(__file__):
            continue
        out.append(os.path.join(here, entry))
    return out


class NoHermesIdentifiersInRuntimeTests(unittest.TestCase):
    def test_no_forbidden_identifier_in_any_runtime_file(self):
        for path in _iter_runtime_py_files():
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
            for needle in _FORBIDDEN_NEEDLES:
                with self.subTest(file=os.path.basename(path),
                                  needle=needle):
                    self.assertNotIn(
                        needle, src,
                        f"{os.path.basename(path)} contains forbidden "
                        f"Hermes identifier {needle!r}",
                    )


class NoHermesStandaloneModulesTests(unittest.TestCase):
    def test_hermes_resident_modules_are_deleted(self):
        here = os.path.dirname(os.path.abspath(__file__))
        for name in (
            "hermes_resident_agent.py",
            "hermes_resident_agent_tools.py",
            "hermes_resident_chat_dispatcher.py",
            "hermes_resident_daemon.py",
            "hermes_resident_enqueuer.py",
            "hermes_resident_memory.py",
            "hermes_resident_prose_composer.py",
            "hermes_resident_reader.py",
            "hermes_resident_rollup.py",
            "hermes_resident_router.py",
            "hermes_resident_worker.py",
        ):
            with self.subTest(name=name):
                self.assertFalse(
                    os.path.exists(os.path.join(here, name)),
                    f"deleted Hermes module {name} reappeared",
                )


class NoHermesEnvVarsLiveTests(unittest.TestCase):


    def test_live_env_has_no_hermes_lines(self):
        here = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.join(here, ".env")
        if not os.path.exists(env_path):
            self.skipTest(".env not present in this environment")
        with open(env_path, "r", encoding="utf-8") as f:
            src = f.read()
        for needle in (
            "VAULTAI_HERMES_",
            "NOUS_API_KEY",
            "nousresearch",
            "hermes",
        ):
            with self.subTest(needle=needle):
                                                               
                                                           
                self.assertNotRegex(
                    src, re.compile(needle, re.IGNORECASE),
                    f".env contains {needle!r} (live Hermes config)",
                )


class OpenAIIsTheOnlyProviderTests(unittest.TestCase):
    def test_provider_constants_collapsed_to_openai(self):
        from vault_ai_provider import PROVIDERS, PROVIDER_OPENAI
        self.assertEqual(PROVIDERS, (PROVIDER_OPENAI,))
        self.assertEqual(PROVIDER_OPENAI, "openai")

    def test_active_provider_always_openai(self):
        from vault_ai_provider import (
            active_provider_name,
            active_fallback_provider_name,
        )
        self.assertEqual(active_provider_name(), "openai")
        self.assertEqual(active_fallback_provider_name(), "openai")

    def test_ai_config_only_exposes_openai_model_fields(self):
        from vault_config import AIConfig
        names = set(AIConfig.__dataclass_fields__.keys())
                             
        self.assertIn("openai_chat_model", names)
        self.assertIn("openai_intent_model", names)
                             
        for n in (
            "hermes_chat_model",
            "hermes_intent_model",
            "hermes_base_url",
            "hermes_api_key_env",
            "hermes_resident_enabled",
        ):
            self.assertNotIn(
                n, names,
                f"AIConfig still exposes Hermes field {n!r}",
            )


if __name__ == "__main__":
    unittest.main()
