"""Simulator-driven evaluation runner for the chat brain.

For each row in ``chat_brain_eval_2026_07_24.jsonl`` we:

    1. Reset the shared chat-state store to an in-memory backend.
    2. Optionally seed a pending delete (per the row's
       ``pending_kind`` field).
    3. Install a **simulated semantic model** (the same
       deterministic emulator used by
       ``test_chat_semantic_paraphrase_2026_07_24``) as the
       decider's ai_provider.
    4. Run the brain end-to-end.
    5. Compare the brain's chosen tool + reply against the
       expected tool declared in the eval row.

The purpose is NOT to prove OpenAI recognizes every phrasing — it
is to prove that when the model's decision matches the semantic
expectation, the policy + router pipeline behaves correctly. This
gives a category-by-category score of pipeline correctness under
expected semantic outputs.

For a REAL LLM evaluation, wire the same runner to
``chat_complete_with_fallback`` from ``vault_ai_provider`` and
rerun. That is a separate cost / API-key gated step; the CI eval
uses the simulator so it is fully deterministic and offline.

Usage:

    python -m evals.chat_brain_eval_runner

Prints per-category pass/fail counts and an overall percentage.
Exits nonzero on any failure to make CI catch regressions.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Optional  # noqa: F401

# ensure the parent (backend) directory is importable when running
# as a module from any cwd.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

from vault_chat_semantic_decider import (  # noqa: E402
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
)
from vault_chat_state_store import (  # noqa: E402
    InMemoryChatStateBackend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)
from vault_chat_tool_registry import (  # noqa: E402
    TOOL_CANCEL_PENDING_DELETE,
    TOOL_CONFIRM_PENDING_DELETE,
    TOOL_CONVERSATIONAL_REPLY,
    TOOL_FALLTHROUGH,
    TOOL_REQUEST_CLARIFICATION,
)


EVAL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "chat_brain_eval_2026_07_24.jsonl",
)


_CONFIRM_TOKEN = (
    r"(?:"
    r"yes|yea|yeah|yep|yup|yee|y|ya|"
    r"ok|okay|k|"
    r"sure|fine|correct|right|thing|"
    r"confirm(?:ed)?|"
    r"proceed|approved|affirmative|"
    r"please|now|plz|"
    r"go\s*ahead|do\s*it|"
    r"go(?:\s+for\s+it)?|"
    r"delete(?:\s+(?:it|that|now))?|"
    r"remove(?:\s+(?:it|that))?|"
    r"it|that|this"
    r")"
)

CONFIRM_RE = re.compile(
    r"^\s*(?:"
    r"(?:{tok})(?:[\s.,!]+{tok})*"
    r"|i'?m\s+sure|that'?s\s+right"
    r")\s*[.!,]?\s*$".format(tok=_CONFIRM_TOKEN),
    re.IGNORECASE,
)

CANCEL_RE = re.compile(
    r"^\s*("
    r"no|nope|nah|n|"
    r"cancel(?:\s*that)?|stop|halt|"
    r"don'?t|do\s*not|"
    r"keep\s+(?:it|them|that)|"
    r"never\s*mind|nevermind|"
    r"on\s*second\s*thought(?:\s*no)?|"
    r"actually\s*(?:no|don'?t|do\s*not)"
    r")\s*[.!,]?\s*"
    r"(?:please|now|it|that)?\s*[.!,]?\s*$",
    re.IGNORECASE,
)


def _semantic_expectation(user_message: str,
                          pending_kind: Optional[str]) -> tuple[str, dict, str]:
    """Emulate what a well-behaved model SHOULD return.

    Returns (tool, args, confidence)."""
    stripped = (user_message or "").strip()
    if pending_kind == "delete_secure_item":
        if CONFIRM_RE.match(stripped):
            return TOOL_CONFIRM_PENDING_DELETE, {
                "action_id": "PENDING_ACTION_ID",
            }, CONFIDENCE_HIGH
        if CANCEL_RE.match(stripped):
            return TOOL_CANCEL_PENDING_DELETE, {
                "action_id": "PENDING_ACTION_ID",
            }, CONFIDENCE_HIGH
        if ("which" in stripped.lower()
                or "what does that" in stripped.lower()
                or "the other" in stripped.lower()
                or "the second" in stripped.lower()):
            return TOOL_REQUEST_CLARIFICATION, {
                "question": "Which one did you mean?",
            }, CONFIDENCE_MEDIUM
        if stripped.lower().startswith("delete my"):
            # Topic-switch to a different delete target — fall through.
            return TOOL_FALLTHROUGH, {}, CONFIDENCE_MEDIUM
        return TOOL_FALLTHROUGH, {}, CONFIDENCE_MEDIUM
    # No pending action
    if stripped.lower() in {"hi", "hello", "hey"}:
        return TOOL_CONVERSATIONAL_REPLY, {
            "reply": "Hi! How can I help with your vault?",
        }, CONFIDENCE_HIGH
    if ("what can you do" in stripped.lower()
            or "what is vaultai" in stripped.lower()
            or "how does" in stripped.lower()):
        return TOOL_CONVERSATIONAL_REPLY, {
            "reply": "I help you manage your encrypted vault.",
        }, CONFIDENCE_HIGH
    if stripped.lower() in {"delete it"}:
        return TOOL_REQUEST_CLARIFICATION, {
            "question": "Which item did you mean?",
        }, CONFIDENCE_MEDIUM
    return TOOL_FALLTHROUGH, {}, CONFIDENCE_LOW


class _StubResult:
    def __init__(self, content: str):
        self.content = content


def _build_provider(pending_id: str):
    async def _provider(**kwargs):
        # Extract user message.
        user_text = ""
        for m in kwargs.get("messages") or []:
            if m.get("role") == "user":
                try:
                    p = json.loads(m.get("content") or "{}")
                    user_text = str(p.get("snapshot", {}).get("user_message") or "")
                except Exception:
                    user_text = m.get("content") or ""
                break
        tool, args, conf = _semantic_expectation(
            user_text,
            _current_pending_kind(),
        )
        # Substitute the real pending action_id if the emulator
        # asked for one.
        if isinstance(args, dict) and args.get("action_id") == "PENDING_ACTION_ID":
            args["action_id"] = pending_id
        return _StubResult(json.dumps({
            "tool": tool, "args": args, "confidence": conf,
            "why": "eval-sim",
        }))
    return _provider


def _build_live_provider(pending_id: str):
    """Real production-LLM provider — wraps
    ``chat_complete_with_fallback`` and substitutes the current
    pending action_id if the model quotes ``PENDING_ACTION_ID``
    verbatim (defensive; a well-behaved model reads the
    real id from the snapshot). No emulator involved."""
    from vault_ai_provider import chat_complete_with_fallback

    async def _provider(**kwargs):
        result = await chat_complete_with_fallback(**kwargs)
        content = result.content or ""
        _LAST_RAW_MODEL_OUTPUT["content"] = content
        try:
            parsed = json.loads(content)
            if (isinstance(parsed, dict)
                    and isinstance(parsed.get("args"), dict)
                    and parsed["args"].get("action_id") == "PENDING_ACTION_ID"):
                parsed["args"]["action_id"] = pending_id
                content = json.dumps(parsed)
            if isinstance(parsed, dict):
                _LAST_RAW_MODEL_OUTPUT["confidence"] = str(
                    parsed.get("confidence") or "",
                )
        except Exception:
            pass

        class _R:
            pass
        r = _R()
        r.content = content
        r.model = result.model
        return r
    return _provider


_pending_kind_holder: dict = {"kind": None}


def _current_pending_kind() -> Optional[str]:
    return _pending_kind_holder["kind"]


def _install_secure_item_stub():
    import vault_secure_item_save as ss

    # Signature must match production; db_executor is required.
    def _exec(*, vault_id, key, db_executor):
        return {"band": "deleted",
                "message": "Deleted saved item from your vault."}

    def _cancel(*, vault_id):
        return {"band": "delete_cancelled",
                "message": "Okay — I won't delete it."}

    ss._execute_pending_delete = _exec
    ss._cancel_pending_delete = _cancel


_LAST_RAW_MODEL_OUTPUT: dict = {"content": "", "confidence": ""}


async def _run_row(row: dict, *, live: bool = False) -> tuple[str, str, str]:
    """Return (chosen_tool, reply_text, notes)."""
    import vault_chat_semantic_decider as sd
    from vault_chat_brain import run_chat_brain
    _LAST_RAW_MODEL_OUTPUT["content"] = ""
    _LAST_RAW_MODEL_OUTPUT["confidence"] = ""

    reset_chat_state_backend_for_tests()
    install_backend_for_tests(InMemoryChatStateBackend())
    _install_secure_item_stub()

    pending_kind = row.get("pending_kind")
    _pending_kind_holder["kind"] = pending_kind
    pending_id = ""
    if pending_kind == "delete_secure_item":
        from vault_secure_item_delete_confirmation import (
            get_pending_delete_intent, store_delete_intent,
        )
        store_delete_intent(
            vault_id="vault-eval", service="Instagram",
            item_type="login",
        )
        intent = get_pending_delete_intent(vault_id="vault-eval")
        pending_id = intent.intent_id if intent else ""

    if live:
        provider = _build_live_provider(pending_id)
    else:
        provider = _build_provider(pending_id)
    orig = sd.decide

    async def patched(snapshot, *, timeout_s=None, ai_provider=None):
        return await orig(snapshot, timeout_s=timeout_s,
                          ai_provider=(ai_provider or provider))

    sd.decide = patched
    try:
        result = await run_chat_brain(
            vault_id="vault-eval", session_id="sess-eval",
            turn_id="t-1", vault_name="Personal",
            reply_language="en",
            user_message=row["user_message"],
            memory=dict(), key=b"\x00" * 32,
        )
    finally:
        sd.decide = orig

    return (
        (result.tool if result.handled else TOOL_FALLTHROUGH),
        result.reply_text,
        "",
    )


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description=(
        "Chat brain eval runner. Default: deterministic semantic "
        "emulator. --live: hits the real production LLM via "
        "chat_complete_with_fallback (costs API tokens)."
    ))
    p.add_argument("--live", action="store_true",
                   help="Use real production LLM instead of the emulator")
    p.add_argument("--limit", type=int, default=0,
                   help="Only run the first N rows (0 = all)")
    p.add_argument("--categories", type=str, default="",
                   help="Comma-separated category prefixes to include")
    args = p.parse_args(argv or sys.argv[1:])

    if not os.path.exists(EVAL_PATH):
        print(f"eval corpus not found at {EVAL_PATH}")
        return 2
    rows: list[dict] = []
    with open(EVAL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception as e:
                print(f"skipping malformed row: {e}")
    if not rows:
        print("empty corpus")
        return 2

    if args.categories:
        wanted = {c.strip() for c in args.categories.split(",") if c.strip()}
        rows = [r for r in rows if r.get("category") in wanted]
    if args.limit > 0:
        rows = rows[:args.limit]

    mode = "LIVE (real LLM)" if args.live else "EMULATOR (deterministic)"
    print(f"chat brain eval: mode={mode}  rows={len(rows)}")
    print("")

    pass_count = 0
    fail_count = 0
    by_category: dict = defaultdict(lambda: {"pass": 0, "fail": 0})

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        for row in rows:
            expected_tool = row.get("expected_tool")
            chosen_tool, reply, _notes = loop.run_until_complete(
                _run_row(row, live=args.live),
            )
            row_ok = (chosen_tool == expected_tool)
            confirm_expects = row.get("confirm_reply_contains")
            if row_ok and confirm_expects:
                row_ok = confirm_expects.lower() in (reply or "").lower()
            must_not = row.get("must_not_contain")
            if row_ok and must_not:
                if must_not.lower() in (reply or "").lower():
                    row_ok = False
            cat = row.get("category", "uncategorized")
            if row_ok:
                pass_count += 1
                by_category[cat]["pass"] += 1
            else:
                fail_count += 1
                by_category[cat]["fail"] += 1
                raw = ""
                if args.live:
                    raw_content = _LAST_RAW_MODEL_OUTPUT.get("content") or ""
                    if raw_content:
                        raw = f" raw={raw_content[:200]!r}"
                print(
                    f"FAIL {row.get('id', '?'):<8} [{cat}] "
                    f"expected={expected_tool} chosen={chosen_tool} "
                    f"msg={row['user_message']!r}{raw}",
                )
    finally:
        loop.close()

    total = pass_count + fail_count
    pct = (100.0 * pass_count / total) if total else 0.0
    print("")
    print(f"===== chat brain eval [{mode}]: "
          f"{pass_count}/{total} ({pct:.1f}%) =====")
    for cat, counts in sorted(by_category.items()):
        c_total = counts["pass"] + counts["fail"]
        c_pct = 100.0 * counts["pass"] / c_total if c_total else 0.0
        print(f"  {cat:<32s}  {counts['pass']:>3d} / {c_total:>3d}  "
              f"({c_pct:5.1f}%)")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
