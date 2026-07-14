"""Regression guard against opaque-ke API drift.

The VaultAI OPAQUE wrapper (`vault_ai_backend/opaque_server_crate/`)
is a pyo3 shim over Meta's `opaque-ke` Rust crate. Between
opaque-ke 3.x and 4.x the CipherSuite trait dropped the standalone
`KeGroup` associated type, `TripleDh` became generic
(`TripleDh<G, H>`), and `ServerLoginStartParameters` was replaced
by a unified `ServerLoginParameters` type used for both start and
finish.

If any of those API assumptions drift again (e.g. an accidental
downgrade of the version constraint, or a paste of a 3.x pattern),
the Docker builder's inline OPAQUE smoke test would fail — but that
signal only surfaces on Linux/Docker after a full image build, and
the failure mode is expensive to iterate on.

This test detects the drift at the source layer, in seconds, on
every backend pytest run. It does NOT require a Rust toolchain.

Reference: https://docs.rs/opaque-ke/4.0.1/opaque_ke/
"""

from __future__ import annotations

import os
import re
import unittest

_CRATE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "opaque_server_crate",
)
_CARGO_TOML = os.path.join(_CRATE_DIR, "Cargo.toml")
_CARGO_LOCK = os.path.join(_CRATE_DIR, "Cargo.lock")
_LIB_RS = os.path.join(_CRATE_DIR, "src", "lib.rs")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _strip_rust_comments(src: str) -> str:
    """Return `src` with Rust line and block comments removed.

    Drift-detection tests scan CODE for uses of removed types; they
    must not trip on prose that MENTIONS a removed type in a
    compatibility note. This helper strips both `//`-line comments
    and `/* ... */` block comments (including `//!` and `///` doc
    variants) before scanning.
    """
    # /* ... */ block comments (non-greedy, single-line dot flag).
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.DOTALL)
    # //-line comments — everything from `//` to end-of-line. This
    # covers `//`, `///` (outer doc), and `//!` (inner doc).
    src = re.sub(r'//[^\n]*', '', src)
    return src


class TestCargoManifestPinsCorrectOpaqueKe(unittest.TestCase):
    """Cargo.toml must request an opaque-ke version that ships the
    4.x `TripleDh<G, H>` + unified `ServerLoginParameters` API.
    """

    def test_opaque_ke_minor_version_is_4x(self) -> None:
        src = _read(_CARGO_TOML)
        # Match either `opaque-ke = "4.x"` or the table form.
        m = re.search(
            r'opaque-ke\s*=\s*(?:\{[^}]*version\s*=\s*)?"([^"]+)"',
            src,
        )
        self.assertIsNotNone(
            m,
            msg="opaque-ke dependency must be declared in Cargo.toml",
        )
        req = m.group(1)
        self.assertTrue(
            req.startswith("4.") or req.startswith("=4.") or req == "^4",
            msg=(
                f"opaque-ke version constraint must be 4.x — got "
                f"{req!r}. Downgrading to 3.x reintroduces the "
                f"KeGroup / TripleDh-no-generics / "
                f"ServerLoginStartParameters shape that our wrapper "
                f"is written against 4.x for."
            ),
        )

    def test_opaque_ke_argon2_feature_enabled(self) -> None:
        src = _read(_CARGO_TOML)
        self.assertRegex(
            src,
            r'opaque-ke\s*=\s*\{[^}]*features\s*=\s*\[[^\]]*"argon2"',
            msg=(
                "opaque-ke must enable the argon2 feature — the "
                "wrapper's CipherSuite pins Ksf = argon2::Argon2. "
                "Without this feature the Ksf impl is not available."
            ),
        )

    def test_sha2_direct_dependency_declared(self) -> None:
        src = _read(_CARGO_TOML)
        # unittest.TestCase.assertRegex has no `flags` kwarg — build
        # a pre-compiled MULTILINE regex so `^sha2` anchors to a
        # line boundary, not the whole file's start.
        pattern = re.compile(r'^sha2\s*=\s*"0\.10', re.MULTILINE)
        self.assertRegex(
            src,
            pattern,
            msg=(
                "sha2 must be a direct dependency at 0.10.x — the "
                "wrapper's CipherSuite uses sha2::Sha512 as the "
                "hash type for TripleDh<Ristretto255, Sha512>. This "
                "hash must match the @serenity-kit/opaque WASM "
                "client (SHA-512) for wire interoperability."
            ),
        )


