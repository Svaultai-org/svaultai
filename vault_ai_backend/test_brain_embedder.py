

from __future__ import annotations

import asyncio
import os
import unittest

from brain_embedder import (
    embed_for_brain,
    make_query_embed_fn,
    EMBED_MODEL,
    EMBED_DIM,
    MAX_INPUT_CHARS,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _StubResponse:

    def __init__(self, vec):
        self.data = [type("D", (), {"embedding": vec})()]


class _StubEmbeddingsAPI:

    def __init__(self, *, return_vec=None, raise_exc=None):
        self.return_vec = return_vec or [0.1] * EMBED_DIM
        self.raise_exc = raise_exc
        self.last_model = None
        self.last_input = None

    async def create(self, *, model, input):
        self.last_model = model
        self.last_input = input
        if self.raise_exc is not None:
            raise self.raise_exc
        return _StubResponse(self.return_vec)


class _StubClient:
    def __init__(self, *, return_vec=None, raise_exc=None):
        self.embeddings = _StubEmbeddingsAPI(
            return_vec=return_vec, raise_exc=raise_exc,
        )


class FullTextEmbedTests(unittest.TestCase):


    def test_embed_2000_char_chunk(self):
        client = _StubClient()
        text = "a" * 2000
        vec = _run(embed_for_brain(client, text))
        self.assertEqual(len(vec), EMBED_DIM)
        self.assertEqual(client.embeddings.last_model, EMBED_MODEL)
                                                        
        self.assertEqual(len(client.embeddings.last_input), 2000)

    def test_input_cap_protects_against_giant_input(self):
        client = _StubClient()
                                                                    
                                                                  
        text = "x" * (MAX_INPUT_CHARS + 5000)
        _run(embed_for_brain(client, text))
        self.assertEqual(
            len(client.embeddings.last_input), MAX_INPUT_CHARS,
        )


class EmptyInputTests(unittest.TestCase):
    def test_none_client_returns_none(self):
        vec = _run(embed_for_brain(None, "hello"))
        self.assertIsNone(vec)

    def test_empty_string_returns_none(self):
        vec = _run(embed_for_brain(_StubClient(), ""))
        self.assertIsNone(vec)

    def test_whitespace_only_returns_none(self):
        vec = _run(embed_for_brain(_StubClient(), "   \n  "))
        self.assertIsNone(vec)


class FeatureFlagIndependentTests(unittest.TestCase):


    def test_works_when_legacy_flag_unset(self):
        prior = os.environ.pop("VAULTAI_SEMANTIC_SEARCH_ENABLED", None)
        try:
            client = _StubClient()
            vec = _run(embed_for_brain(client, "hello"))
            self.assertEqual(len(vec), EMBED_DIM)
        finally:
            if prior is not None:
                os.environ["VAULTAI_SEMANTIC_SEARCH_ENABLED"] = prior

    def test_works_when_legacy_flag_false(self):
        prior = os.environ.get("VAULTAI_SEMANTIC_SEARCH_ENABLED")
        os.environ["VAULTAI_SEMANTIC_SEARCH_ENABLED"] = "false"
        try:
            client = _StubClient()
            vec = _run(embed_for_brain(client, "hello"))
            self.assertEqual(len(vec), EMBED_DIM)
        finally:
            if prior is None:
                os.environ.pop("VAULTAI_SEMANTIC_SEARCH_ENABLED", None)
            else:
                os.environ["VAULTAI_SEMANTIC_SEARCH_ENABLED"] = prior


class DimensionMismatchTests(unittest.TestCase):
    def test_short_vector_returns_none(self):
        client = _StubClient(return_vec=[0.0] * 128)             
        vec = _run(embed_for_brain(client, "hi"))
        self.assertIsNone(vec)


class APIRaisesTests(unittest.TestCase):


    def test_propagates_exception(self):
        client = _StubClient(raise_exc=RuntimeError("rate limited"))
        with self.assertRaises(RuntimeError):
            _run(embed_for_brain(client, "hello"))


class MakeQueryEmbedFnTests(unittest.TestCase):
    def test_returns_callable_that_embeds(self):
        client = _StubClient()
        fn = make_query_embed_fn(client)
        vec = _run(fn("anything about a blue contract"))
        self.assertEqual(len(vec), EMBED_DIM)
        self.assertEqual(client.embeddings.last_model, EMBED_MODEL)


class SourceSafetyTests(unittest.TestCase):


    def test_no_input_logging(self):
        import ast
        import pathlib
        src_path = (
            pathlib.Path(__file__).parent / "brain_embedder.py"
        )
        tree = ast.parse(src_path.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = ""
            if isinstance(func, ast.Attribute):
                name = func.attr
            if name not in {"info", "warning", "error", "exception", "debug"}:
                continue
                                                                  
                                                              
            for arg in node.args:
                if isinstance(arg, ast.JoinedStr):
                    for v in arg.values:
                        if isinstance(v, ast.FormattedValue):
                            tgt = v.value
                            if isinstance(tgt, ast.Name) and \
                               tgt.id in {"text", "payload", "input"}:
                                offenders.append(ast.unparse(node))
        self.assertEqual(
            offenders, [],
            "brain_embedder must NEVER log the input text — found: "
            + "; ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
