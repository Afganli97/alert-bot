#!/usr/bin/env python
"""Pre-register the LAPTOP token so the first move after its launch fires an alert.

The token is not listed yet, so it cannot be added through the bot: ``/add`` calls
DexScreener first (``handlers/sessionCommands.js:379``) and refuses an address with no
pairs. This script writes the same ``alerts`` document the bot would have written, so the
running Node.js checker picks it up on its next 20 s cycle without a restart.

How the alert then behaves (``checkers/dexPriceChecker.js``):

1. Every cycle reads ``{source: "dex", status: "active"}``, groups the addresses by chain
   and asks ``GET https://api.dexscreener.com/tokens/v1/<chain>/<addr>,<addr>,...``.
2. While LAPTOP has no pair the response contains nothing for it, the alert is skipped and
   the document is left untouched — no error, no cost beyond one address in the batch.
3. The first cycle after the token starts trading finds a pair and, because
   ``condition.baselinePrice`` is ``null``, only *anchors*: it stores that first price and
   sends nothing (``conditionEvaluator.js:25``).
4. The next cycle whose price differs from that anchor by at least ``changePercent``
   sends the alert and re-anchors. With the default ``--percent 1`` that is the first
   meaningful move after launch, which is the point of registering early.

**Address casing matters.** ``fetchBatchPrices`` keys its price map on
``baseToken.address.toLowerCase()`` but looks it up with the address exactly as stored
(``dexPriceChecker.js:62`` vs ``:184``), so an EVM address stored in checksum case — the
form every explorer copies — never matches and the alert never fires. That is the bug
recorded as PLAN.md §6.4. This script therefore stores the address lowercased, which is
what the live bot needs to see; the given checksummed form is only echoed back in the
report. Nothing else in the document differs from an ``/add`` insert.

Usage::

    .venv/bin/python scripts/laptop-add.py --owner 123456789
    .venv/bin/python scripts/laptop-add.py --owner 123456789 --percent 10 --dry-run
    .venv/bin/python scripts/laptop-add.py --all-users --env-file /etc/alert-bot.env

``MONGO_URI`` comes from the environment (or ``--env-file``); no secret is printed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:  # run as a script, not as an installed package
    sys.path.insert(0, str(REPO_ROOT))

from alert_bot.config import (  # noqa: E402  (path set up above)
    ConfigError,
    load_admin_chat_ids,
    load_limit_settings,
    load_mongo_settings,
)
from alert_bot.errors import DuplicateAlertError  # noqa: E402
from alert_bot.storage import Alert, AlertRepository, UserRepository, connect  # noqa: E402

#: The token to register. Supplied by the operator before launch; the symbol is a guess
#: and is cosmetic — the alert text uses the symbol DexScreener reports at fire time.
TOKEN_ADDRESS = "0xB095274743941e953c746F9C228DA9c18Bb6ec29"
TOKEN_CHAIN = "base"
TOKEN_NAME = "LAPTOP"

#: Threshold in percent. The bot's own default is 10; 1 is used here because the purpose
#: of pre-registering is to hear about the launch, not to filter noise.
DEFAULT_PERCENT = 1.0

EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def normalise_address(address: str) -> str:
    """Return the form the price checker can actually match, or raise ``ValueError``.

    EVM addresses are case-insensitive, so lowercase is canonical; see the module
    docstring for why storing anything else means an alert that never fires. Only EVM is
    accepted here — LAPTOP is on Base — so a base58 Solana address, which must *not* be
    lowercased, cannot reach this path by accident.
    """
    address = address.strip()
    if not EVM_ADDRESS.match(address):
        raise ValueError(f"not an EVM address: {address!r}")
    return address.lower()


def find_existing(alerts: Sequence[Alert], chain: str, address: str) -> Alert | None:
    """The owner's alert on this token, matched case-insensitively.

    Case-insensitively because the point is to detect a document added through the bot in
    checksum case: it is a duplicate for this script's purpose even though the unique
    index would happily accept a second, differently cased copy.
    """
    for alert in alerts:
        if alert.chain == chain and alert.address.lower() == address.lower():
            return alert
    return None


def parse_env_file(text: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines: comments, blanks and a leading ``export`` are ignored.

    Deliberately minimal — enough to read the deployment's ``EnvironmentFile``, with no
    interpolation and no dependency.
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def resolve_owners(args: argparse.Namespace, env: Mapping[str, str]) -> list[str]:
    """Owner chat ids from ``--owner``, else ``ADMIN_CHAT_IDS``. Empty means ``--all-users``."""
    if args.all_users:
        return []
    owners = [owner.strip() for owner in args.owner if owner.strip()]
    if owners:
        return list(dict.fromkeys(owners))
    return sorted(load_admin_chat_ids(env))


# ---------------------------------------------------------------------------
# Work
# ---------------------------------------------------------------------------


async def add_for_owner(
    repository: AlertRepository,
    users: UserRepository,
    owner_id: str,
    *,
    chain: str,
    address: str,
    name: str,
    percent: float,
    limit_for_tier: Any,
    force: bool,
    dry_run: bool,
) -> tuple[bool, str]:
    """Insert one alert. Returns ``(ok, line)`` where ``line`` is one report line."""
    existing = find_existing(await repository.list_for_owner(owner_id), chain, address)
    if existing is not None:
        if existing.address != address:
            return True, (
                f"{owner_id}: already tracked, but stored as {existing.address} — "
                "that casing never matches the price map, so it cannot fire (PLAN.md §6.4)"
            )
        return True, f"{owner_id}: already tracked at {existing.change_percent:g}%, unchanged"

    user = await users.get(owner_id)
    if user is None:
        return False, f"{owner_id}: no user document — the chat has never used the bot"
    if user.is_banned:
        return False, f"{owner_id}: user is blocked; the price loop would skip the alert"

    limit = limit_for_tier(user.subscription)
    count = await repository.count_for_owner(owner_id)
    if count >= limit and not force:
        return False, f"{owner_id}: at the {user.subscription} limit ({count}/{limit}); --force overrides"

    alert = Alert.new(owner_id, chain, address, name, percent)
    if dry_run:
        return True, f"{owner_id}: would insert {name} {chain}:{address} at {percent:g}% (dry run)"
    try:
        await repository.create(alert)
    except DuplicateAlertError:
        return True, f"{owner_id}: already tracked (inserted concurrently), unchanged"
    return True, f"{owner_id}: added {name} {chain}:{address} at {percent:g}%, baseline null"


async def probe_dexscreener(chain: str, address: str, base_url: str) -> str:
    """Ask the endpoint the cycle uses whether the token trades yet. Never fatal."""
    import httpx

    url = f"{base_url}/tokens/v1/{chain}/{address}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url)
    except Exception as exc:  # network is optional for this script
        return f"probe: request failed ({type(exc).__name__})"
    if response.status_code != 200:
        return f"probe: HTTP {response.status_code} — treated as 'no data' by the cycle"
    payload = response.json()
    pairs = payload if isinstance(payload, list) else payload.get("pairs") or []
    if not pairs:
        return "probe: no pairs yet — the alert waits, as intended"
    best = max(pairs, key=lambda pair: float((pair.get("liquidity") or {}).get("usd") or 0))
    return (
        f"probe: {len(pairs)} pair(s) already live, "
        f"{best.get('baseToken', {}).get('symbol', '?')} at ${best.get('priceUsd', '?')}"
    )


async def run(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    address = normalise_address(args.address)
    chain = args.chain.strip().lower()
    owners = resolve_owners(args, env)
    if not owners and not args.all_users:
        print("No owner: pass --owner <chat id>, --all-users, or set ADMIN_CHAT_IDS.")
        return 2

    lines: list[str] = []
    if args.probe:
        lines.append(await probe_dexscreener(chain, address, args.dex_base_url))

    limits = load_limit_settings(env)
    storage = await connect(load_mongo_settings(env))
    try:
        alerts = AlertRepository(storage.alerts)
        users = UserRepository(
            storage.users, excluded_cache_ttl_ms=limits.blocked_users_cache_ttl_ms
        )
        if args.all_users:
            owners = [user.chat_id async for user in users.iter_reachable()]
            lines.append(f"owners: {len(owners)} reachable user(s)")

        failures = 0
        for owner_id in owners:
            ok, line = await add_for_owner(
                alerts,
                users,
                owner_id,
                chain=chain,
                address=address,
                name=args.name,
                percent=args.percent,
                limit_for_tier=limits.subscription_limit,
                force=args.force,
                dry_run=args.dry_run,
            )
            failures += 0 if ok else 1
            lines.append(line)
    finally:
        await storage.close()

    for line in lines:
        print(line)
    if args.address != address:
        print(f"note: stored lowercased ({args.address} -> {address}), see PLAN.md §6.4")
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="laptop-add",
        description="Register the LAPTOP token before it launches so the first move alerts.",
    )
    parser.add_argument(
        "--owner",
        action="append",
        default=[],
        metavar="CHAT_ID",
        help="owner chat id; repeatable. Default: ADMIN_CHAT_IDS.",
    )
    parser.add_argument(
        "--all-users", action="store_true", help="add for every reachable user instead"
    )
    parser.add_argument("--address", default=TOKEN_ADDRESS, help="token contract address")
    parser.add_argument("--chain", default=TOKEN_CHAIN, help="DexScreener chain id")
    parser.add_argument("--name", default=TOKEN_NAME, help="label shown in /list")
    parser.add_argument(
        "--percent",
        type=float,
        default=DEFAULT_PERCENT,
        help=f"alert threshold in percent (default {DEFAULT_PERCENT:g}; the bot's own default is 10)",
    )
    parser.add_argument(
        "--force", action="store_true", help="insert past the subscription limit"
    )
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument(
        "--probe", action="store_true", help="ask DexScreener whether the token trades yet"
    )
    parser.add_argument(
        "--dex-base-url", default="https://api.dexscreener.com", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        help="read KEY=VALUE lines from PATH first; existing variables win",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.percent <= 0 or args.percent > 1000:
        print("--percent must be greater than 0 and at most 1000 (the bot's own range).")
        return 2
    if args.env_file:
        for key, value in parse_env_file(Path(args.env_file).read_text(encoding="utf-8")).items():
            os.environ.setdefault(key, value)
    try:
        return asyncio.run(run(args, os.environ))
    except (ConfigError, ValueError) as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
