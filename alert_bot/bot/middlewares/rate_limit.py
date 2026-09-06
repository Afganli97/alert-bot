"""Per-chat command rate limit.

RATE_LIMIT_COMMANDS commands per RATE_LIMIT_WINDOW_MS, in memory, as the legacy
``commandTimestamps`` Map does. Over the limit the update is dropped with a notice.
"""
