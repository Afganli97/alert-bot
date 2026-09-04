"""Outbound message queue.

A FIFO queue drained by one task at TG_QUEUE_DELAY_MS per message (~28/s at the default),
so that a broadcast or a burst of alerts cannot exceed the Bot API rate limit.

Ported failure handling: HTTP 429 requeues the message at the tail and sleeps
``min(retry_after, 60)`` seconds; HTTP 403 marks the user undeliverable in ``users`` and
drops the message. Unlike the legacy queue, shutdown drains what is pending within
SHUTDOWN_DRAIN_TIMEOUT_MS before the process exits.
"""
