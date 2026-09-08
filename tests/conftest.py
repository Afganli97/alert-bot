"""Shared pytest fixtures.

A settings factory built from an explicit environment mapping (never the real one), fake
DexScreener responses recorded from the live API, and an in-memory outbound queue. No
test may touch production MongoDB or the Bot API.

Only the settings factory exists so far; the service fixtures land with the steps that
need them (PLAN.md §8).
"""

from __future__ import annotations

import pytest

from alert_bot.config import Settings, load_settings

#: A complete environment, so a test can override one variable without repeating the rest.
#: Values are obviously fake: nothing here may resolve to a real bot, cluster or host.
BASE_ENV: dict[str, str] = {
    "TELEGRAM_TOKEN": "111111:test-token",
    "MONGO_URI": "mongodb://127.0.0.1:27017/dexalerts_test",
    "MONGO_DB_NAME": "dexalerts_test",
    "WEBHOOK_URL": "https://bot.invalid/webhook-v2",
    "WEBHOOK_SECRET": "test-webhook-secret",
    "ADMIN_CHAT_IDS": "42",
}


@pytest.fixture
def env() -> dict[str, str]:
    return dict(BASE_ENV)


@pytest.fixture
def settings(env: dict[str, str]) -> Settings:
    return load_settings(env)
