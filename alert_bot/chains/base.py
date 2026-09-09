"""The ``Chain`` protocol.

A chain provides:

* ``id`` — the DexScreener ``chainId``; the value stored in ``target.chain``.
* ``display_name`` / ``aliases`` — presentation and user input matching.
* ``validate_address(address)`` — accepts an address belonging to this chain.
* ``normalize_address(address)`` — the canonical form used as storage and price-cache
  key. Lowercase for EVM, unchanged for base58 chains. Getting this per-chain is what
  fixes the cache-key mismatch described in PLAN.md §6.4.
* ``explorer_url(address)`` — link shown alongside an alert.

Also home to the shared base58 codec, kept here rather than pulled in as a dependency.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Chain(Protocol):
    """What every registered chain implements. See the module docstring."""

    id: str
    display_name: str
    aliases: tuple[str, ...]

    def validate_address(self, address: str) -> bool: ...

    def normalize_address(self, address: str) -> str: ...

    def explorer_url(self, address: str) -> str: ...


#: Bitcoin's base58 ordering, the one ``bs58`` uses. ``0``, ``O``, ``I`` and ``l`` are
#: absent by design, which is why an address containing one is rejected outright.
B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

_B58_DIGITS = {char: value for value, char in enumerate(B58_ALPHABET)}


def b58decode(value: str) -> bytes:
    """Decode base58, raising :class:`ValueError` on anything that is not.

    Twenty lines against a dependency: the legacy bot pulls in ``bs58`` for the single
    call ``decode(address).length === 32`` (``handlers/alertCommands.js:49``), and that
    is the only use base58 has here.

    A leading ``1`` is the digit zero and encodes a leading zero byte, so the all-``1``
    address ``"1" * 32`` decodes to 32 zero bytes and is a valid Solana address — a case
    the legacy test suite pins down (``test/isValidTokenAddress.test.js:18``) and which a
    plain big-integer conversion would get wrong.
    """
    number = 0
    for char in value:
        digit = _B58_DIGITS.get(char)
        if digit is None:
            raise ValueError(f"not a base58 character: {char!r}")
        number = number * 58 + digit

    leading_zeros = len(value) - len(value.lstrip(B58_ALPHABET[0]))
    body = number.to_bytes((number.bit_length() + 7) // 8, "big")
    return b"\x00" * leading_zeros + body
