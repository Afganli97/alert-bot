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
