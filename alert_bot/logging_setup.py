"""Logging configuration.

Configures the stdlib logging root from LOG_LEVEL: a single stderr handler, timestamps in
UTC, and formatting suited to ``journalctl``. Also installs the filters that keep secrets
(bot token, Mongo URI credentials, webhook secret) out of log records.
"""
