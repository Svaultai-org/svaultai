

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional


logger = logging.getLogger(__name__)


DEFAULT_REMIND_LATER_S: int = int(
    os.getenv("VAULTAI_DEVICE_REMIND_LATER_S", str(7 * 24 * 3600)),
)

                                                                
DEFAULT_REMINDER_COOLDOWN_S: int = int(
    os.getenv("VAULTAI_DEVICE_REMINDER_COOLDOWN_S", str(24 * 3600)),
)


DECISION_SHOW:                str = "show"
DECISION_HIDDEN_HAS_DEVICE:   str = "hidden_has_device"
DECISION_HIDDEN_DISMISSED:    str = "hidden_dismissed_forever"
DECISION_HIDDEN_REMIND_LATER: str = "hidden_remind_later"
DECISION_HIDDEN_COOLDOWN:     str = "hidden_recent_show_cooldown"

ALL_DECISIONS: tuple[str, ...] = (
    DECISION_SHOW,
    DECISION_HIDDEN_HAS_DEVICE,
    DECISION_HIDDEN_DISMISSED,
    DECISION_HIDDEN_REMIND_LATER,
    DECISION_HIDDEN_COOLDOWN,
)


_lock = threading.Lock()
                        
          
_store: dict[str, dict] = {}


def _now() -> float:
    return time.time()


def _state_for(vault_id: str) -> dict:
    return _store.setdefault(vault_id, {
        "dismissed_forever":  False,
        "remind_later_until": 0.0,
        "last_shown_at":      0.0,
    })


def reminder_decision(
    *,
    vault_id: str,
    devices_count: int,
) -> str:


    if not vault_id or not isinstance(vault_id, str):
                                
        return DECISION_HIDDEN_HAS_DEVICE
    if isinstance(devices_count, int) and devices_count > 0:
        return DECISION_HIDDEN_HAS_DEVICE

    now = _now()
    with _lock:
        st = _state_for(vault_id)
        if st.get("dismissed_forever"):
            return DECISION_HIDDEN_DISMISSED
        if float(st.get("remind_later_until") or 0.0) > now:
            return DECISION_HIDDEN_REMIND_LATER
        last_shown = float(st.get("last_shown_at") or 0.0)
        if last_shown > 0 and (now - last_shown) < DEFAULT_REMINDER_COOLDOWN_S:
            return DECISION_HIDDEN_COOLDOWN
    return DECISION_SHOW


def should_show_reminder(
    *,
    vault_id: str,
    devices_count: int,
) -> bool:


    decision = reminder_decision(
        vault_id=vault_id, devices_count=devices_count,
    )
    show = decision == DECISION_SHOW
    logger.info(
        "[DEVICE-REMINDER] decision vault=%s devices_count=%d "
        "band=%s",
        (vault_id or "")[:8] + "…",
        int(devices_count or 0),
        decision,
    )
    return show


def mark_shown(vault_id: str) -> None:


    if not vault_id:
        return
    now = _now()
    with _lock:
        st = _state_for(vault_id)
        st["last_shown_at"] = now
    logger.info(
        "[DEVICE-REMINDER] mark_shown vault=%s",
        (vault_id or "")[:8] + "…",
    )


def mark_remind_later(
    vault_id: str,
    *,
    snooze_seconds: Optional[int] = None,
) -> None:

    if not vault_id:
        return
    snooze = int(
        snooze_seconds if snooze_seconds is not None
        else DEFAULT_REMIND_LATER_S
    )
    if snooze <= 0:
        snooze = DEFAULT_REMIND_LATER_S
    until = _now() + snooze
    with _lock:
        st = _state_for(vault_id)
        st["remind_later_until"] = until
    logger.info(
        "[DEVICE-REMINDER] remind_later vault=%s snooze_s=%d",
        (vault_id or "")[:8] + "…", snooze,
    )


def mark_dismissed_forever(vault_id: str) -> None:


    if not vault_id:
        return
    with _lock:
        st = _state_for(vault_id)
        st["dismissed_forever"] = True
    logger.info(
        "[DEVICE-REMINDER] dismissed_forever vault=%s",
        (vault_id or "")[:8] + "…",
    )


def reset_reminder_state(vault_id: str) -> bool:


    if not vault_id:
        return False
    with _lock:
        return _store.pop(vault_id, None) is not None


def _snapshot_for_test() -> dict[str, dict]:
    with _lock:
        return {k: dict(v) for k, v in _store.items()}


def _reset_store_for_test() -> None:
    with _lock:
        _store.clear()


__all__ = [
    "DECISION_SHOW",
    "DECISION_HIDDEN_HAS_DEVICE",
    "DECISION_HIDDEN_DISMISSED",
    "DECISION_HIDDEN_REMIND_LATER",
    "DECISION_HIDDEN_COOLDOWN",
    "ALL_DECISIONS",
    "DEFAULT_REMIND_LATER_S",
    "DEFAULT_REMINDER_COOLDOWN_S",
    "reminder_decision",
    "should_show_reminder",
    "mark_shown",
    "mark_remind_later",
    "mark_dismissed_forever",
    "reset_reminder_state",
]
