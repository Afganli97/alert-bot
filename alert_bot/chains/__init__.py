"""Per-chain behaviour, resolved through a registry rather than conditionals.

Address validation, address normalisation and explorer links are the only chain-aware
decisions in the system. Everything else treats a chain as an opaque id string, which is
also what MongoDB stores (``target.chain``) and what DexScreener expects in its URLs.
"""
