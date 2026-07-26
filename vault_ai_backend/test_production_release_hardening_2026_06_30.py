

from __future__ import annotations

import re
import unittest
from pathlib import Path


_BACKEND_ROOT = Path(__file__).parent


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


_ROUTE_FILES: dict[str, str] = {}
for path in (_BACKEND_ROOT / "routes").glob("*.py"):
    _ROUTE_FILES[path.name] = _read(path)
_ROUTE_FILES["main.py"] = _read(_BACKEND_ROOT / "main.py")


PIN_TAKING_ROUTE_ANCHORS = (
                                      
    ('@router.post("/list-login-names")',  "login_routes.py"),
    ('@router.post("/get-login")',          "login_routes.py"),
    ('@router.post("/delete-login")',       "login_routes.py"),
    ('@router.post("/login-count")',        "login_routes.py"),
                                 
    ('@router.post("/update-secure-item")', "login_routes.py"),
    ('@router.post("/get-secure-item")',    "login_routes.py"),
    ('@router.post("/delete-secure-item")', "login_routes.py"),
    ('@router.post("/list-secure-items")',  "login_routes.py"),
                           
    ('@router.post("/crypto/save-wallet-profile")',
        "login_routes.py"),
    ('@router.post("/crypto/save-sensitive-backup")',
        "login_routes.py"),
    ('@router.post("/crypto/reveal-sensitive-backup")',
        "login_routes.py"),
    ('@router.post("/crypto/save-note")',
        "login_routes.py"),
)


def _slice_handler(file_key: str, anchor: str) -> str:
    src = _ROUTE_FILES[file_key]
    start = src.index(anchor)
                                             
    nxt = src.find("@router.", start + 1)
    end = nxt if nxt != -1 else len(src)
    return src[start:end]


class TestPinRoutesUseUnifiedAuthPattern(unittest.TestCase):
    def test_every_pin_route_uses_trusted_device_dep(self) -> None:
        for anchor, file_key in PIN_TAKING_ROUTE_ANCHORS:
            body = _slice_handler(file_key, anchor)
            self.assertIn(
                "verify_trusted_device", body,
                msg=(
                    f"PIN-taking route {anchor!r} in {file_key} "
                    "must gate on verify_trusted_device."
                ),
            )

    def test_every_pin_route_calls_verify_vault_pin(self) -> None:
        for anchor, file_key in PIN_TAKING_ROUTE_ANCHORS:
            body = _slice_handler(file_key, anchor)
            self.assertIn(
                "verify_vault_pin(", body,
                msg=(
                    f"PIN-taking route {anchor!r} in {file_key} "
                    "must call verify_vault_pin(vault_id, pin)."
                ),
            )


LOGGER_PREFIXES = (
    "logger.info(",  "logger.debug(",
    "logger.warning(", "logger.error(",
    "logger.exception(",
    "_logger.info(", "_logger.debug(",
    "_logger.warning(", "_logger.error(",
    "_logger.exception(",
    "log.info(",  "log.debug(",
    "log.warning(", "log.error(",
    "log.exception(",
    "print(",
)


FORBIDDEN_PAYLOAD_PATTERNS = (
                                                                 
    re.compile(r"logger\.(?:info|debug|warning|error|exception)\([^)]*\bpayload\s*\)"),
    re.compile(r"_logger\.(?:info|debug|warning|error|exception)\([^)]*\bpayload\s*\)"),
    re.compile(r"log\.(?:info|debug|warning|error|exception)\([^)]*\bpayload\s*\)"),
    re.compile(r"print\(\s*payload\s*\)"),
)


def _strip_comments_and_strings(src: str) -> str:
                                                               
                                                             
    src = re.sub(r'"""[\s\S]*?"""', '""""""', src)
    src = re.sub(r"'''[\s\S]*?'''", "''''''", src)
                              
    lines = []
    for line in src.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
                                                              
        if " #" in line:
            line = line.split(" #", 1)[0]
        lines.append(line)
    return "\n".join(lines)


class TestNoWholePayloadLogging(unittest.TestCase):
    def test_no_route_file_logs_payload_object(self) -> None:
        for fname, src in _ROUTE_FILES.items():
            cleaned = _strip_comments_and_strings(src)
            for rx in FORBIDDEN_PAYLOAD_PATTERNS:
                match = rx.search(cleaned)
                self.assertIsNone(
                    match,
                    msg=(
                        f"{fname} logs the raw payload object — "
                        f"this is the PIN/secret/address leak "
                        f"pattern: matched {match.group(0)!r} "
                        if match else ""
                    ),
                )


APPROVED_CRYPTO_MODULES = frozenset({
                                            
    "vault_secure_item_save.py",
    "vault_secure_item_draft.py",
    "vault_core.py",
    "durable_personal_memory.py",
    "main.py",
    "chunked_aead.py",
                                                            
                                                                
    "vault_analysis_worker.py",
    "vault_archive_worker.py",
    "vault_audio_worker.py",
    "vault_brain_indexer.py",
    "vault_brain_retrieval.py",
    "vault_brain_worker.py",
    "vault_chunk_store.py",
    "vault_device_vault.py",
    "vault_embedding_worker.py",
    "vault_inspection_tools.py",
    "vault_ocr_worker.py",
    "vault_understanding_search.py",
    "vault_understanding_worker.py",
    "vault_video_worker.py",
    "vault_intelligence_cache.py",


    "vault_chat_card_data.py",

    "routes/login_routes.py",
    "routes/vault_manage_routes.py",
    "routes/auth_routes.py",
    "routes/file_text_routes.py",
    "routes/chunked_upload_routes.py",
    "routes/security_center_routes.py",

    "routes/vault_delete_routes.py",
})


