"""Regression tests for the 2026-07-20 username blind-index correction.

The 2026-07-19 corrective release changed the client-side vault_handle
derivation from CSPRNG to SHA-256(salt||normalized_username). Rows
written before that change carry a random handle; rows written after
carry a deterministic handle. The partial UNIQUE on ``vault_handle``
cannot detect the two representations of the SAME human username as
a collision, and so re-registering "Alexa" produced a second vaults
row on 2026-07-20.

The fix is a derivation-version-independent blind index:

    HMAC-SHA256(env[VAULTAI_USERNAME_BLIND_INDEX_PEPPER], normalized)

stored in ``vaults.username_blind_index`` with a partial UNIQUE index.
This test covers the pure Python side (the HMAC helper + the request
model shape). The end-to-end DB test lives in the Docker builder
stage where a real Postgres is available.
"""

from __future__ import annotations

import base64
import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_pepper(monkeypatch):
    """Every test picks its own pepper so nothing else in the process
    accidentally shares state.
    """
    monkeypatch.setenv(
        "VAULTAI_USERNAME_BLIND_INDEX_PEPPER",
        base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("="),
    )
    yield


class TestBlindIndexHelper:
    def test_same_username_yields_same_bindex(self, monkeypatch):
        from routes import auth_zk_routes as m
        bi1 = m._compute_username_blind_index("alexa")
        bi2 = m._compute_username_blind_index("alexa")
        assert bi1 == bi2

    def test_different_usernames_yield_different_bindex(self):
        from routes import auth_zk_routes as m
        assert m._compute_username_blind_index(
            "alexa"
        ) != m._compute_username_blind_index("bob")

    def test_length_is_32_bytes(self):
        from routes import auth_zk_routes as m
        bi = m._compute_username_blind_index("alexa")
        assert bi is not None
        assert len(bi) == 32

    def test_returns_none_when_no_pepper_configured(self, monkeypatch):
        from routes import auth_zk_routes as m
        monkeypatch.delenv("VAULTAI_USERNAME_BLIND_INDEX_PEPPER", raising=False)
        assert m._compute_username_blind_index("alexa") is None

    def test_normalized_variants_of_alexa_all_collide(self):
        """Every visually-equivalent form of "Alexa" must produce the
        SAME blind index — so a second registration under "ALEXA",
        " alexa ", or " Alexa " cannot slip past the partial UNIQUE.
        """
        from vault_handle import normalize_username
        from routes import auth_zk_routes as m
        base = m._compute_username_blind_index(normalize_username("Alexa"))
        assert base is not None
        for variant in [
            "alexa",
            "ALEXA",
            "  Alexa  ",
            " alexa ",
            "Alexa ",
            "  ALEXA  ",
        ]:
            assert (
                m._compute_username_blind_index(normalize_username(variant))
                == base
            ), f"variant {variant!r} did not collide with Alexa"

    def test_visually_distinct_usernames_do_not_collide(self):
        from vault_handle import normalize_username
        from routes import auth_zk_routes as m
        a = m._compute_username_blind_index(normalize_username("Alexa"))
        b = m._compute_username_blind_index(normalize_username("Alex"))
        c = m._compute_username_blind_index(normalize_username("Bob"))
        assert a is not None and b is not None and c is not None
        assert a != b
        assert a != c
        assert b != c

    def test_pepper_change_changes_bindex(self, monkeypatch):
        """Two different deployments must produce different blind
        indexes for the same username; a DB dump from one deployment
        cannot be used to enumerate usernames on the other.
        """
        from routes import auth_zk_routes as m
        monkeypatch.setenv(
            "VAULTAI_USERNAME_BLIND_INDEX_PEPPER",
            base64.urlsafe_b64encode(b"pepper-A" * 4).decode("ascii").rstrip("="),
        )
        bi_a = m._compute_username_blind_index("alexa")
        monkeypatch.setenv(
            "VAULTAI_USERNAME_BLIND_INDEX_PEPPER",
            base64.urlsafe_b64encode(b"pepper-B" * 4).decode("ascii").rstrip("="),
        )
        bi_b = m._compute_username_blind_index("alexa")
        assert bi_a != bi_b


class TestRequestModelsCarryNormalizedUsername:
    def test_zk_register_init_accepts_normalized_username(self):
        from routes.auth_zk_routes import ZkRegisterInitRequest
        req = ZkRegisterInitRequest(
            vault_handle="VLT-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX",
            ke1="AAAA",
            normalized_username="alexa",
        )
        assert req.normalized_username == "alexa"

    def test_zk_register_init_still_accepts_omission(self):
        from routes.auth_zk_routes import ZkRegisterInitRequest
        req = ZkRegisterInitRequest(
            vault_handle="VLT-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX",
            ke1="AAAA",
        )
        assert req.normalized_username is None

    def test_zk_register_finalize_accepts_normalized_username(self):
        from routes.auth_zk_routes import ZkRegisterFinalizeRequest
        req = ZkRegisterFinalizeRequest(
            vault_handle="VLT-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX",
            ke3="AAAA",
            wrapped_mvk="AAAA",
            wrapped_sk_vault="AAAA",
            pk_vault_public="AAAA",
            display_name_ciphertext="AAAA",
            acknowledged_irrecoverable=True,
            pin_salt="AAAA",
            pin_verifier="AAAA",
            kdf_iterations=600_000,
            normalized_username="alexa",
        )
        assert req.normalized_username == "alexa"

    def test_zk_login_init_accepts_normalized_username(self):
        from routes.auth_zk_routes import ZkLoginInitRequest
        req = ZkLoginInitRequest(
            vault_handle="VLT-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX",
            ke1="AAAA",
            normalized_username="alexa",
        )
        assert req.normalized_username == "alexa"


class TestDuplicateUsernameCopy:
    def test_duplicate_username_error_matches_spec(self):
        from routes.auth_zk_routes import DUPLICATE_USERNAME_ERROR
        assert DUPLICATE_USERNAME_ERROR == (
            "That username is already taken. Please choose another."
        )

    def test_generic_auth_error_matches_spec(self):
        from routes.auth_zk_routes import GENERIC_ZK_AUTH_ERROR
        assert GENERIC_ZK_AUTH_ERROR == "Wrong username or PIN."