class TestCargoLockAgreesWithManifest(unittest.TestCase):
    """Cargo.lock must reflect the manifest so that Docker builds
    without network access (or with --locked) do not silently
    regenerate the lockfile.
    """

    def test_lockfile_lists_sha2_as_direct_dependency(self) -> None:
        src = _read(_CARGO_LOCK)
        m = re.search(
            r'\[\[package\]\]\s*\n'
            r'name\s*=\s*"vaultai_opaque_server"\s*\n'
            r'version\s*=\s*"[^"]+"\s*\n'
            r'dependencies\s*=\s*\[(.*?)\]',
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            msg="Cargo.lock must have a package entry for "
                "vaultai_opaque_server",
        )
        deps_block = m.group(1)
        self.assertIn(
            '"sha2"',
            deps_block,
            msg=(
                "Cargo.lock's vaultai_opaque_server dependencies "
                "must include sha2 — otherwise Docker builder "
                "regenerates the lockfile which breaks reproducible "
                "builds and hides drift."
            ),
        )

    def test_lockfile_pins_opaque_ke_4x(self) -> None:
        src = _read(_CARGO_LOCK)
        m = re.search(
            r'\[\[package\]\]\s*\n'
            r'name\s*=\s*"opaque-ke"\s*\n'
            r'version\s*=\s*"([^"]+)"',
            src,
        )
        self.assertIsNotNone(m, msg="opaque-ke must be resolved in Cargo.lock")
        pinned = m.group(1)
        self.assertTrue(
            pinned.startswith("4."),
            msg=(
                f"Cargo.lock must pin opaque-ke to a 4.x resolution "
                f"— got {pinned!r}. The wrapper depends on the "
                f"4.x CipherSuite / TripleDh / ServerLoginParameters "
                f"shape."
            ),
        )


class TestLibRsCipherSuiteContract(unittest.TestCase):
    """src/lib.rs must implement the opaque-ke 4.x CipherSuite
    contract exactly. This test locks in every previously-observed
    drift point so a regression trips before hitting Docker.
    """

    def setUp(self) -> None:
        # Strip comments so drift assertions see CODE only, not the
        # explanatory prose that discusses the removed 3.x types.
        self.src = _strip_rust_comments(_read(_LIB_RS))

    def test_no_ke_group_associated_type(self) -> None:
        # opaque-ke 4.x removed the standalone `KeGroup` associated
        # type from CipherSuite. A `type KeGroup = ...` line is a
        # 3.x pattern that will fail to compile against 4.x.
        self.assertNotRegex(
            self.src,
            r'^\s*type\s+KeGroup\s*=',
            msg=(
                "src/lib.rs must NOT declare `type KeGroup` — that "
                "associated type was removed from CipherSuite in "
                "opaque-ke 4.x. Group selection is folded into "
                "KeyExchange."
            ),
        )

    def test_key_exchange_uses_generic_tripledh(self) -> None:
        # opaque-ke 4.x: TripleDh<G, H> is generic. A bare `TripleDh`
        # (no generics) is a 3.x pattern that fails E0107 on 4.x.
        self.assertRegex(
            self.src,
            r'type\s+KeyExchange\s*=\s*[^;]*TripleDh\s*<\s*Ristretto255\s*,'
            r'\s*Sha512\s*>',
            msg=(
                "src/lib.rs must declare `type KeyExchange = "
                "...TripleDh<Ristretto255, Sha512>` — opaque-ke 4.x "
                "requires the two generic parameters (Group, Hash), "
                "and Ristretto255-SHA-512 is what the "
                "@serenity-kit/opaque WASM client uses on the wire."
            ),
        )

    def test_no_bare_tripledh_without_generics(self) -> None:
        # Belt-and-suspenders: forbid any bare `TripleDh` reference
        # not immediately followed by `<`.
        for match in re.finditer(r'\bTripleDh\b(.)', self.src):
            trailing = match.group(1)
            self.assertEqual(
                trailing,
                "<",
                msg=(
                    "src/lib.rs contains a bare `TripleDh` "
                    "reference not followed by `<`, which will fail "
                    "E0107 against opaque-ke 4.x."
                ),
            )

    def test_oprfcs_is_ristretto255(self) -> None:
        self.assertRegex(
            self.src,
            r'type\s+OprfCs\s*=\s*Ristretto255\s*;',
            msg=(
                "src/lib.rs must pin OprfCs = Ristretto255 — the "
                "OPAQUE OPRF group must match the "
                "@serenity-kit/opaque WASM client."
            ),
        )

    def test_ksf_is_argon2(self) -> None:
        self.assertRegex(
            self.src,
            r'type\s+Ksf\s*=\s*argon2::Argon2',
            msg=(
                "src/lib.rs must pin Ksf = argon2::Argon2 — this "
                "matches the OPAQUE Ristretto255-SHA-512-Argon2id "
                "ciphersuite the WASM client expects."
            ),
        )


