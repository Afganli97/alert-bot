"""EVM-family chains.

One parameterised ``EvmChain`` class covering ethereum, bsc and every future EVM network:
addresses match ``0x`` plus 40 hex digits, comparison is case-insensitive, so
normalisation lowercases. Checksum casing is preserved in nothing but display.
"""
