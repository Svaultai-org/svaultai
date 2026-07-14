"""Unit tests for vault_handle module (pure Python, no crypto).

Runs without the OPAQUE wheel; safe on Windows dev boxes where WDAC
blocks Rust builds. Verifies:
  * generate() produces 15-byte handles
  * to_display() → from_display() round-trip is stable
  * from_display() tolerates dashes/case/whitespace variants
  * is_valid_display() returns False for malformed inputs
  * handles are unique across many generations (statistical spot-check)
"""

from __future__ import annotations

import pytest

from vault_handle import (
    VAULT_HANDLE_BYTES,
    VAULT_HANDLE_DISPLAY_CHARS,
    VAULT_HANDLE_PREFIX,
    InvalidVaultHandle,
    from_display,
    generate,
    is_valid_display,
    to_display,
)


def test_generate_returns_15_bytes() -> None:
    for _ in range(50):
        h = generate()
        assert isinstance(h, bytes)
        assert len(h) == VAULT_HANDLE_BYTES


def test_display_form_shape() -> None:
    raw = generate()
    disp = to_display(raw)
    assert disp.startswith(VAULT_HANDLE_PREFIX)
    tail = disp[len(VAULT_HANDLE_PREFIX):]
    groups = tail.split("-")
    assert len(groups) == 6
    assert all(len(g) == 4 for g in groups)
    assert len(tail.replace("-", "")) == VAULT_HANDLE_DISPLAY_CHARS


def test_round_trip_display() -> None:
    for _ in range(50):
        raw = generate()
        disp = to_display(raw)
        assert from_display(disp) == raw


def test_from_display_tolerates_variants() -> None:
    raw = generate()
    canonical = to_display(raw)
    assert from_display(canonical) == raw
    assert from_display(canonical.lower()) == raw
    assert from_display(canonical.replace("-", "")) == raw
    assert from_display(" " + canonical + " ") == raw
    assert from_display(canonical.replace("VLT-", "")) == raw


def test_from_display_rejects_invalid_chars() -> None:
    with pytest.raises(InvalidVaultHandle):
        from_display("VLT-XXXX-XXXX-XXXX-XXXX-XXXX-XXX!")
    with pytest.raises(InvalidVaultHandle):
        from_display("VLT-XXXX-XXXX-XXXX-XXXX-XXXX")
    with pytest.raises(InvalidVaultHandle):
        from_display("")
    with pytest.raises(InvalidVaultHandle):
        from_display("A" * 500)


def test_is_valid_display() -> None:
    raw = generate()
    assert is_valid_display(to_display(raw))
    assert not is_valid_display("not a handle")
    assert not is_valid_display("")
    assert not is_valid_display("VLT-XXXX")


def test_confusable_chars_normalized() -> None:
    raw = generate()
    disp = to_display(raw)
    tail = disp[len(VAULT_HANDLE_PREFIX):].replace("-", "")

    substituted = (
        tail.replace("1", "I", 1)
            .replace("0", "O", 1)
    )
    if substituted != tail:
        recovered = from_display(VAULT_HANDLE_PREFIX + substituted)
        assert recovered == raw


def test_no_two_generations_collide_in_small_sample() -> None:
    seen: set[bytes] = set()
    for _ in range(1000):
        h = generate()
        assert h not in seen, "collision within 1000 samples"
        seen.add(h)


def test_display_is_deterministic() -> None:
    raw = generate()
    a = to_display(raw)
    b = to_display(raw)
    assert a == b
