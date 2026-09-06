"""DexScreener client.

Two calls, both unauthenticated:

* ``GET /latest/dex/tokens/{address}`` — one-shot lookup during ``/add``; picks the pair
  with the highest USD liquidity and returns its symbol (lowercased) and ``chainId``.
* ``GET /tokens/v1/{chain}/{a1,a2,...}`` — batch price poll, DEX_BATCH_SIZE addresses per
  request with DEX_BATCH_DELAY_MS between them, highest-liquidity pair winning per token.

Batching and pacing live here so the monitor cycle stays about alerts. Addresses are
keyed through ``chains.registry`` normalisation on the way in and out.
"""
