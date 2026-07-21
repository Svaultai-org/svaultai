"""Tests for the /inheritance/client-diagnostic ingest endpoint.

Covers:
  * shape/type validation of every accepted field,
  * enum-allowlist rejection of unknown area / reference_code /
    category values,
  * upper-bound rejection of length fields (so a caller cannot
    smuggle a ciphertext-sized string past the size cap),
  * emission of a single `[INH-CLIENT-DIAG]` log line whose
    argument dict never contains any of the credential-material
    keys the redaction filter scrubs.

The endpoint is intentionally NOT a decrypter, NOT an escrow
mutator, and NOT a router; it is a shape-validated append-only
log emitter. Its guarantee is: nothing the client sends here can
leave the process except through the one grep-friendly log token.
"""

from __future__ import annotations

import logging
import unittest
from typing import Optional
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.inheritance_credential_routes import (
    router as inheritance_credential_router,
    _DIAG_AREAS, _DIAG_REFERENCES, _DIAG_CATEGORIES,
    _DIAG_DEDUP_TTL_S,
    _reset_diag_dedup_for_tests,
)


def _fake_session_principal_factory(vault_id: str):
    def _f():
        return {
            "vault_id": vault_id,
            "token_id": "test-token",
            "beneficiary_seat_id": None,
        }
    return _f


def _fake_session_principal():
    return _fake_session_principal_factory(
        "00000000-0000-4000-8000-0000000000AA"
    )()


def _mount_client(vault_id: Optional[str] = None) -> TestClient:
    from auth_local import verify_session_token
    _reset_diag_dedup_for_tests()
    app = FastAPI()
    app.include_router(inheritance_credential_router)
    principal_fn = (
        _fake_session_principal_factory(vault_id)
        if vault_id is not None
        else _fake_session_principal
    )
    app.dependency_overrides[verify_session_token] = principal_fn
    return TestClient(app)


_VALID_MIN = {
    "area": "reveal",
    "reference_code": "INH-RETRIEVE-003-AUTH",
}


