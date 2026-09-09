"""EVM-family chains.

One parameterised ``EvmChain`` class covering ethereum, bsc and every future EVM network:
addresses match ``0x`` plus 40 hex digits, comparison is case-insensitive, so
normalisation lowercases. Checksum casing is preserved in nothing but display.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The legacy ``/^0x[0-9a-fA-F]{40}$/`` (``handlers/alertCommands.js:44``), matched with
#: ``fullmatch``: Python's ``$`` also matches before a trailing newline, JavaScript's
#: does not, and an address with a stray newline must stay invalid in both bots.
_EVM_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")


@dataclass(frozen=True, slots=True)
class EvmChain:
    """An EVM network. Adding one is a single line in ``registry.py``."""

    id: str
    display_name: str
    #: Explorer link with one ``{}`` placeholder for the address.
    explorer_template: str
    aliases: tuple[str, ...] = ()

    def validate_address(self, address: str) -> bool:
        return _EVM_ADDRESS.fullmatch(address) is not None

    def normalize_address(self, address: str) -> str:
        """Lowercase, so a checksummed address and a lowercase one are one key.

        This is the EVM half of the PLAN.md §6.4 fix. It is applied on both sides — the
        stored address and the address DexScreener reports — so the two can no longer
        disagree about case.
        """
        return address.lower()

    def explorer_url(self, address: str) -> str:
        return self.explorer_template.format(self.normalize_address(address))
