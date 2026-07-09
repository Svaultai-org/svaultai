

from __future__ import annotations

import json
import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)


TYPE_DEVICE_VAULT_RESULTS:  str = "device_vault_results"
TYPE_DEVICE_VAULT_REMINDER: str = "device_vault_reminder"


SCHEMA_VERSION: str = "device_vault.v1"
COPY_VERSION:   str = "device_vault_2026_06_29"


REMINDER_TITLE: str = "Quick reminder 📱"

REMINDER_MESSAGE: str = (
    "Remember to save important details about your phone, laptop, "
    "or other devices — like IMEI, serial number, model, receipt, "
    "or recovery notes — so you can find them quickly if a device "
    "is lost or stolen."
)


ACTION_SAVE_DEVICE_INFO: str = "save_device_info"
ACTION_REMIND_LATER:     str = "remind_later"
ACTION_DISMISS_FOREVER:  str = "dont_show_again"

                                                                
ACTION_ADD_PHONE:  str = ACTION_SAVE_DEVICE_INFO
ACTION_ADD_LAPTOP: str = ACTION_SAVE_DEVICE_INFO

ALL_REMINDER_ACTIONS: tuple[str, ...] = (
    ACTION_SAVE_DEVICE_INFO,
    ACTION_REMIND_LATER,
    ACTION_DISMISS_FOREVER,
)


def build_device_results_envelope(
    *,
    devices: list[dict],
    message: Optional[str] = None,
) -> str:


    safe_devices: list[dict] = []
    for d in devices or []:
        if not isinstance(d, dict):
            continue
        safe_devices.append(_filter_safe_preview(d))

    payload = {
        "type":            TYPE_DEVICE_VAULT_RESULTS,
        "schema_version":  SCHEMA_VERSION,
        "copy_version":    COPY_VERSION,
        "count":           len(safe_devices),
        "devices":         safe_devices,
        "message":         message or _default_message(len(safe_devices)),
                                                                   
                                                                  
        "available_actions": (
            "open", "edit", "attach_receipt", "delete",
        ),
    }
    logger.info(
        "[DEVICE-VAULT-ENV] results count=%d schema=%s",
        len(safe_devices), SCHEMA_VERSION,
    )
    return json.dumps(payload, ensure_ascii=False)


def build_reminder_envelope() -> str:


    payload = {
        "type":            TYPE_DEVICE_VAULT_REMINDER,
        "schema_version":  SCHEMA_VERSION,
        "copy_version":    COPY_VERSION,
        "title":           REMINDER_TITLE,
        "message":         REMINDER_MESSAGE,
        "buttons": [
            {"id": ACTION_SAVE_DEVICE_INFO, "label": "Save device info"},
            {"id": ACTION_REMIND_LATER,     "label": "Remind me later"},
            {"id": ACTION_DISMISS_FOREVER,  "label": "Don't show again"},
        ],
    }
    logger.info(
        "[DEVICE-VAULT-ENV] reminder schema=%s",
        SCHEMA_VERSION,
    )
    return json.dumps(payload, ensure_ascii=False)


_ALLOWED_PREVIEW_KEYS: frozenset[str] = frozenset({
                      
    "device_id", "device_kind",
                                    
    "device_name", "brand", "model",
    "purchase_date",
    "operating_system",
    "sim_provider",
    "color",
    "find_my_status",
                              
    "imei_1_mask", "imei_2_mask",
    "serial_mask", "phone_mask",
    "mac_mask",
                                                              
    "has_receipt", "has_notes",
    "has_lock_screen_note",
    "has_emergency_contact",
    "has_recovery_reference",
})


def _filter_safe_preview(d: dict) -> dict:


    if not isinstance(d, dict):
        return {}
    out: dict[str, Any] = {}
    inner_preview = d.get("preview") if isinstance(d, dict) else None
    if isinstance(inner_preview, dict):
                                                                        
                                                  
        for k, v in inner_preview.items():
            if k in _ALLOWED_PREVIEW_KEYS:
                out[k] = v
    for k, v in d.items():
        if k == "preview":
            continue
        if k in _ALLOWED_PREVIEW_KEYS:
            out[k] = v
    return out


def _default_message(count: int) -> str:
    if count == 0:
        return "You haven't added any devices yet."
    if count == 1:
        return "Here's the device you saved."
    return f"Here are the {count} devices you've saved."


__all__ = [
    "TYPE_DEVICE_VAULT_RESULTS",
    "TYPE_DEVICE_VAULT_REMINDER",
    "SCHEMA_VERSION",
    "COPY_VERSION",
    "REMINDER_TITLE",
    "REMINDER_MESSAGE",
    "ACTION_SAVE_DEVICE_INFO",
    "ACTION_ADD_PHONE",
    "ACTION_ADD_LAPTOP",
    "ACTION_REMIND_LATER",
    "ACTION_DISMISS_FOREVER",
    "ALL_REMINDER_ACTIONS",
    "build_device_results_envelope",
    "build_reminder_envelope",
]
