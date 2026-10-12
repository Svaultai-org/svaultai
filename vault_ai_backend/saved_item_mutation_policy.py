"""Staged saved-item client protocol; no production settings are changed here.

VAULTAI_SAVED_ITEM_MUTATION_INTENT_REQUIRED defaults false for rollout.
Keep it false while stores still serve older clients. Enable only after the
replacement iOS AND Android versions are publicly available. Explicitly
invalid create/edit combinations and duplicate/ambiguity guards are always
rejected independently of this compatibility flag.
"""
import os


def saved_item_mutation_intent_required() -> bool:
    return os.getenv("VAULTAI_SAVED_ITEM_MUTATION_INTENT_REQUIRED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }
