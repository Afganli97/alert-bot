"""EVM validation, normalisation and explorer links."""

from __future__ import annotations

import pytest

from alert_bot.chains.evm import EvmChain

ETHEREUM = EvmChain("ethereum", "Ethereum", "https://etherscan.io/token/{}", ("eth",))

LOWERCASE = "0x1234567890abcdef1234567890abcdef12345678"
CHECKSUMMED = "0xABCDEF1234567890ABCDEF1234567890ABCDEF12"


@pytest.mark.parametrize("address", [LOWERCASE, CHECKSUMMED])
def test_accepts_forty_hex_digits_in_either_case(address: str) -> None:
    assert ETHEREUM.validate_address(address) is True


@pytest.mark.parametrize(
    "address",
    [
        "",
        "invalid",
        "0xinvalid",
        "0x1234567890abcdef1234567890abcdef1234567",  # 39 digits
        "0x1234567890abcdef1234567890abcdef123456789",  # 41 digits
        "1234567890abcdef1234567890abcdef12345678",  # no 0x
        "0X1234567890abcdef1234567890abcdef12345678",  # uppercase prefix
        " " + LOWERCASE,
    ],
)
def test_rejects_anything_else(address: str) -> None:
    assert ETHEREUM.validate_address(address) is False


def test_a_trailing_newline_is_rejected() -> None:
    """``fullmatch``, not ``$``: Python's ``$`` would accept this, JavaScript's does not."""
    assert ETHEREUM.validate_address(LOWERCASE + "\n") is False


def test_normalisation_lowercases_so_checksummed_and_plain_are_one_key() -> None:
    """The EVM half of the PLAN.md §6.4 fix."""
    assert ETHEREUM.normalize_address(CHECKSUMMED) == CHECKSUMMED.lower()
    assert ETHEREUM.normalize_address(CHECKSUMMED) == ETHEREUM.normalize_address(
        CHECKSUMMED.lower()
    )


def test_normalisation_is_idempotent() -> None:
    once = ETHEREUM.normalize_address(CHECKSUMMED)
    assert ETHEREUM.normalize_address(once) == once


def test_explorer_url_uses_the_normalised_address() -> None:
    assert ETHEREUM.explorer_url(CHECKSUMMED) == (
        "https://etherscan.io/token/" + CHECKSUMMED.lower()
    )


def test_every_evm_network_shares_one_validator() -> None:
    """Adding an EVM chain cannot change which addresses the bot accepts."""
    bsc = EvmChain("bsc", "BNB Chain", "https://bscscan.com/token/{}")

    assert bsc.validate_address(CHECKSUMMED) == ETHEREUM.validate_address(CHECKSUMMED)
    assert bsc.explorer_url(LOWERCASE) == "https://bscscan.com/token/" + LOWERCASE
