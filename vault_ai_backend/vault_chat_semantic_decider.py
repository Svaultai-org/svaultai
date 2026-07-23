"""Semantic decider — the model-side of the chat brain.

The decider takes a ``TurnSnapshot`` and asks the LLM which of a
small set of tools should handle the turn. The LLM's answer is a
structured decision (name + args + confidence + reasoning). The
decider validates the structure but does NOT execute anything —
authorization is the policy layer's job (``vault_chat_policy``),
and execution is the router's job (``vault_chat_decision_router``).

Failure modes are exhaustively handled here so a broken model
response can never crash the chat pipeline:

    * timeout                → Decision(FALLTHROUGH, low confidence)
    * transport error        → Decision(FALLTHROUGH, low confidence)
    * empty content          → Decision(FALLTHROUGH, low confidence)
    * malformed JSON         → Decision(FALLTHROUGH, low confidence)
    * missing fields         → Decision(FALLTHROUGH, low confidence)
    * unknown tool name      → Decision(FALLTHROUGH, low confidence)
    * args_schema mismatch   → Decision(FALLTHROUGH, low confidence)

A low-confidence or fallthrough result never authorizes a
destructive action — the policy layer refuses it.

Response wire format (JSON only, no prose):

    {
      "tool":       "<one of tool_registry.tool_names()>",
      "args":       { ... tool-specific schema },
      "confidence": "low" | "medium" | "high",
      "why":        "one short sentence, model-facing rationale"
    }

The decider prompt is written to bias the model AWAY from action
on ambiguity and TOWARD ``request_clarification`` or
``fallthrough``. Aggressive interpretations are rejected by the
policy layer, but making the model conservative in the first
place saves a round-trip.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from vault_chat_pending_action import KIND_NONE
from vault_chat_tool_registry import (
    TOOL_CANCEL_PENDING_DELETE,
    TOOL_CANCEL_PENDING_SAVE,
    TOOL_CONFIRM_PENDING_DELETE,
    TOOL_CONFIRM_PENDING_SAVE,
    TOOL_CONVERSATIONAL_REPLY,
    TOOL_FALLTHROUGH,
    TOOL_REQUEST_CLARIFICATION,
    all_tools,
    get_tool,
    tool_names,
    tools_for_prompt,
)
from vault_chat_turn_snapshot import TurnSnapshot


logger = logging.getLogger(__name__)


DECIDER_TIMEOUT_S: float = 8.0
DECIDER_MAX_TOKENS: int = 400


CONFIDENCE_HIGH:   str = "high"
CONFIDENCE_MEDIUM: str = "medium"
CONFIDENCE_LOW:    str = "low"

CONFIDENCE_ORDER: tuple[str, ...] = (
    CONFIDENCE_LOW, CONFIDENCE_MEDIUM, CONFIDENCE_HIGH,
)


@dataclass(frozen=True)
class Decision:
    tool:        str
    args:        dict = field(default_factory=dict)
    confidence:  str  = CONFIDENCE_LOW
    why:         str  = ""
    raw:         str  = ""
    error:       str  = ""

    def is_fallthrough(self) -> bool:
        return self.tool == TOOL_FALLTHROUGH


FALLTHROUGH_LOW: Decision = Decision(
    tool=TOOL_FALLTHROUGH,
    args={},
    confidence=CONFIDENCE_LOW,
    why="decider fell through",
    raw="",
    error="",
)


def _make_fallthrough(reason: str, raw: str = "") -> Decision:
    return Decision(
        tool=TOOL_FALLTHROUGH,
        args={},
        confidence=CONFIDENCE_LOW,
        why="",
        raw=raw or "",
        error=reason,
    )


# -------------------------------------------------------------------
# Prompt authoring
# -------------------------------------------------------------------

_SYSTEM_PROMPT: str = """\
You are the intent arbiter for the VaultAI chat brain.

You will be given a snapshot of the current chat turn and a small
set of tools you can invoke. You must return a SINGLE JSON object
choosing exactly one tool. No prose, no explanation outside JSON.

The tools you can invoke — CLOSED SET. Do not invent tool names.
{tools_block}

Your job is to interpret the user's message SEMANTICALLY with
respect to the pending action and recent conversation. You do not
execute anything. The backend re-checks every choice against
deterministic policies before running it.

RULES

1. If a pending action is present, the user's reply is most likely
   about that pending action. Interpret confirmation / rejection
   with common sense. Different natural phrasings that MEAN "yes
   go ahead" all count as confirmation; different phrasings that
   MEAN "no don't" all count as rejection. Do NOT match against a
   list of phrases — reason about MEANING.

2. If the pending action is destructive (``is_destructive: true``,
   e.g. a pending delete), be extra careful. Choose the confirm
   tool ONLY if the user's reply unambiguously means "go ahead
   with the pending delete". Ambiguity → ``request_clarification``
   or ``fallthrough``. Never assume affirmative when the user
   changed topic.

