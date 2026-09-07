"""Configuration parsing, and the webhook defaults the deployment decision fixed."""

from __future__ import annotations

import pytest

from alert_bot.config import ConfigError, load_settings


def test_webhook_defaults_are_the_deployment_values(env: dict[str, str]) -> None:
    """PLAN.md §9.1: nginx is local and the legacy bot holds 3000."""
    settings = load_settings(env)

    assert settings.webhook.host == "127.0.0.1"
    assert settings.webhook.port == 3001
    assert settings.webhook.path == "/webhook-v2"


def test_webhook_path_is_configurable(env: dict[str, str]) -> None:
    env["WEBHOOK_PATH"] = "hook/other"

    assert load_settings(env).webhook.path == "/hook/other"


def test_missing_secret_fails_at_startup(env: dict[str, str]) -> None:
    del env["WEBHOOK_SECRET"]

    with pytest.raises(ConfigError, match="WEBHOOK_SECRET"):
        load_settings(env)


def test_unparseable_number_falls_back_to_the_default(env: dict[str, str]) -> None:
    """The legacy config.num contract: never raise, use the default."""
    env["WEBHOOK_PORT"] = "not-a-port"

    assert load_settings(env).webhook.port == 3001
