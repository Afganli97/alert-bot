"""Solana.

Addresses are base58 and decode to exactly 32 bytes — the check the legacy bot performed
with the ``bs58`` package. Base58 is case-sensitive, so normalisation must leave the
string untouched; lowercasing it is the legacy defect from PLAN.md §6.4.
"""