class TestLibRsServerLoginParametersContract(unittest.TestCase):
    """The unified `ServerLoginParameters` type (opaque-ke 4.x)
    must be used at both start and finish; the removed
    `ServerLoginStartParameters` type must not appear anywhere.
    """

    def setUp(self) -> None:
        # Strip comments so drift assertions see CODE only, not the
        # explanatory prose that discusses the removed 3.x types.
        self.src = _strip_rust_comments(_read(_LIB_RS))

    def test_no_server_login_start_parameters(self) -> None:
        # `ServerLoginStartParameters` was removed in opaque-ke 4.x.
        # Any occurrence (import or call site) triggers E0432.
        # `ServerLoginStartResult` (with "Result") is unaffected —
        # only exclude the removed `Parameters` variant.
        offending = re.findall(
            r'\bServerLoginStartParameters\b', self.src,
        )
        self.assertEqual(
            offending,
            [],
            msg=(
                "src/lib.rs must not reference "
                "`ServerLoginStartParameters` — that type was "
                "removed in opaque-ke 4.x. Use "
                "`ServerLoginParameters` for both start and finish."
            ),
        )

    def test_server_login_parameters_is_imported(self) -> None:
        self.assertRegex(
            self.src,
            r'use\s+opaque_ke::\{[^}]*ServerLoginParameters',
            msg=(
                "src/lib.rs must import `ServerLoginParameters` — "
                "the unified 4.x type used at both ServerLogin::"
                "start and ServerLogin::finish call sites."
            ),
        )

    def test_login_start_call_site_uses_unified_parameters(self) -> None:
        # In `server_login_start`, the last argument to
        # `ServerLogin::start(...)` must be
        # `ServerLoginParameters::default()`. Allow arbitrary
        # whitespace/newlines between the closing `)` and
        # `.map_err(...)?` so the assertion works regardless of the
        # Rust source's line-break style.
        start_call = re.search(
            r'ServerLogin::start\s*\((.*?)\)\s*\.map_err',
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            start_call,
            msg="ServerLogin::start call site not found in lib.rs",
        )
        self.assertIn(
            "ServerLoginParameters::default()",
            start_call.group(1),
            msg=(
                "ServerLogin::start must be called with "
                "ServerLoginParameters::default() as its final "
                "argument (opaque-ke 4.x)."
            ),
        )

    def test_login_finish_call_site_uses_unified_parameters(self) -> None:
        finish_call = re.search(
            r'\.finish\s*\((.*?)\)\s*\.map_err',
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            finish_call,
            msg="ServerLogin.finish call site not found in lib.rs",
        )
        self.assertIn(
            "ServerLoginParameters::default()",
            finish_call.group(1),
            msg=(
                "ServerLogin::finish must be called with "
                "ServerLoginParameters::default() as its second "
                "argument (opaque-ke 4.x)."
            ),
        )


class TestFrontendWireInteropInvariants(unittest.TestCase):
    """The wire ciphersuite the Rust wrapper implements must remain
    identical to what the @serenity-kit/opaque WASM client speaks.
    If either side drifts, VaultAI users lose ZK login.
    """

    def test_lib_rs_documents_ristretto255_sha512_argon2id(self) -> None:
        src = _read(_LIB_RS)
        # The module docstring must document the exact suite so a
        # human review catches a suite mismatch before compilation.
        for token in ("Ristretto255", "SHA-512", "Argon2id"):
            self.assertIn(
                token,
                src,
                msg=(
                    f"src/lib.rs module docstring must document "
                    f"{token!r} — this is the ciphersuite the "
                    f"@serenity-kit/opaque WASM client expects."
                ),
            )


if __name__ == "__main__":
    unittest.main()
