

import os
import time
from collections import OrderedDict
from typing import Any, Optional


CHAT_MEMORY_TTL_SECONDS = int(os.getenv("CHAT_MEMORY_TTL_SECONDS", str(60 * 60)))
CHAT_MEMORY_MAX_ENTRIES = int(os.getenv("CHAT_MEMORY_MAX_ENTRIES", "10000"))


class TTLDict:


    __slots__ = ("_data", "max_size", "ttl_seconds")

    def __init__(self, max_size: int, ttl_seconds: int):
        self._data: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds

    def _evict_expired(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        while self._data:
            key = next(iter(self._data))
            ts, _ = self._data[key]
            if ts < cutoff:
                self._data.popitem(last=False)
            else:
                break

    def get(self, key: str) -> Optional[Any]:
        if key not in self._data:
            return None
        ts, value = self._data[key]
        if time.time() - ts > self.ttl_seconds:
            del self._data[key]
            return None
                                                                          
        self._data[key] = (time.time(), value)
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        self._evict_expired()
        self._data[key] = (time.time(), value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_size:
            self._data.popitem(last=False)

    def pop(self, key: str, default: Any = None) -> Any:
        if key in self._data:
            _, value = self._data.pop(key)
            return value
        return default

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def __len__(self) -> int:
        return len(self._data)


CHAT_MEMORY = TTLDict(
    max_size=CHAT_MEMORY_MAX_ENTRIES,
    ttl_seconds=CHAT_MEMORY_TTL_SECONDS,
)


def memory_key(vault_id: str) -> str:
    return str(vault_id)


def get_memory(vault_id: str) -> dict:
    key = memory_key(vault_id)
    existing = CHAT_MEMORY.get(key)
    if existing is None:
        existing = {
            "last_service": None,
            "pending_action": None,
            "pending_field": None,
        }
        CHAT_MEMORY.set(key, existing)
    return existing


def remember_service(vault_id: str, service: Optional[str]):
    if service and service != "general":
        get_memory(vault_id)["last_service"] = service


def set_pending_edit(vault_id: str, service: str, field: Optional[str] = None):
    memory = get_memory(vault_id)
    memory["pending_action"] = "edit_login"
    memory["pending_field"] = field
    memory["last_service"] = service


def clear_pending(vault_id: str):
    memory = get_memory(vault_id)
    memory["pending_action"] = None
    memory["pending_field"] = None


LAST_FILE_SEARCH_MAX_ITEMS = 25


def set_last_file_search_results(
    vault_id: str,
    *,
    kind: str,
    results: list,
) -> None:


    memory = get_memory(vault_id)
    snapshot = []
    for raw in results[:LAST_FILE_SEARCH_MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
                                                            
                                                            
        raw_reasons = raw.get("reasons")
        if isinstance(raw_reasons, list):
            safe_reasons = [
                str(r) for r in raw_reasons
                if isinstance(r, str) and r.strip()
            ]
        else:
            safe_reasons = []
                                                 
                                                                    
        density_raw = raw.get("credential_density")
        density = (
            round(float(density_raw), 4)
            if isinstance(density_raw, (int, float)) else 0.0
        )
        block_count_raw = raw.get("credential_block_count")
        block_count = (
            int(block_count_raw)
            if isinstance(block_count_raw, int) else 0
        )
        service_count_raw = raw.get("service_count")
        service_count = (
            int(service_count_raw)
            if isinstance(service_count_raw, int) else 0
        )
                                                               
                                                                 
        purpose_raw = raw.get("purpose")
        purpose = (
            str(purpose_raw)
            if isinstance(purpose_raw, str) and purpose_raw.strip()
            else ""
        )
        purpose_label_raw = raw.get("purpose_label")
        purpose_label = (
            str(purpose_label_raw).strip()
            if isinstance(purpose_label_raw, str) else ""
        )
        snapshot.append({
            "file_id":               str(raw.get("file_id") or raw.get("id") or ""),
            "file_name":             raw.get("file_name") or "",
            "saved_name":            raw.get("saved_name") or "",
            "relative_path":         raw.get("relative_path") or "",
            "mime_type":             raw.get("mime_type") or raw.get("content_type") or "",
            "asset_type":            raw.get("asset_type") or "file",
            "confidence":            (raw.get("confidence") or "").lower(),
            "reasons":               safe_reasons,
            "credential_density":    density,
            "credential_block_count": block_count,
            "service_count":         service_count,
            "mostly_credentials":    bool(raw.get("mostly_credentials") or False),
            "best_match":            bool(raw.get("best_match") or False),
            "purpose":               purpose,
            "purpose_label":         purpose_label,
        })
    memory["last_file_search"] = {
        "kind":    str(kind or ""),
        "results": snapshot,
    }


def get_last_file_search_results(vault_id: str) -> Optional[dict]:


    memory_key_v = memory_key(vault_id)
    raw = CHAT_MEMORY.get(memory_key_v)
    if not raw or not isinstance(raw, dict):
        return None
    snapshot = raw.get("last_file_search")
    if not snapshot or not isinstance(snapshot, dict):
        return None
    results = snapshot.get("results") or []
    if not results:
        return None
    return snapshot


def clear_last_file_search_results(vault_id: str) -> None:


    memory_key_v = memory_key(vault_id)
    raw = CHAT_MEMORY.get(memory_key_v)
    if isinstance(raw, dict) and "last_file_search" in raw:
        raw.pop("last_file_search", None)
