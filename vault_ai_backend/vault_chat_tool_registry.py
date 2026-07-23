"""General tool/capability registry for the VaultAI chat brain.

The semantic decider (``vault_chat_semantic_decider``) chooses
between "confirm the pending action", "reject the pending action",
"invoke a tool", "ask for clarification", "answer conversationally",
or "fall through to the existing pipeline". When it chooses
``invoke_tool``, it names one of the tools listed in this registry.

Each tool entry declares:

    * ``name``  — stable identifier the model uses. Kebab / snake
      case, ASCII only.
    * ``description`` — one-line human-readable summary the model
      sees in its context.
    * ``args_schema`` — a JSON-Schema-ish descriptor of the
      arguments. Passed to the model as text; also validated by
      the policy layer before dispatch.
    * ``destructive`` — True iff calling this tool mutates or
      deletes vault state. Destructive tools are gated by
      ``vault_chat_policy`` (must be authorized by a matching
      pending action + high confidence).
    * ``requires_pending`` — kind string from
      ``vault_chat_pending_action`` that a pending action must
      match. ``None`` if the tool doesn't require a pending
      action.
    * ``category`` — freeform grouping for the registry index.

The registry is intentionally small in this initial release —
just enough to route the confirmation/rejection/clarification
cases that were the root cause of the 2026-07-24 incident. New
tools can be added later without changing the semantic decider
code — they will show up in the model's tool list automatically.

There is no per-tool executor here; the decision router
(``vault_chat_decision_router``) is what actually invokes the
backend tool. That keeps this file inert — a description of what
tools exist, nothing more.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from vault_chat_pending_action import (
    KIND_DELETE_SECURE_ITEM,
    KIND_SAVE_ATTACHMENT,
    KIND_SAVE_CREDENTIAL,
    KIND_SAVE_LOGIN_DRAFT,
    KIND_SAVE_SECURE_ITEM,
)


# -------------------------------------------------------------------
# Tool names — closed set. The model may ONLY return one of these.
# -------------------------------------------------------------------

TOOL_CONFIRM_PENDING_DELETE:  str = "confirm_pending_delete"
TOOL_CANCEL_PENDING_DELETE:   str = "cancel_pending_delete"
TOOL_CONFIRM_PENDING_SAVE:    str = "confirm_pending_save"
TOOL_CANCEL_PENDING_SAVE:     str = "cancel_pending_save"
TOOL_REQUEST_CLARIFICATION:   str = "request_clarification"
TOOL_CONVERSATIONAL_REPLY:    str = "conversational_reply"
TOOL_FALLTHROUGH:             str = "fallthrough"


@dataclass(frozen=True)
class ToolSpec:
    name:              str
    description:       str
    args_schema:       dict
    destructive:       bool
    requires_pending:  Optional[str]
    category:          str


_TOOLS: dict[str, ToolSpec] = {}


def _register(spec: ToolSpec) -> None:
    if spec.name in _TOOLS:
        raise RuntimeError(f"duplicate tool {spec.name!r}")
    _TOOLS[spec.name] = spec


_register(ToolSpec(
    name=TOOL_CONFIRM_PENDING_DELETE,
    description=(
        "Confirm and execute the currently pending delete action. "
        "Use ONLY when the user's reply clearly means 'yes go ahead' "
        "with respect to the pending delete action described in the "
        "context. The backend independently re-checks that a matching "
        "pending delete exists for this session before executing."
    ),
    args_schema={
        "type": "object",
        "properties": {
            "action_id": {
                "type": "string",
                "description": (
                    "The pending action's action_id from the context. "
                    "Copy verbatim."
                ),
            },
        },
        "required": ["action_id"],
        "additionalProperties": False,
    },
    destructive=True,
    requires_pending=KIND_DELETE_SECURE_ITEM,
    category="confirmation",
))

_register(ToolSpec(
    name=TOOL_CANCEL_PENDING_DELETE,
    description=(
        "Cancel the currently pending delete action. Use when the "
        "user's reply clearly means they no longer want to delete."
    ),
    args_schema={
        "type": "object",
        "properties": {
            "action_id": {"type": "string"},
        },
        "required": ["action_id"],
        "additionalProperties": False,
    },
    destructive=False,
    requires_pending=KIND_DELETE_SECURE_ITEM,
    category="confirmation",
))

_register(ToolSpec(
    name=TOOL_CONFIRM_PENDING_SAVE,
    description=(
        "Confirm the currently pending save action (credential draft, "
        "login draft, secure item draft, or a freshly-uploaded "
        "attachment that was bound to THIS session). Use ONLY when "
        "the user's reply clearly means 'yes save it'."
    ),
    args_schema={
        "type": "object",
        "properties": {
            "action_id": {"type": "string"},
            "pending_kind": {
                "type": "string",
                "enum": [
                    KIND_SAVE_CREDENTIAL,
                    KIND_SAVE_LOGIN_DRAFT,
                    KIND_SAVE_ATTACHMENT,
                    KIND_SAVE_SECURE_ITEM,
                ],
            },
        },
        "required": ["action_id", "pending_kind"],
        "additionalProperties": False,
    },
    destructive=False,
    requires_pending=None,
    category="confirmation",
))

_register(ToolSpec(
    name=TOOL_CANCEL_PENDING_SAVE,
    description=(
        "Cancel the currently pending save action. Use when the "
        "user's reply clearly means 'don't save that'."
    ),
    args_schema={
        "type": "object",
        "properties": {
            "action_id": {"type": "string"},
        },
        "required": ["action_id"],
        "additionalProperties": False,
    },
    destructive=False,
    requires_pending=None,
    category="confirmation",
))

_register(ToolSpec(
    name=TOOL_REQUEST_CLARIFICATION,
    description=(
        "Ask the user a concise clarification question. Use when the "
        "reply is ambiguous, references something that isn't "
        "grounded, or asks about an item that has multiple matches. "
        "Never guess."
    ),
    args_schema={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "minLength": 3,
                "maxLength": 400,
                "description": (
                    "The exact question to render to the user. Keep "
                    "it short and specific."
                ),
            },
        },
        "required": ["question"],
        "additionalProperties": False,
    },
    destructive=False,
    requires_pending=None,
    category="clarification",
))

_register(ToolSpec(
    name=TOOL_CONVERSATIONAL_REPLY,
    description=(
        "Answer the user conversationally without invoking any vault "
        "tool. Use for ordinary chat, greetings, general questions "
        "about VaultAI, or explanations that don't require reading "
        "or writing vault data. Never claim an item was saved / "
        "deleted / changed here — those require real tool "
        "invocations."
    ),
    args_schema={
        "type": "object",
        "properties": {
            "reply": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1200,
            },
        },
        "required": ["reply"],
        "additionalProperties": False,
    },
    destructive=False,
    requires_pending=None,
    category="conversation",
))

_register(ToolSpec(
    name=TOOL_FALLTHROUGH,
    description=(
        "Yield to the existing chat pipeline. Use when the user's "
        "request needs a vault tool that is not listed here — the "
        "downstream pipeline can classify vault reads, credential "
        "generation, file search, and other capabilities that are "
        "not in this narrow registry. NEVER pick fallthrough when "
        "the user is confirming or rejecting a pending destructive "
        "action."
    ),
    args_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    destructive=False,
    requires_pending=None,
    category="fallthrough",
))


def all_tools() -> list[ToolSpec]:
    return list(_TOOLS.values())


def get_tool(name: str) -> Optional[ToolSpec]:
    if not isinstance(name, str):
        return None
    return _TOOLS.get(name)


def tool_names() -> list[str]:
    return list(_TOOLS.keys())


def is_destructive_tool(name: str) -> bool:
    spec = get_tool(name)
    return bool(spec and spec.destructive)


def tools_for_prompt() -> list[dict]:
    """Compact list of tools suitable for embedding in a model
    prompt. Does not include the raw JSON schemas — the decider
    prompt renders these into human-readable lines and the
    router validates args against the schemas after the fact.
    """
    return [
        {
            "name":             s.name,
            "description":      s.description,
            "destructive":      s.destructive,
            "requires_pending": s.requires_pending,
            "category":         s.category,
        }
        for s in _TOOLS.values()
    ]


__all__ = [
    "TOOL_CONFIRM_PENDING_DELETE",
    "TOOL_CANCEL_PENDING_DELETE",
    "TOOL_CONFIRM_PENDING_SAVE",
    "TOOL_CANCEL_PENDING_SAVE",
    "TOOL_REQUEST_CLARIFICATION",
    "TOOL_CONVERSATIONAL_REPLY",
    "TOOL_FALLTHROUGH",
    "ToolSpec",
    "all_tools",
    "get_tool",
    "tool_names",
    "is_destructive_tool",
    "tools_for_prompt",
]
