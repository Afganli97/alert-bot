"""One poll cycle.

Load active alerts, drop those of undeliverable users (cached for
BLOCKED_USERS_CACHE_TTL_MS), group addresses by chain, fetch prices in batches, evaluate
each alert, queue the notifications, then advance the baselines.

Baselines are written after the send, per alert, as the legacy checker does: a crash
between the two re-fires the alert, and a send that fails still advances the baseline.
Ported deliberately so dual-run output stays comparable (PLAN.md §6.8).
"""
