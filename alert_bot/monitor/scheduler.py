"""Periodic driver.

One asyncio task that runs a cycle, then waits DEX_CYCLE_INTERVAL_MS before the next —
the self-rescheduling shape of the legacy ``setTimeout`` loop, so the interval is measured
between cycles rather than between starts. Overlapping cycles are impossible by
construction.

Also owns the shutdown handshake: stop scheduling, let the running cycle finish, report
when it is safe to close the database.
"""
