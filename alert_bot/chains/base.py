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
