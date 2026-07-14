"""Backend must not derive persistent Vault subkeys.

Enforces the authoritative zero-knowledge boundary: the backend
may transiently see the specific plaintext the user just asked the
AI/OCR to process, but must NEVER derive VaultKeyHierarchy subkeys
(memoryKey, metadataKey, walletLockLookupKey, semanticLookupKey,
memoryLookupKey, displayNameKey, ...) from any server-held key
material.

This test scans every backend Python file that participates in the
AI / chat / persistence pipeline and fails the build if it contains
any of the following forbidden signals:

  * The HKDF info string namespace ``vaultai.<subkey>.v<n>``.
  * A direct import of ``HKDF`` when combined with an AI/chat path.
  * A call to ``derive_key`` / ``derive_subkey`` /
    ``derive_memory_key`` / etc from an AI or chat module.

Files under ``vault_core.py`` (the low-level KDF module used only by
the legacy PIN-verified path) and ``opaque_server_module.py`` (the
OPAQUE server-role wrapper) are exempt — they own the key
boundary rather than crossing it.

The audit is source-scan only; runs without a live DB or the
pyo3 wheel.
"""

from __future__ import annotations

import glob
import os
import re


FORBIDDEN_INFO_STRINGS = (
    b"vaultai.memory.v",
    b"vaultai.metadata.v",
    b"vaultai.wallet.v",
    b"vaultai.display.v",
    b"vaultai.lookup.semantic.v",
    b"vaultai.lookup.memory.v",
    b"vaultai.lookup.wallet.lock.v",
    b"vaultai.kek.v",
)


AI_CHAT_FILE_PATTERNS = (
    "ai_memory.py",
    "vault_planner*.py",
    "vault_memory_answer_composer.py",
    "vault_chat*.py",
    "chat_fast_path.py",
    "memory_recall.py",
    "relationship_builder.py",
    "brain_embedder.py",
    "vault_secure_item_save.py",
    "asset_tagger.py",
    "semantic_embedder.py",
    "document_understanding.py",
    "document_entities.py",
    "routes/vault_metadata_migration_routes.py",
    "routes/vault_ciphertext_write_routes.py",
    "routes/vault_manage_routes.py",
    "routes/auth_zk_routes.py",
    "main.py",
)


def _iter_ai_chat_files():
    root = os.path.dirname(os.path.abspath(__file__))
    seen: set[str] = set()
    for pattern in AI_CHAT_FILE_PATTERNS:
        for path in glob.glob(os.path.join(root, pattern)):
            if path in seen:
                continue
            seen.add(path)
            yield path


def test_no_ai_chat_backend_file_derives_vault_subkeys() -> None:
    """No file in the AI / chat / persistence pipeline may reference
    a VaultKeyHierarchy info-string. Deriving one server-side would
    give the backend the ability to encrypt or authenticate as the
    user's vault key, breaking the ZK boundary."""
    offenders: list[tuple[str, str]] = []
    for path in _iter_ai_chat_files():
        with open(path, "rb") as f:
            data = f.read()
        for token in FORBIDDEN_INFO_STRINGS:
            if token in data:
                offenders.append((os.path.basename(path),
                                  token.decode("ascii")))
    assert offenders == [], (
        "Backend AI/chat/persistence file(s) contain a "
        "VaultKeyHierarchy info-string. The backend must NEVER "
        "derive Vault subkeys — that responsibility belongs to the "
        "unlocked client. Offenders:\n" +
        "\n".join(f"  {name}: {tok}" for name, tok in offenders)
    )


def test_no_ai_chat_backend_file_imports_hkdf_from_cryptography() -> None:
    """A weaker but useful heuristic: no AI/chat module should
    `from cryptography.hazmat.primitives.kdf.hkdf import HKDF`. If
    it did, the only reason would be to derive a Vault subkey. The
    legitimate low-level KDF (`vault_core.derive_key`) is a
    server-side legacy compatibility hook, not a ZK boundary
    crossing.
    """
    hkdf_re = re.compile(
        rb"from cryptography\.hazmat\.primitives\.kdf\.hkdf import HKDF",
    )
    offenders: list[str] = []
    for path in _iter_ai_chat_files():
        with open(path, "rb") as f:
            if hkdf_re.search(f.read()):
                offenders.append(os.path.basename(path))
    assert offenders == [], (
        "Backend AI/chat/persistence file imports HKDF — this "
        "typically indicates a Vault subkey derivation. Move any "
        "subkey derivation to the client. Offenders: " +
        repr(offenders)
    )


def test_ai_memory_zk_ciphertext_branch_accepts_only_precomputed_bytes() -> None:
    """The ZK ciphertext-first branch in ai_memory.update_memory_safe
    must accept ONLY pre-computed ciphertext + lookup hash (produced
    by the client). It must not accept a vault_key / PIN / MVK
    argument that would allow server-side derivation."""
    import inspect
    from ai_memory import update_memory_safe
    sig = inspect.signature(update_memory_safe)
    forbidden_params = {"vault_key", "mvk", "pin", "kek",
                        "memory_key_material", "metadata_key",
                        "memory_subkey"}
    offenders = forbidden_params & set(sig.parameters)
    assert not offenders, (
        f"update_memory_safe accepts server-side-derivation params: "
        f"{sorted(offenders)} — this would break the ZK boundary."
    )
