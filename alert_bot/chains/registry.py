"""Chain registry.

``register(chain)``, ``get(chain_id)``, ``all_chains()`` and ``detect(address)``, which
returns every registered chain whose validator accepts an address. The union of the
registered validators reproduces the legacy ``isValidTokenAddress`` exactly.

``get`` never raises for an unrecognised id: it returns an ``UnknownChain`` that accepts
any address and normalises to the identity. That fallback is required for parity, because
the legacy bot stores whatever ``chainId`` DexScreener reports without checking it against
a list. ENABLED_CHAINS, when set, restricts what users may add — not what already exists.

Registering a new chain is one line here and no change anywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from alert_bot.chains.base import Chain
from alert_bot.chains.evm import EvmChain
from alert_bot.chains.solana import SolanaChain


@dataclass(frozen=True, slots=True)
class UnknownChain:
    """A chain id nobody registered, treated as opaque.

    Everything it does is a no-op: any address is accepted, the address is its own
    normal form, and there is no explorer to link to. This is what keeps an alert on a
    chain we have never heard of working exactly as it does under the legacy bot, which
    stores ``bestPair.chainId`` verbatim (``handlers/tokenCommands.js:41``).
    """

    id: str
    aliases: tuple[str, ...] = ()

    @property
    def display_name(self) -> str:
        return self.id

    def validate_address(self, address: str) -> bool:
        return True

    def normalize_address(self, address: str) -> str:
        return address

    def explorer_url(self, address: str) -> str:
        return ""


_REGISTERED: dict[str, Chain] = {}


def register(chain: Chain) -> None:
    """Add a chain to the registry, rejecting a duplicate id."""
    if chain.id in _REGISTERED:
        raise ValueError(f"chain already registered: {chain.id}")
    _REGISTERED[chain.id] = chain


def normalize_chain_id(chain_id: str) -> str:
    """Lowercase and strip an id, the form ``target.chain`` is written in.

    ``handlers/alertCommands.js:91`` stores ``chain.toLowerCase()``, so a lookup has to
    use the same form to find anything.
    """
    return chain_id.strip().lower()


def get(chain_id: str) -> Chain:
    """Return the chain for an id, or an :class:`UnknownChain` — never raise."""
    normalized = normalize_chain_id(chain_id)
    chain = _REGISTERED.get(normalized)
    return chain if chain is not None else UnknownChain(normalized)


def all_chains() -> tuple[Chain, ...]:
    """Every registered chain, in registration order."""
    return tuple(_REGISTERED.values())


def detect(address: str) -> tuple[Chain, ...]:
    """Every registered chain whose validator accepts this address.

    Ambiguity is real and harmless: the chain an alert is stored under comes from the
    DexScreener lookup, not from the address shape. What the caller needs from this is
    whether the address is worth looking up at all.
    """
    return tuple(chain for chain in _REGISTERED.values() if chain.validate_address(address))


def is_valid_address(address: str) -> bool:
    """The port of ``isValidTokenAddress`` (``handlers/alertCommands.js:43``).

    The legacy check is "EVM regex **or** base58 decoding to 32 bytes", which is the
    union of the registered validators — so it is reproduced by construction rather than
    copied, and registering a chain cannot make it drift.
    """
    return bool(detect(address))


def is_enabled(chain_id: str, enabled_chains: Iterable[str]) -> bool:
    """Whether ``ENABLED_CHAINS`` permits a user to add a token on this chain.

    An empty allow-list means "accept whatever DexScreener reports", the legacy
    behaviour. The restriction applies to new alerts only: the price loop keeps
    evaluating alerts that already exist on any chain, so narrowing the list can never
    silence an alert a user is relying on.
    """
    allowed = {normalize_chain_id(item) for item in enabled_chains}
    return not allowed or normalize_chain_id(chain_id) in allowed


# -- the registered chains --------------------------------------------------
#
# One line each. The two EVM entries share a validator, so adding Base or Arbitrum
# changes nothing about which addresses the bot accepts.

register(EvmChain("ethereum", "Ethereum", "https://etherscan.io/token/{}", ("eth",)))
register(EvmChain("bsc", "BNB Chain", "https://bscscan.com/token/{}", ("bnb",)))
register(SolanaChain())