3. If the user's reply looks unrelated to the pending action (a
   new question, a topic switch, a different vault ask), pick
   ``fallthrough`` — the existing pipeline will handle it. Do
   NOT try to confirm a pending action on an unrelated message.

4. If the user's reference is ambiguous (multiple candidates could
   match, or there is nothing in context to resolve "that one"),
   pick ``request_clarification`` and ask a short, specific
   question.

5. For ordinary conversation, greetings, questions about VaultAI's
   capabilities, or explanations that do NOT require reading or
   writing vault data, pick ``conversational_reply`` and write a
   short helpful answer. Never claim you saved, deleted, changed
   or found anything in ``conversational_reply`` — those require
   real tool invocations.

6. For everything else — vault reads, credential generation, file
   searches, secure-item saves, wallet operations, and so on —
   pick ``fallthrough`` so the existing pipeline can classify and
   execute the request. Do NOT invent tool names for tasks that
   aren't in the closed set above.

7. Confidence:
     * ``high``   = "I am sure this is the right choice"
     * ``medium`` = "I am fairly sure but this could go another way"
     * ``low``    = "I am guessing"
   The policy layer refuses destructive actions unless confidence
   is ``high``, so LOW-confidence confirms of destructive actions
   are functionally equivalent to fallthrough. Prefer
   ``request_clarification`` over LOW-confidence destructive
   confirms.

8. Never invent an ``action_id``. If the tool needs one, copy it
   verbatim from ``pending_action.action_id`` in the snapshot.

Return a single JSON object with EXACTLY these keys:
  {{
    "tool":       "<tool name>",
    "args":       {{ ... }},
    "confidence": "high" | "medium" | "low",
    "why":        "one short sentence"
  }}

