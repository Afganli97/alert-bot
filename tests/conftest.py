"""Shared pytest fixtures.

A settings factory built from an explicit environment mapping (never the real one), fake
DexScreener responses recorded from the live API, and an in-memory outbound queue. No
test may touch production MongoDB or the Bot API.
"""
