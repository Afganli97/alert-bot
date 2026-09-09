"""Configuration.

Every environment variable the bot reads is declared here and nowhere else. No other
module may touch :data:`os.environ`; they call :func:`get_settings` instead. Values are
parsed once, on first call, into frozen dataclasses.

Secrets (``TELEGRAM_TOKEN``, ``MONGO_URI``, ``WEBHOOK_SECRET``) come from the environment
only — never from a literal, a file in the repository, or the database — and are never
logged. See ``.env.example`` for the full list with defaults.

Numeric parsing reproduces the legacy ``config.num(name, fallback, min)`` contract: a
value that is missing, unparseable, or below the minimum falls back to the default
silently. One deliberate difference from JavaScript: ``parseInt("20abc")`` yields ``20``
there, while here a value that is not a clean integer falls back to the default.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Mapping

__all__ = [
    "ConfigError",
    "Settings",
    "TelegramSettings",
    "MongoSettings",
    "WebhookSettings",
    "DexSettings",
    "HttpSettings",
    "LimitSettings",
    "RuntimeSettings",
    "get_settings",
    "load_settings",
]

logger = logging.getLogger(__name__)

Env = Mapping[str, str]

#: Delivery modes. ``webhook`` is what production uses; ``polling`` is for local work
#: without a public URL.
BOT_MODE_WEBHOOK = "webhook"
BOT_MODE_POLLING = "polling"
BOT_MODES = (BOT_MODE_WEBHOOK, BOT_MODE_POLLING)

#: Accepted MongoDB URI schemes, as validated by the legacy ``lib/db.js``.
MONGO_URI_SCHEMES = ("mongodb://", "mongodb+srv://")

SUBSCRIPTION_TIERS = ("basic", "pro", "premium")


class ConfigError(RuntimeError):
    """Raised when the environment is missing or malformed.

    Always names the offending variable so the failure is actionable from a log line.
    """


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _str_env(env: Env, name: str, default: str = "") -> str:
    """Return a trimmed string variable, or ``default`` when unset or blank."""
    value = env.get(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _required_env(env: Env, name: str) -> str:
    """Return a mandatory variable, or raise :class:`ConfigError` naming it."""
    value = _str_env(env, name)
    if not value:
        raise ConfigError(f"{name} is required but not set")
    return value


def _int_env(env: Env, name: str, fallback: int, minimum: int = 0) -> int:
    """Return an integer variable, falling back when unparseable or below ``minimum``.

    Ports the legacy ``config.num`` semantics: invalid input never raises, it is replaced
    by the default and reported at WARNING level.
    """
    raw = _str_env(env, name)
    if not raw:
        return fallback
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer; using default %d", name, raw, fallback)
        return fallback
    if value < minimum:
        logger.warning(
            "%s=%d is below the minimum %d; using default %d", name, value, minimum, fallback
        )
        return fallback
    return value


def _csv_env(env: Env, name: str) -> tuple[str, ...]:
    """Return a comma-separated variable as a tuple, blanks and duplicates removed."""
    raw = _str_env(env, name)
    if not raw:
        return ()
    seen: dict[str, None] = {}
    for part in raw.split(","):
        part = part.strip()
        if part:
            seen.setdefault(part, None)
    return tuple(seen)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TelegramSettings:
    """Bot API credentials and outbound send-queue pacing."""

    token: str
    api_base_url: str
    #: Chat ids allowed to run ``/admin``. Parsed once, unlike the legacy bot which
    #: re-split the variable on every ``isAdmin()`` call.
    admin_chat_ids: frozenset[str]
    #: Delay between queued sends. The legacy bot parsed this variable and then ignored
    #: it, hardcoding 35 ms; here it is honoured, with 35 ms as the default.
    queue_delay_ms: int

    def is_admin(self, chat_id: str | int) -> bool:
        return str(chat_id) in self.admin_chat_ids


@dataclass(frozen=True, slots=True)
class MongoSettings:
    """Connection settings for the database shared with the legacy bot."""

    uri: str
    #: Overrides the database name embedded in the URI. Empty means "use the URI's".
    database: str
    max_pool_size: int
    min_pool_size: int
    server_selection_timeout_ms: int
    socket_timeout_ms: int
    connect_timeout_ms: int


@dataclass(frozen=True, slots=True)
class WebhookSettings:
    """Inbound update delivery."""

    mode: str
    #: Public URL Telegram calls. Required in webhook mode.
    url: str
    host: str
    port: int
    path: str
    #: Sent to Telegram with ``setWebhook`` *and* checked on every inbound request. The
    #: legacy bot only did the second half, so no update could ever pass the check.
    secret: str

    @property
    def uses_webhook(self) -> bool:
        return self.mode == BOT_MODE_WEBHOOK


@dataclass(frozen=True, slots=True)
class DexSettings:
    """DexScreener polling."""

    base_url: str
    cycle_interval_ms: int
    batch_size: int
    batch_delay_ms: int


@dataclass(frozen=True, slots=True)
class HttpSettings:
    """Shared outbound HTTP policy (see ``services/http.py``)."""

    timeout_ms: int
    retry_attempts: int
    retry_backoff_ms: int


@dataclass(frozen=True, slots=True)
class LimitSettings:
    """Per-user and per-operation ceilings."""

    subscription: Mapping[str, int]
    rate_limit_commands: int
    rate_limit_window_ms: int
    session_ttl_ms: int
    session_cleanup_interval_ms: int
    blocked_users_cache_ttl_ms: int
    broadcast_max_users: int

    def subscription_limit(self, tier: str | None) -> int:
        """Return the token limit for a tier, defaulting to ``basic`` for unknown tiers."""
        return self.subscription.get(tier or "", self.subscription["basic"])


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Process-level behaviour."""

    log_level: str
    #: How long shutdown waits for the send queue to drain before exiting anyway.
    shutdown_drain_timeout_ms: int
    #: Optional allow-list of chain ids. Empty means "accept whatever DexScreener
    #: reports", which is the legacy behaviour.
    enabled_chains: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Settings:
    """The whole configuration, assembled by :func:`load_settings`."""

    telegram: TelegramSettings
    mongo: MongoSettings
    webhook: WebhookSettings
    dex: DexSettings
    http: HttpSettings
    limits: LimitSettings
    runtime: RuntimeSettings
    env_name: str = field(default="production")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_settings(env: Env | None = None) -> Settings:
    """Parse and validate the environment.

    Raises :class:`ConfigError` — never a partially built object — so a misconfigured
    process dies at startup with a readable message instead of inside a handler.
    """
    env = os.environ if env is None else env

    mode = _str_env(env, "BOT_MODE", BOT_MODE_WEBHOOK).lower()
    if mode not in BOT_MODES:
        raise ConfigError(f"BOT_MODE must be one of {', '.join(BOT_MODES)}, got {mode!r}")

    mongo_uri = _required_env(env, "MONGO_URI")
    if not mongo_uri.startswith(MONGO_URI_SCHEMES):
        raise ConfigError(
            "MONGO_URI must start with " + " or ".join(MONGO_URI_SCHEMES)
        )

    webhook_path = _str_env(env, "WEBHOOK_PATH", "/webhook-v2")
    if not webhook_path.startswith("/"):
        webhook_path = "/" + webhook_path

    webhook = WebhookSettings(
        mode=mode,
        url=_str_env(env, "WEBHOOK_URL"),
        # Defaults are the deployment values of PLAN.md §9.1: nginx on the same host
        # terminates TLS, and the legacy bot holds 3000.
        host=_str_env(env, "WEBHOOK_HOST", "127.0.0.1"),
        port=_int_env(env, "WEBHOOK_PORT", 3001, 1),
        path=webhook_path,
        secret=_str_env(env, "WEBHOOK_SECRET"),
    )
    if webhook.uses_webhook:
        for name, value in (("WEBHOOK_URL", webhook.url), ("WEBHOOK_SECRET", webhook.secret)):
            if not value:
                raise ConfigError(f"{name} is required when BOT_MODE={BOT_MODE_WEBHOOK}")

    settings = Settings(
        telegram=TelegramSettings(
            token=_required_env(env, "TELEGRAM_TOKEN"),
            api_base_url=_str_env(env, "TELEGRAM_API_BASE_URL", "https://api.telegram.org"),
            admin_chat_ids=frozenset(_csv_env(env, "ADMIN_CHAT_IDS")),
            queue_delay_ms=_int_env(env, "TG_QUEUE_DELAY_MS", 35, 1),
        ),
        mongo=MongoSettings(
            uri=mongo_uri,
            database=_str_env(env, "MONGO_DB_NAME"),
            max_pool_size=_int_env(env, "MONGO_MAX_POOL_SIZE", 10, 1),
            min_pool_size=_int_env(env, "MONGO_MIN_POOL_SIZE", 1, 0),
            server_selection_timeout_ms=_int_env(env, "MONGO_SERVER_SELECTION_TIMEOUT_MS", 5000, 1),
            socket_timeout_ms=_int_env(env, "MONGO_SOCKET_TIMEOUT_MS", 45000, 1),
            connect_timeout_ms=_int_env(env, "MONGO_CONNECT_TIMEOUT_MS", 10000, 1),
        ),
        webhook=webhook,
        dex=DexSettings(
            base_url=_str_env(env, "DEXSCREENER_BASE_URL", "https://api.dexscreener.com"),
            cycle_interval_ms=_int_env(env, "DEX_CYCLE_INTERVAL_MS", 20000, 1),
            batch_size=_int_env(env, "DEX_BATCH_SIZE", 30, 1),
            batch_delay_ms=_int_env(env, "DEX_BATCH_DELAY_MS", 1000, 0),
        ),
        http=HttpSettings(
            timeout_ms=_int_env(env, "HTTP_TIMEOUT_MS", 15000, 1),
            retry_attempts=_int_env(env, "HTTP_RETRY_ATTEMPTS", 3, 1),
            retry_backoff_ms=_int_env(env, "HTTP_RETRY_BACKOFF_MS", 2000, 0),
        ),
        limits=LimitSettings(
            subscription={
                "basic": _int_env(env, "SUBSCRIPTION_LIMIT_BASIC", 5, 1),
                "pro": _int_env(env, "SUBSCRIPTION_LIMIT_PRO", 15, 1),
                "premium": _int_env(env, "SUBSCRIPTION_LIMIT_PREMIUM", 50, 1),
            },
            rate_limit_commands=_int_env(env, "RATE_LIMIT_COMMANDS", 10, 1),
            rate_limit_window_ms=_int_env(env, "RATE_LIMIT_WINDOW_MS", 60000, 1),
            session_ttl_ms=_int_env(env, "SESSION_TTL_MS", 1800000, 1),
            session_cleanup_interval_ms=_int_env(env, "SESSION_CLEANUP_INTERVAL_MS", 300000, 1),
            blocked_users_cache_ttl_ms=_int_env(env, "BLOCKED_USERS_CACHE_TTL_MS", 300000, 60000),
            broadcast_max_users=_int_env(env, "BROADCAST_MAX_USERS", 1000, 1),
        ),
        runtime=RuntimeSettings(
            log_level=_str_env(env, "LOG_LEVEL", "INFO").upper(),
            shutdown_drain_timeout_ms=_int_env(env, "SHUTDOWN_DRAIN_TIMEOUT_MS", 5000, 0),
            enabled_chains=_csv_env(env, "ENABLED_CHAINS"),
        ),
        env_name=_str_env(env, "ENV_NAME", "production"),
    )
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, parsing the environment on first call."""
    return load_settings()
