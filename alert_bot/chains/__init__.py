"""Per-chain behaviour, resolved through a registry rather than conditionals.

Address validation, address normalisation and explorer links are the only chain-aware
decisions in the system. Everything else treats a chain as an opaque id string, which is
also what MongoDB stores (``target.chain``) and what DexScreener expects in its URLs.
"""

from .base import Chain, b58decode
from .evm import EvmChain
from .registry import (
    UnknownChain,
    all_chains,
    detect,
    get,
    is_enabled,
    is_valid_address,
    normalize_chain_id,
    register,
)
from .solana import SolanaChain

__all__ = [
    "Chain",
    "EvmChain",
    "SolanaChain",
    "UnknownChain",
    "all_chains",
    "b58decode",
    "detect",
    "get",
    "is_enabled",
    "is_valid_address",
    "normalize_chain_id",
    "register",
]
