"""Solana validation and the case-preserving normalisation of PLAN.md §6.4."""

from __future__ import annotations

import pytest

from alert_bot.chains.solana import SolanaChain

SOLANA = SolanaChain()

WSOL = "So11111111111111111111111111111111111111112"


@pytest.mark.parametrize(
    "address",
    [
        WSOL,
        "1" * 32,  # 32 zero bytes, the legacy suite's edge case
        "5D7V7Yz9KQeVZcVtX9cV9fZcV9cV9cV9cV9cV9cV9cV",
    ],
)
def test_accepts_what_decodes_to_thirty_two_bytes(address: str) -> None:
    assert SOLANA.validate_address(address) is True


@pytest.mark.parametrize(
    "address",
    [
        "",
        "invalid",  # 'l' is not a base58 character
        "1" * 44,  # decodes, but to 44 bytes
        "1" * 31,  # 31 bytes
        "0x1234567890abcdef1234567890abcdef12345678",  # '0' and 'x' are not base58
        WSOL + " ",
    ],
)
def test_rejects_everything_else(address: str) -> None:
    assert SOLANA.validate_address(address) is False


def test_normalisation_leaves_the_address_untouched() -> None:
    """Lowercasing here is the legacy defect that kept Solana alerts from ever firing."""
    assert SOLANA.normalize_address(WSOL) == WSOL
    assert SOLANA.normalize_address(WSOL) != WSOL.lower()


def test_a_lowercased_address_is_a_different_key() -> None:
    """Base58 is case-sensitive, so the two must not collapse onto one another."""
    assert SOLANA.normalize_address(WSOL.lower()) != SOLANA.normalize_address(WSOL)


def test_explorer_url_preserves_case() -> None:
    assert SOLANA.explorer_url(WSOL) == "https://solscan.io/token/" + WSOL
