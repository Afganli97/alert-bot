"""``GET /health``.

Reports process liveness plus the age of the last completed price cycle, so the
supervisor can restart a bot whose loop has silently stopped. Never exposes
configuration or secrets.
"""