def _list_python_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*.py"):
        if "test_" in p.name or "tests/" in str(p):
            continue
        if "/.venv/" in str(p).replace("\\", "/"):
            continue
        out.append(p)
    return out


class TestCryptoCallsitesAllowListed(unittest.TestCase):
    def test_encrypt_decrypt_callsites_stay_in_approved_modules(
        self,
    ) -> None:
        rx = re.compile(r"\b(?:encrypt|decrypt)_message\s*\(")
        unauthorized: list[str] = []
        for p in _list_python_files(_BACKEND_ROOT):
            if "/migrations/" in str(p).replace("\\", "/"):
                continue
            text = p.read_text(encoding="utf-8")
            cleaned = _strip_comments_and_strings(text)
            if not rx.search(cleaned):
                continue
            rel = str(p.relative_to(_BACKEND_ROOT)).replace("\\", "/")
            if rel in APPROVED_CRYPTO_MODULES:
                continue
            unauthorized.append(rel)
        self.assertEqual(
            unauthorized, [],
            msg=(
                "Unauthorized encrypt/decrypt callsites detected. "
                "These modules call encrypt_message / "
                "decrypt_message directly without being on the "
                "approved owner list (extend "
                "APPROVED_CRYPTO_MODULES intentionally if a new "
                "approved owner is added): "
                f"{unauthorized!r}"
            ),
        )


QUOTA_BUMP_CALLSITES = (
                           
    ("main.py",                          "bump_vault_total_bytes("),
                                                       
    ("vault_secure_item_save.py",        "bump_vault_total_bytes"),
                             
    ("routes/login_routes.py",           "bump_vault_total_bytes("),
    ("routes/vault_manage_routes.py",    "bump_vault_total_bytes"),
)


class TestStorageQuotaTouchpoints(unittest.TestCase):
    def test_every_known_quota_callsite_remains_wired(self) -> None:
        for rel, needle in QUOTA_BUMP_CALLSITES:
            src = (_BACKEND_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn(
                needle, src,
                msg=(
                    f"{rel} no longer calls {needle!r} — a "
                    "storage-mutating path may have lost its "
                    "quota bump."
                ),
            )


class TestBillingRoutesMounted(unittest.TestCase):
    def setUp(self) -> None:
        import main
        self.paths = {r.path for r in main.app.routes}

    def test_stripe_webhook_route_registered(self) -> None:
        self.assertIn(
            "/billing/stripe/webhook", self.paths,
            msg=(
                "Stripe webhook must be at /billing/stripe/webhook"
                " — Stripe is configured to POST that exact path."
            ),
        )

    def test_billing_me_route_registered(self) -> None:
        self.assertIn(
            "/billing/me", self.paths,
            msg=(
                "/billing/me must be mounted at root prefix — "
                "the frontend's billing-state poll posts to it."
            ),
        )


class TestNoLeftoverDebugPrint(unittest.TestCase):
    def test_no_print_emits_sensitive_payload_value(self) -> None:
                                                           
                                                            
        sensitive_field_rx = re.compile(
            r"payload\.(?:pin|secretValue|publicAddress|note|"
            r"txHash|title|walletLabel)\b(?!\s*[,)\]]\s*[,)\]])",
        )
                                                               
                                                              
        for fname, src in _ROUTE_FILES.items():
            cleaned = _strip_comments_and_strings(src)
                                                                
                                                          
            for m in re.finditer(
                r"^\s*print\([\s\S]*?\)\s*$",
                cleaned, re.MULTILINE,
            ):
                block = m.group(0)
                hits = [
                    h.group(0)
                    for h in sensitive_field_rx.finditer(block)
                                                               
                                                           
                    if "len(" not in block[
                        max(0, h.start() - 8): h.start()
                    ]
                ]
                self.assertEqual(
                    hits, [],
                    msg=(
                        f"{fname}: print() emits sensitive raw "
                        f"payload value(s) {hits!r}: {block!r}"
                    ),
                )


class TestNoLoggerArgEchoesPayload(unittest.TestCase):


    def test_no_fstring_payload_in_logger_call(self) -> None:
        rx_fstring = re.compile(
            r"(logger|_logger|log)\.(?:info|debug|warning|error|exception)"
            r"\([^)]*f[\"'][^\"']*\{\s*payload\b",
        )
        for fname, src in _ROUTE_FILES.items():
            cleaned = _strip_comments_and_strings(src)
            match = rx_fstring.search(cleaned)
            self.assertIsNone(
                match,
                msg=(
                    f"{fname} embeds payload in an f-string log "
                    "argument — leaks PIN/secret via repr: "
                    f"{match.group(0)!r}"
                    if match else ""
                ),
            )


if __name__ == "__main__":
    unittest.main()
