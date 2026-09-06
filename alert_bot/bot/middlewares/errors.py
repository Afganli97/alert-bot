"""Catch-all error boundary.

Logs the exception with the update id and chat id, then replies with the same generic
Russian error message the legacy ``handleMessage`` catch block sends. Typed domain errors
from ``errors.py`` are translated to specific text before reaching this point.
"""
