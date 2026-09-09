"""The registry: legacy validation parity, the unknown-chain fallback, and §6.4.

The address vectors below are the ones the legacy suite asserts on
(``test/isValidTokenAddress.test.js``, ``test/alertCommands.test.js:39``). They are the
contract: ``registry.is_valid_address`` must answer exactly what ``isValidTokenAddress``
answers, for every one of them.
"""

from __future__ import annotations

from typing import Iterator

import pytest

from alert_bot.chains import registry
from alert_bot.chains.evm import EvmChain
from alert_bot.chains.registry import UnknownChain

WSOL = "So11111111111111111111111111111111111111112"
CHECKSUMMED = "0xABCDEF1234567890ABCDEF1234567890ABCDEF12"


@pytest.fixture
def isolated_registry() -> Iterator[None]:
    """Undo registrations a test makes; the registry is module-level state."""
    saved = dict(registry._REGISTERED)
    yield
    registry._REGISTERED.clear()
    registry._REGISTERED.update(saved)


# -- parity with isValidTokenAddress ----------------------------------------


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("0x1234567890abcdef1234567890abcdef12345678", True),
        ("0xABCDEF1234567890ABCDEF1234567890ABCDEF12", True),
        ("5D7V7Yz9KQeVZcVtX9cV9fZcV9cV9cV9cV9cV9cV9cV", True),
        (WSOL, True),
        ("1" * 32, True),
        ("1" * 44, False),
        ("invalid", False),
        ("0xinvalid", False),
        ("", False),
    ],
)
def test_matches_the_legacy_validator(address: str, expected: bool) -> None:
    assert registry.is_valid_address(address) is expected


def test_detect_returns_the_chains_that_accept_an_address() -> None:
    evm = {chain.id for chain in registry.detect(CHECKSUMMED)}
    solana = {chain.id for chain in registry.detect(WSOL)}

    assert evm == {"ethereum", "bsc"}
    assert solana == {"solana"}
    assert registry.detect("invalid") == ()


def test_an_evm_address_is_never_also_a_solana_one() -> None:
    """``0`` and ``x`` are outside the base58 alphabet, so the two sets cannot overlap."""
    for chain in registry.detect(CHECKSUMMED):
        assert chain.id != "solana"


# -- lookup and the unknown-chain fallback ----------------------------------


def test_get_returns_the_registered_chain() -> None:
    assert registry.get("ethereum").display_name == "Ethereum"


def test_get_lowercases_the_id_as_the_stored_documents_do() -> None:
    assert registry.get("  Ethereum  ").id == "ethereum"


@pytest.mark.parametrize("chain_id", ["base", "sui", ""])
def test_an_unregistered_chain_falls_back_instead_of_raising(chain_id: str) -> None:
    """Parity: the legacy bot stores whatever chainId DexScreener reports."""
    chain = registry.get(chain_id)

    assert isinstance(chain, UnknownChain)
    assert chain.id == chain_id
    assert chain.display_name == chain_id
    assert chain.validate_address("anything at all") is True
    assert chain.normalize_address("MixedCase") == "MixedCase"
    assert chain.explorer_url("MixedCase") == ""


def test_all_chains_lists_the_registered_ones_in_order() -> None:
    assert [chain.id for chain in registry.all_chains()] == ["ethereum", "bsc", "solana"]


def test_registering_a_chain_needs_one_line(isolated_registry: None) -> None:
    registry.register(EvmChain("base", "Base", "https://basescan.org/token/{}"))

    assert registry.get("base").display_name == "Base"
    assert {chain.id for chain in registry.detect(CHECKSUMMED)} == {
        "ethereum",
        "bsc",
        "base",
    }


def test_registering_an_evm_chain_does_not_widen_the_validator(
    isolated_registry: None,
) -> None:
    registry.register(EvmChain("base", "Base", "https://basescan.org/token/{}"))

    assert registry.is_valid_address("invalid") is False
    assert registry.is_valid_address("1" * 44) is False


def test_a_duplicate_id_is_rejected(isolated_registry: None) -> None:
    with pytest.raises(ValueError):
        registry.register(EvmChain("ethereum", "Ethereum", "https://etherscan.io/token/{}"))


# -- ENABLED_CHAINS ---------------------------------------------------------


def test_an_empty_allow_list_enables_everything() -> None:
    assert registry.is_enabled("ethereum", ()) is True
    assert registry.is_enabled("whatever", ()) is True


def test_the_allow_list_is_matched_on_the_normalised_id() -> None:
    assert registry.is_enabled("Ethereum", ("ethereum",)) is True
    assert registry.is_enabled("solana", ("ethereum", "bsc")) is False


# -- PLAN.md §6.4 -----------------------------------------------------------


@pytest.mark.parametrize(
    ("chain_id", "stored", "reported"),
    [
        ("ethereum", CHECKSUMMED, CHECKSUMMED.lower()),
        ("ethereum", CHECKSUMMED.lower(), CHECKSUMMED),
        ("solana", WSOL, WSOL),
    ],
)
def test_the_price_cache_key_agrees_with_the_lookup(
    chain_id: str, stored: str, reported: str
) -> None:
    """Both sides go through the same ``normalize_address``, so they cannot diverge.

    The legacy loop keyed the cache on ``baseToken.address.toLowerCase()`` and looked it
    up with the address as stored, so a checksummed EVM or any Solana alert missed every
    time and never fired.
    """
    chain = registry.get(chain_id)

    assert chain.normalize_address(stored) == chain.normalize_address(reported)


def test_the_legacy_mismatch_is_what_the_fix_removes() -> None:
    """Spelling out the defect: lowercasing a Solana address loses the alert."""
    solana = registry.get("solana")

    assert solana.normalize_address(WSOL) != WSOL.lower()
