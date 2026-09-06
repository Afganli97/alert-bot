"""Condition evaluators, registered by ``condition.kind``.

``percent_change`` is the only kind today. Its semantics are the legacy semantics: a null
baseline is set on the first cycle that sees a price and fires nothing, and the baseline
is reset to the current price every time the alert fires. Change is therefore measured
since the last notification and sub-threshold moves accumulate indefinitely — unusual,
and ported as-is (PLAN.md §5 row).

New kinds — absolute price, rolling window, liquidity — register here and require no
change to the cycle.
"""