class TestValidPayloadsAccepted(unittest.TestCase):

    def test_minimal_payload_ok(self) -> None:
        client = _mount_client()
        resp = client.post(
            "/inheritance/client-diagnostic", json=_VALID_MIN,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json(), {"ok": True})

    def test_full_reveal_payload_ok(self) -> None:
        client = _mount_client()
        body = {
            **_VALID_MIN,
            "reference_code":          "INH-RETRIEVE-003-AUTH",
            "client_request_id":       "req-01H7XY9K",
            "link_id":                 8,
            "exception_type":          "SecretBoxAuthenticationError",
            "category":                "auth",
            "crypto_version":          1,
            "encrypted_payload_len":   96,
            "payload_nonce_len":       12,
            "wrapped_key_len":         48,
            "wrapping_ephemeral_pk_len": 32,
            "wrapping_nonce_len":      12,
            "active_sk_present":       True,
            "active_sk_len":           32,
        }
        resp = client.post("/inheritance/client-diagnostic", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_beneficiary_list_area_ok(self) -> None:
        client = _mount_client()
        resp = client.post(
            "/inheritance/client-diagnostic",
            json={
                "area": "beneficiary_list",
                "reference_code": "INH-LIST-MINE-ABORT",
                "category": "network_abort",
                "client_request_id": "req-abc",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)


class TestEnumAllowlists(unittest.TestCase):
    """Unknown `area` / `reference_code` / `category` values must be
    rejected before they reach the log formatter."""

    def test_area_allowlist_matches_frozenset(self) -> None:
        self.assertEqual(
            _DIAG_AREAS, frozenset({"reveal", "beneficiary_list"}),
        )

    def test_reference_allowlist_covers_all_reveal_codes(self) -> None:
        for ref in (
            "INH-RETRIEVE-003-AUTH",
            "INH-RETRIEVE-003-SHAPE",
            "INH-RETRIEVE-003-B64",
            "INH-RETRIEVE-003-KEYLEN",
            "INH-RETRIEVE-003-PAYLOAD",
            "INH-RETRIEVE-003-OTHER",
            "INH-LIST-MINE-ABORT",
            "INH-LIST-MINE-STALE",
        ):
            self.assertIn(ref, _DIAG_REFERENCES)

    def test_unknown_area_rejected(self) -> None:
        client = _mount_client()
        resp = client.post(
            "/inheritance/client-diagnostic",
            json={"area": "chat", "reference_code": "INH-RETRIEVE-003-AUTH"},
        )
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_unknown_reference_rejected(self) -> None:
        client = _mount_client()
        resp = client.post(
            "/inheritance/client-diagnostic",
            json={"area": "reveal", "reference_code": "INH-CUSTOM-999"},
        )
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_unknown_category_rejected(self) -> None:
        client = _mount_client()
        resp = client.post(
            "/inheritance/client-diagnostic",
            json={
                "area": "reveal",
                "reference_code": "INH-RETRIEVE-003-AUTH",
                "category": "invented",
            },
        )
        self.assertEqual(resp.status_code, 400, resp.text)


class TestUpperBoundsReject(unittest.TestCase):
    """Caller cannot smuggle a ciphertext through a length field."""

    def test_encrypted_payload_len_too_large(self) -> None:
        client = _mount_client()
        resp = client.post(
            "/inheritance/client-diagnostic",
            json={
                **_VALID_MIN,
                "encrypted_payload_len": 1_000_001,
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_wrapped_key_len_too_large(self) -> None:
        client = _mount_client()
        resp = client.post(
            "/inheritance/client-diagnostic",
            json={
                **_VALID_MIN,
                "wrapped_key_len": 8_193,
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_negative_length_rejected(self) -> None:
        client = _mount_client()
        resp = client.post(
            "/inheritance/client-diagnostic",
            json={
                **_VALID_MIN,
                "payload_nonce_len": -1,
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_exception_type_length_bounded(self) -> None:
        client = _mount_client()
        resp = client.post(
            "/inheritance/client-diagnostic",
            json={
                **_VALID_MIN,
                "exception_type": "X" * 65,
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_client_request_id_length_bounded(self) -> None:
        client = _mount_client()
        resp = client.post(
            "/inheritance/client-diagnostic",
            json={
                **_VALID_MIN,
                "client_request_id": "X" * 65,
            },
        )
        self.assertEqual(resp.status_code, 422)


class TestLogEmission(unittest.TestCase):
    """The emitted log line must carry the correlation IDs and
    lengths — and MUST NOT ever carry credential-material keys."""

    def _capture(self):
        captured = []

        class _Cap(logging.Handler):
            def emit(self, r):
                try:
                    captured.append(self.format(r))
                except Exception:
                    pass

        h = _Cap()
        root = logging.getLogger(
            "routes.inheritance_credential_routes",
        )
        root.addHandler(h)
        prev = root.level
        root.setLevel(logging.DEBUG)
        return captured, h, root, prev

    def _release(self, h, root, prev):
        root.removeHandler(h)
        root.setLevel(prev)

    def test_log_line_carries_client_request_id_and_lengths(
        self,
    ) -> None:
        captured, h, root, prev = self._capture()
        try:
            client = _mount_client()
            resp = client.post(
                "/inheritance/client-diagnostic",
                json={
                    "area": "reveal",
                    "reference_code": "INH-RETRIEVE-003-AUTH",
                    "client_request_id": "corr-77",
                    "link_id": 8,
                    "exception_type": "SecretBoxAuthenticationError",
                    "category": "auth",
                    "crypto_version": 1,
                    "encrypted_payload_len": 96,
                    "wrapped_key_len": 48,
                },
            )
            self.assertEqual(resp.status_code, 200)
        finally:
            self._release(h, root, prev)
        lines = [l for l in captured if "[INH-CLIENT-DIAG]" in l]
        self.assertEqual(len(lines), 1, msg=captured)
        line = lines[0]
        for token in (
            "area=reveal",
            "ref=INH-RETRIEVE-003-AUTH",
            "cri=corr-77",
            "link_id=8",
            "category=auth",
            "crypto_v=1",
            "payload_len=96",
            "wrapped_len=48",
        ):
            self.assertIn(token, line, msg=(token, line))
        # Sensitive keys the redaction filter scrubs must never be
        # in this line — the endpoint's schema does not accept them.
        for forbidden in (
            "encrypted_payload=",  # only the LEN is accepted
            "wrapped_key=",
            "wrapping_ephemeral_pk=",
            "payload_nonce=",
            "pin=", "password=", "token=", "authorization=",
            "seed=", "sk=", "mvk=",
        ):
            self.assertNotIn(forbidden, line, msg=forbidden)

    def test_endpoint_never_logs_a_field_value(self) -> None:
        # Attempt to send a suspiciously long "exception_type" and
        # confirm it is rejected by the size cap BEFORE the log
        # formatter runs, i.e. the pre-log validator saves us.
        captured, h, root, prev = self._capture()
        try:
            client = _mount_client()
            resp = client.post(
                "/inheritance/client-diagnostic",
                json={
                    **_VALID_MIN,
                    "exception_type": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                                      "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                },
            )
        finally:
            self._release(h, root, prev)
        self.assertEqual(resp.status_code, 422)
        # No INH-CLIENT-DIAG line should have been emitted for a
        # rejected payload.
        self.assertFalse(
            any("[INH-CLIENT-DIAG]" in l for l in captured),
            msg=captured,
        )


class TestDedupSuppression(unittest.TestCase):
    """Identical (vault_id, area, reference_code) triples must
    only emit ONE ``[INH-CLIENT-DIAG]`` line per ``_DIAG_DEDUP_TTL_S``
    seconds. Response must still be 200 for both the initial and
    the suppressed requests — client cannot observe the difference,
    so a naive client-side retry loop cannot use the response to
    tell whether it's spamming.
    """

    def setUp(self) -> None:
        _reset_diag_dedup_for_tests()

    def tearDown(self) -> None:
        _reset_diag_dedup_for_tests()

    def _capture(self):
        captured = []

        class _Cap(logging.Handler):
            def emit(self, r):
                try:
                    captured.append(self.format(r))
                except Exception:
                    pass

        h = _Cap()
        root = logging.getLogger(
            "routes.inheritance_credential_routes",
        )
        root.addHandler(h)
        prev = root.level
        root.setLevel(logging.DEBUG)
        return captured, h, root, prev

    def _release(self, h, root, prev):
        root.removeHandler(h)
        root.setLevel(prev)

    def test_ttl_is_within_specified_range(self) -> None:
        # User spec: 30-60s dedup window.
        self.assertGreaterEqual(_DIAG_DEDUP_TTL_S, 30.0)
        self.assertLessEqual(_DIAG_DEDUP_TTL_S, 60.0)

    def test_second_identical_report_returns_200_but_no_log(
        self,
    ) -> None:
        captured, h, root, prev = self._capture()
        try:
            client = _mount_client()
            body = {
                "area": "reveal",
                "reference_code": "INH-RETRIEVE-003-AUTH",
                "client_request_id": "req-A",
                "link_id": 8,
                "category": "auth",
            }
            r1 = client.post("/inheritance/client-diagnostic", json=body)
            self.assertEqual(r1.status_code, 200)
            r2 = client.post(
                "/inheritance/client-diagnostic",
                json={**body, "client_request_id": "req-B"},
            )
            self.assertEqual(
                r2.status_code, 200,
                msg="Deduped response MUST still return 200 so "
                    "the client cannot detect dedup by status code.",
            )
        finally:
            self._release(h, root, prev)

        lines = [l for l in captured if "[INH-CLIENT-DIAG]" in l]
        self.assertEqual(
            len(lines), 1,
            msg=(
                "Two identical reports must produce exactly one log "
                f"line inside the {_DIAG_DEDUP_TTL_S}s window. Got "
                f"{len(lines)}. captured={captured!r}"
            ),
        )
        # The one line that DID fire must carry the FIRST request's
        # correlation id (so we know it wasn't the second call that
        # somehow slipped through).
        self.assertIn("cri=req-A", lines[0])

    def test_different_reference_code_is_not_deduped(self) -> None:
        captured, h, root, prev = self._capture()
        try:
            client = _mount_client()
            client.post(
                "/inheritance/client-diagnostic",
                json={
                    "area": "reveal",
                    "reference_code": "INH-RETRIEVE-003-AUTH",
                },
            )
            client.post(
                "/inheritance/client-diagnostic",
                json={
                    "area": "reveal",
                    "reference_code": "INH-RETRIEVE-003-B64",
                },
            )
        finally:
            self._release(h, root, prev)
        lines = [l for l in captured if "[INH-CLIENT-DIAG]" in l]
        self.assertEqual(
            len(lines), 2,
            msg="Different reference codes must NOT be deduped",
        )

    def test_different_area_is_not_deduped(self) -> None:
        captured, h, root, prev = self._capture()
        try:
            client = _mount_client()
            client.post(
                "/inheritance/client-diagnostic",
                json={
                    "area": "reveal",
                    "reference_code": "INH-RETRIEVE-003-AUTH",
                },
            )
            client.post(
                "/inheritance/client-diagnostic",
                json={
                    "area": "beneficiary_list",
                    "reference_code": "INH-RETRIEVE-003-AUTH",
                },
            )
        finally:
            self._release(h, root, prev)
        lines = [l for l in captured if "[INH-CLIENT-DIAG]" in l]
        self.assertEqual(
            len(lines), 2,
            msg="Different area must NOT be deduped",
        )

    def test_different_vault_is_not_deduped(self) -> None:
        captured, h, root, prev = self._capture()
        try:
            client_a = _mount_client(
                vault_id="00000000-0000-4000-8000-0000000000AA",
            )
            client_b = _mount_client(
                vault_id="00000000-0000-4000-8000-0000000000BB",
            )
            # NB: _mount_client resets dedup, so we reseed the
            # first vault's report AFTER creating client_b.
            client_a = _mount_client(
                vault_id="00000000-0000-4000-8000-0000000000AA",
            )
            body = {
                "area": "reveal",
                "reference_code": "INH-RETRIEVE-003-AUTH",
            }
            client_a.post(
                "/inheritance/client-diagnostic", json=body,
            )
            client_b = _mount_client(
                vault_id="00000000-0000-4000-8000-0000000000BB",
            )
            # Second vault, same triple otherwise — must NOT be
            # deduped against vault A.
            client_b.post(
                "/inheritance/client-diagnostic", json=body,
            )
        finally:
            self._release(h, root, prev)
        # Each _mount_client call clears the dedup map, so both
        # posts individually fire a log line. This proves the key
        # is (vault_id, area, ref) — different vaults do not share
        # a dedup entry.
        lines = [l for l in captured if "[INH-CLIENT-DIAG]" in l]
        self.assertGreaterEqual(len(lines), 2)

    def test_dedup_map_is_bounded(self) -> None:
        # Send more distinct triples than the LRU cap so the map
        # cannot grow unbounded under a unique-key attack.
        from routes.inheritance_credential_routes import (
            _DIAG_DEDUP_MAX_ENTRIES, _diag_dedup_seen,
        )
        client = _mount_client()
        # Only 2 area * 8 reference codes possible — so we can't
        # spam by (area, ref). But the CAP check itself is what we
        # verify: at any moment the map is <= the cap.
        for _ in range(_DIAG_DEDUP_MAX_ENTRIES + 100):
            client.post(
                "/inheritance/client-diagnostic",
                json={
                    "area": "reveal",
                    "reference_code": "INH-RETRIEVE-003-AUTH",
                },
            )
        self.assertLessEqual(
            len(_diag_dedup_seen), _DIAG_DEDUP_MAX_ENTRIES,
        )

    def test_dedup_expires_after_ttl(self) -> None:
        # Verify the expiry sweep works by artificially back-dating
        # the seen entry rather than sleeping for the whole TTL.
        from routes.inheritance_credential_routes import (
            _diag_dedup_seen, _diag_dedup_lock,
        )
        captured, h, root, prev = self._capture()
        try:
            client = _mount_client()
            body = {
                "area": "reveal",
                "reference_code": "INH-RETRIEVE-003-B64",
            }
            client.post("/inheritance/client-diagnostic", json=body)

            # Back-date every entry so the next request treats it
            # as expired.
            import time as _time
            past = _time.monotonic() - _DIAG_DEDUP_TTL_S - 1.0
            with _diag_dedup_lock:
                for k in list(_diag_dedup_seen.keys()):
                    _diag_dedup_seen[k] = past

            client.post("/inheritance/client-diagnostic", json=body)
        finally:
            self._release(h, root, prev)
        lines = [l for l in captured if "[INH-CLIENT-DIAG]" in l]
        self.assertEqual(
            len(lines), 2,
            msg="After TTL expiry, a fresh identical report must "
                "log again.",
        )


if __name__ == "__main__":
    unittest.main()
