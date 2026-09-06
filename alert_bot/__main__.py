"""Entry point: ``python -m alert_bot``.

Owns the process lifecycle and nothing else — build the dependency graph, start the
webhook server (or long polling) and the price monitor, then wait for SIGINT/SIGTERM and
shut both down in order: stop accepting updates, finish the running cycle, drain the
outbound queue within SHUTDOWN_DRAIN_TIMEOUT_MS, close MongoDB.

No business logic lives here; it is wiring only.
"""
