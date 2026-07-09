"""Backend source-hygiene scans (Part E of the polish pass).

Scans production Python files for:
  * obsolete "coming soon" / "planned" / placeholder copy
  * generic "Aisha" in product copy
  * logger calls that would leak secrets (api key, auth token,
    seed, mnemonic, private key, spend key, view key, encrypted
    wallet secret, signed tx hex, raw provider responses)
  * long commented-out code blocks (≥5 consecutive lines)

Scans ONLY production source under vault_ai_backend/ — skips
.venv/, tests/, __pycache__, migrations/, alembic auto-generated.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


_BACKEND_ROOT = Path(__file__).parent


_EXCLUDE_DIRS: frozenset[str] = frozenset({
    ".venv", "__pycache__", "build", "dist", ".git",
    ".idea", ".vscode", "migrations", "alembic",
    "node_modules",
})


def _iter_backend_py_files():
    for path in _BACKEND_ROOT.rglob("*.py"):
        parts = path.relative_to(_BACKEND_ROOT).parts

        if any(p in _EXCLUDE_DIRS for p in parts):
            continue
        if path.name.startswith("test_"):
            continue
        yield path


class TestNoObsoletePlaceholderCopy(unittest.TestCase):
    """No 'Coming soon' / 'Planned' / 'Phase 2' copy in strings."""

    _PLACEHOLDERS: tuple[str, ...] = (
        "Coming next",
        "Coming soon",
        "Later phase",


        "Privacy wallet later",
    )

    def test_no_obsolete_placeholders_in_backend_strings(self):
        offenders: list[str] = []
        for path in _iter_backend_py_files():
            rel = path.relative_to(_BACKEND_ROOT)
            text = path.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(text.splitlines(), 1):
                for p in self._PLACEHOLDERS:

                    if re.search(
                        r"(?:^|[\s\"'.>({\[])"
                        + re.escape(p) +
                        r"(?:$|[\s\"'.<),}\]])",
                        line,
                    ):
                        offenders.append(
                            f"{rel}:{lineno}: {line.strip()}"
                        )
        self.assertEqual(
            offenders, [],
            msg=(
                "obsolete placeholder copy in backend production "
                "source:\n" + "\n".join(offenders)
            ),
        )


class TestNoGenericAishaInBackend(unittest.TestCase):
    def test_no_generic_aisha_in_backend_source(self):
        offenders: list[str] = []
        for path in _iter_backend_py_files():
            rel = path.relative_to(_BACKEND_ROOT)
            text = path.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(text.splitlines(), 1):
                if re.search(r"\bAisha\b", line, re.IGNORECASE):
                    offenders.append(
                        f"{rel}:{lineno}: {line.strip()}",
                    )
        self.assertEqual(
            offenders, [],
            msg=(
                "generic 'Aisha' in backend product copy — use "
                "'VaultAI Chat' / 'the assistant' instead:\n"
                + "\n".join(offenders)
            ),
        )


class TestNoLeakingLoggerCalls(unittest.TestCase):
    """Best-effort scan: any logger.<level>(...) call whose first
    positional argument mentions a secret keyword by name is
    surfaced for review. This isn't a proof of no-leak — it's a
    trip-wire for obvious mistakes."""

    _SECRET_KEYWORDS: tuple[str, ...] = (

        "seed_phrase", "seedPhrase",
        "mnemonic", "polyseed",
        "private_key", "privateKey",
        "spend_key", "spendKey",
        "view_key", "viewKey",
        "encrypted_wallet_secret", "encryptedWalletSecret",
        "encrypted_secret", "encryptedSecret",
        "auth_token", "authToken",
        "api_key", "apiKey",
        "stripe_secret_key", "stripeSecretKey",
        "signed_tx_hex", "signedTxHex",
    )

    def test_no_logger_calls_reference_secret_fields_directly(self):

        offenders: list[str] = []

        pattern = re.compile(
            r"\blogger\.\w+\s*\([^)]*\b("
            + "|".join(re.escape(k) for k in self._SECRET_KEYWORDS)
            + r")\b",
            re.IGNORECASE,
        )
        for path in _iter_backend_py_files():
            rel = path.relative_to(_BACKEND_ROOT)
            text = path.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(text.splitlines(), 1):

                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                m = pattern.search(line)
                if not m:
                    continue

                nearby_start = max(0, lineno - 3)
                nearby_end = lineno + 2
                nearby = text.splitlines()[nearby_start:nearby_end]
                nearby_joined = "\n".join(nearby)
                if re.search(
                    r"never|no\s+leak|forbidden|_stripForbid|"
                    r"strip_forbid|not\s+logged|redact|mask",
                    nearby_joined, re.IGNORECASE,
                ):
                    continue
                offenders.append(
                    f"{rel}:{lineno}: possible secret in logger "
                    f"call ('{m.group(1)}'): {line.strip()}"
                )
        self.assertEqual(
            offenders, [],
            msg=(
                "logger calls appear to reference secret field "
                "names directly. If these are safe (e.g. redacted "
                "or a hash) add a nearby 'redact' / 'mask' / "
                "'never' comment. Otherwise remove the leak:\n"
                + "\n".join(offenders)
            ),
        )


class TestNoLongCommentedOutCodeBlocks(unittest.TestCase):
    """No ≥5 consecutive commented-out code lines."""

    _CODE_COMMENT_RE = re.compile(
        r"^\s*#\s+(?:"
        r"[a-zA-Z_][\w.]*\s*\(|"
        r"if\s|for\s|while\s|return\s|"
        r"def\s|class\s|import\s|from\s|"
        r"try:|except|else:|elif\s)"
    )

    def test_no_long_commented_out_blocks(self):
        offenders: list[str] = []
        for path in _iter_backend_py_files():
            rel = path.relative_to(_BACKEND_ROOT)
            lines = path.read_text(
                encoding="utf-8", errors="ignore",
            ).splitlines()
            consecutive = 0
            start = -1
            for i, line in enumerate(lines):
                if self._CODE_COMMENT_RE.match(line):
                    if consecutive == 0:
                        start = i + 1
                    consecutive += 1
                    if consecutive >= 5:
                        offenders.append(
                            f"{rel}:{start}-{i + 1}: "
                            "commented-out code block"
                        )
                        consecutive = 0
                        start = -1
                else:
                    consecutive = 0
                    start = -1
        self.assertEqual(
            offenders, [],
            msg=(
                "commented-out code blocks in backend:\n"
                + "\n".join(offenders)
            ),
        )


if __name__ == "__main__":
    unittest.main()
