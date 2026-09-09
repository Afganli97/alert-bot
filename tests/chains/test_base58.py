"""The base58 codec that replaces the ``bs58`` dependency."""

from __future__ import annotations

import pytest

from alert_bot.chains.base import B58_ALPHABET, b58decode


def test_alphabet_excludes_the_ambiguous_characters() -> None:
    assert len(B58_ALPHABET) == 58
    assert not set("0OIl") & set(B58_ALPHABET)


def test_empty_string_decodes_to_no_bytes() -> None:
    """``bs58.decode('')`` returns an empty buffer rather than throwing."""
    assert b58decode("") == b""


def test_leading_ones_decode_to_leading_zero_bytes() -> None:
    assert b58decode("1") == b"\x00"
    assert b58decode("1" * 32) == b"\x00" * 32
    assert b58decode("12") == b"\x00\x01"


def test_known_vector() -> None:
    assert b58decode("2NEpo7TZRRrLZSi2U") == b"Hello World!"


@pytest.mark.parametrize("value", ["invalid", "0xinvalid", "abc0", "O", "I", "l", "so1 ana"])
def test_a_character_outside_the_alphabet_raises(value: str) -> None:
    with pytest.raises(ValueError):
        b58decode(value)
