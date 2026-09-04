"""aiohttp application hosting the aiogram webhook handler.

Registers the webhook with Telegram at startup passing ``secret_token``, and verifies the
``x-telegram-bot-api-secret-token`` header on every request. The legacy bot did only the
second half, so as written no update could ever pass the check (PLAN.md §6.1).

Binds WEBHOOK_HOST:WEBHOOK_PORT and serves WEBHOOK_PATH. TLS is terminated upstream.
"""
