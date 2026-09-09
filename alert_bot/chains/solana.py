"""Solana.

Addresses are base58 and decode to exactly 32 bytes — the check the legacy bot performed
with the ``bs58`` package. Base58 is case-sensitive, so normalisation must leave the
string untouched; lowercasing it is the legacy defect from PLAN.md §6.4.
"""

from __future__ import annotations

from dataclasses import dataclass

from alert_bot.chains.base import b58decode

#: A Solana public key is 32 bytes (``handlers/alertCommands.js:50``).
ADDRESS_BYTES = 32


@dataclass(frozen=True, slots=True)
class SolanaChain:
    id: str = "solana"
    display_name: str = "Solana"
    aliases: tuple[str, ...] = ("sol",)
    explorer_template: str = "https://solscan.io/token/{}"

    def validate_address(self, address: str) -> bool:
        try:
            decoded = b58decode(address)
        except ValueError:
            return False
        return len(decoded) == ADDRESS_BYTES

    def normalize_address(self, address: str) -> str:
        """Return the address unchanged.

        Base58 is case-sensitive — ``So1…`` and ``so1…`` are different keys, and only one
        of them is a real address. The legacy price loop lowercased it anyway
        (``checkers/dexPriceChecker.js:62``) while looking the alert up by the address as
        typed, so every Solana alert missed the cache and never fired (PLAN.md §6.4).
        """
        return address

    def explorer_url(self, address: str) -> str:
        return self.explorer_template.format(address)