No text before or after the JSON. No markdown fences.
"""


def _render_tools_block() -> str:
    lines: list[str] = []
    for t in tools_for_prompt():
        marker = ""
        if t["destructive"]:
            marker = " (destructive)"
        elif t["requires_pending"]:
            marker = f" (requires_pending={t['requires_pending']})"
        lines.append(
            f"  * {t['name']}{marker} — {t['description']}"
        )
    return "\n".join(lines)


def build_prompt(snapshot: TurnSnapshot) -> list[dict]:
    system_body = _SYSTEM_PROMPT.replace(
        "{tools_block}", _render_tools_block(),
    )
    user_payload = {
        "snapshot": snapshot.to_prompt_dict(),
        "instructions": (
            "Choose exactly one tool. Return only JSON."
        ),
    }
    return [
        {"role": "system", "content": system_body},
        {
            "role":    "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        },
    ]


# -------------------------------------------------------------------
# JSON parsing + validation
# -------------------------------------------------------------------

def _extract_json_object(text: str) -> Optional[dict]:
    """Salvage the first balanced JSON object from the string.
    Handles the common case where the model wraps its output in
    accidental prose or a code fence. Returns None on failure.
    """
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        fence_end = stripped.find("\n")
        if fence_end != -1:
            stripped = stripped[fence_end + 1:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    stripped = stripped.strip()
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    # brace-scan fallback
    start = stripped.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(stripped)):
            ch = stripped[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    chunk = stripped[start:i + 1]
                    try:
                        parsed = json.loads(chunk)
                        return parsed if isinstance(parsed, dict) else None
                    except Exception:
                        break
        start = stripped.find("{", start + 1)
    return None


def _validate_args_against_schema(
    tool_name: str, args: Any,
) -> tuple[bool, str]:
    """Lightweight JSON-Schema-ish validation limited to the
    shapes the tool registry actually declares (object types with
    required scalar properties, an optional enum, and additional-
    Properties=false). Returns (ok, reason)."""
    spec = get_tool(tool_name)
    if spec is None:
        return False, f"unknown tool {tool_name!r}"
    schema = spec.args_schema or {}
    if schema.get("type") != "object":
        return True, ""
    if not isinstance(args, dict):
        return False, "args must be an object"
    required = list(schema.get("required") or [])
    properties = dict(schema.get("properties") or {})
    additional = schema.get("additionalProperties", True)
    for req in required:
        if req not in args:
            return False, f"missing required arg {req!r}"
    if additional is False:
        for k in args:
            if k not in properties:
                return False, f"unexpected arg {k!r}"
    for name, subschema in properties.items():
        if name not in args:
            continue
        value = args[name]
        expected_type = subschema.get("type")
        if expected_type == "string":
            if not isinstance(value, str):
                return False, f"arg {name!r} must be string"
            min_len = subschema.get("minLength")
            if isinstance(min_len, int) and len(value) < min_len:
                return False, f"arg {name!r} shorter than {min_len}"
            max_len = subschema.get("maxLength")
            if isinstance(max_len, int) and len(value) > max_len:
                return False, f"arg {name!r} longer than {max_len}"
            enum = subschema.get("enum")
            if isinstance(enum, list) and value not in enum:
                return False, f"arg {name!r} not in enum"
        elif expected_type == "number":
            if not isinstance(value, (int, float)):
                return False, f"arg {name!r} must be number"
        elif expected_type == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                return False, f"arg {name!r} must be int"
        elif expected_type == "boolean":
            if not isinstance(value, bool):
                return False, f"arg {name!r} must be bool"
    return True, ""


def _validate_decision(raw_obj: dict) -> Decision:
    tool = raw_obj.get("tool")
    args = raw_obj.get("args") or {}
    confidence = raw_obj.get("confidence") or CONFIDENCE_LOW
    why = raw_obj.get("why") or ""

    if not isinstance(tool, str) or tool not in tool_names():
        return _make_fallthrough(
            f"unknown_tool:{tool!r}", raw=json.dumps(raw_obj)[:400],
        )
    if not isinstance(args, dict):
        return _make_fallthrough(
            f"args_not_object:{tool!r}",
            raw=json.dumps(raw_obj)[:400],
        )
    if confidence not in CONFIDENCE_ORDER:
        confidence = CONFIDENCE_LOW
    if not isinstance(why, str):
        why = ""

    ok, reason = _validate_args_against_schema(tool, args)
    if not ok:
        return _make_fallthrough(
            f"args_schema:{reason}",
            raw=json.dumps(raw_obj)[:400],
        )

    return Decision(
        tool=tool,
        args=dict(args),
        confidence=confidence,
        why=why[:400],
        raw="",
        error="",
    )


# -------------------------------------------------------------------
# LLM call
# -------------------------------------------------------------------

async def decide(
    snapshot: TurnSnapshot,
    *,
    timeout_s: Optional[float] = None,
    ai_provider: Optional[Any] = None,
) -> Decision:
    """Run the model call, return a validated ``Decision``.

    NEVER raises. On any exception path returns a fallthrough
    Decision with ``error`` populated so callers / logs can see
    why.
    """
    # Trivial fast-path: if there is neither a pending action nor
    # an active entity nor a nontrivial user message, don't waste
    # a model call — just fall through.
    if (
        snapshot.pending_action.kind == KIND_NONE
        and snapshot.active_entity is None
        and len(snapshot.user_message) < 2
    ):
        return _make_fallthrough("empty_or_trivial", raw="")

    messages = build_prompt(snapshot)

    if ai_provider is None:
        try:
            from vault_ai_provider import chat_complete_with_fallback
            ai_provider = chat_complete_with_fallback
        except Exception:
            logger.exception("[DECIDER] provider_import_failed")
            return _make_fallthrough("provider_import_failed")

    started = time.time()
    try:
        result = await asyncio.wait_for(
            ai_provider(
                messages=messages,
                model_kind="intent",
                temperature=0.0,
                max_tokens=DECIDER_MAX_TOKENS,
                response_format={"type": "json_object"},
                timeout=timeout_s or DECIDER_TIMEOUT_S,
            ),
            timeout=(timeout_s or DECIDER_TIMEOUT_S) + 2.0,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "[DECIDER] timeout_after=%.2fs pending_kind=%s",
            time.time() - started,
            snapshot.pending_action.kind,
        )
        return _make_fallthrough("timeout")
    except Exception as exc:
        logger.warning(
            "[DECIDER] transport_error type=%s pending_kind=%s",
            type(exc).__name__,
            snapshot.pending_action.kind,
        )
        return _make_fallthrough(f"transport:{type(exc).__name__}")

    content = ""
    try:
        content = getattr(result, "content", "") or ""
    except Exception:
        content = ""
    if not content:
        return _make_fallthrough("empty_content")

    raw_obj = _extract_json_object(content)
    if raw_obj is None:
        return _make_fallthrough("json_parse_failed", raw=content[:400])

    decision = _validate_decision(raw_obj)
    _log_decision(snapshot, decision, elapsed=time.time() - started)
    return decision


def _log_decision(
    snapshot: TurnSnapshot,
    decision: Decision,
    *,
    elapsed: float,
) -> None:
    """Structured log line — safe fields only. Never logs user
    message text, tool args (which may contain the action_id and
    a clarification question string), or the model's why."""
    logger.info(
        "[DECIDER] tool=%s conf=%s pending_kind=%s "
        "is_dest=%s active_entity=%s elapsed_ms=%d error=%s",
        decision.tool,
        decision.confidence,
        snapshot.pending_action.kind,
        bool(snapshot.pending_action.is_destructive),
        (snapshot.active_entity.entity_type
         if snapshot.active_entity else "-"),
        int(elapsed * 1000),
        decision.error or "-",
    )


__all__ = [
    "DECIDER_TIMEOUT_S",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_LOW",
    "CONFIDENCE_ORDER",
    "Decision",
    "FALLTHROUGH_LOW",
    "build_prompt",
    "decide",
]
