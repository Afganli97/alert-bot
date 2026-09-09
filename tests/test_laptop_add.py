"""``scripts/laptop-add.py``: what it writes, and what it refuses to write.

The document it inserts is the contract — the running Node.js bot reads it — so the tests
assert the insert document field by field, and pin the lowercasing that decides whether
the alert can ever fire (PLAN.md §6.4).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from alert_bot.config import load_limit_settings
from alert_bot.storage.alerts import AlertRepository
from alert_bot.storage.models import Alert
from alert_bot.storage.users import UserRepository
from tests.fakes import FakeCollection, run

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "laptop-add.py"


def _load_script() -> Any:
    """Import the script by path: its name has a hyphen, so it is not importable."""
    spec = importlib.util.spec_from_file_location("laptop_add", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


laptop_add = _load_script()

CHECKSUMMED = "0xB095274743941e953c746F9C228DA9c18Bb6ec29"
LOWERCASED = CHECKSUMMED.lower()


def _user_document(**overrides: Any) -> dict[str, Any]:
    document = {"_id": "42", "status": "active", "subscription": "basic"}
    document.update(overrides)
    return document


def _add(
    alerts: FakeCollection,
    users: FakeCollection,
    *,
    address: str = LOWERCASED,
    percent: float = 1.0,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[bool, str]:
    limits = load_limit_settings({})
    return run(
        laptop_add.add_for_owner(
            AlertRepository(alerts),
            UserRepository(users, excluded_cache_ttl_ms=60000),
            "42",
            chain="base",
            address=address,
            name="LAPTOP",
            percent=percent,
            limit_for_tier=limits.subscription_limit,
            force=force,
            dry_run=dry_run,
        )
    )


# -- address handling -------------------------------------------------------


def test_checksummed_address_is_stored_lowercased() -> None:
    assert laptop_add.normalise_address(CHECKSUMMED) == LOWERCASED


def test_surrounding_whitespace_is_trimmed() -> None:
    assert laptop_add.normalise_address(f"  {CHECKSUMMED}\n") == LOWERCASED


@pytest.mark.parametrize("address", ["", "0x123", "not-an-address", LOWERCASED + "ff"])
def test_a_non_evm_address_is_rejected(address: str) -> None:
    with pytest.raises(ValueError):
        laptop_add.normalise_address(address)


# -- the inserted document --------------------------------------------------


def test_insert_matches_the_document_the_bot_would_have_written() -> None:
    alerts, users = FakeCollection(), FakeCollection()
    users.find_one_result = _user_document()

    ok, line = _add(alerts, users)

    document = alerts.last("insert_one").args[0]
    assert document["ownerId"] == "42"
    assert document["source"] == "dex"
    assert document["target"] == {"chain": "base", "address": LOWERCASED}
    assert document["condition"] == {
        "kind": "percent_change",
        "changePercent": 1.0,
        "baselinePrice": None,
    }
    assert document["repeat"] == "always"
    assert document["status"] == "active"
    assert document["name"] == "LAPTOP"
    assert ok and "added" in line


def test_baseline_stays_null_so_the_first_sighting_only_anchors() -> None:
    alerts, users = FakeCollection(), FakeCollection()
    users.find_one_result = _user_document()

    _add(alerts, users)

    assert alerts.last("insert_one").args[0]["condition"]["baselinePrice"] is None


def test_dry_run_writes_nothing() -> None:
    alerts, users = FakeCollection(), FakeCollection()
    users.find_one_result = _user_document()

    ok, line = _add(alerts, users, dry_run=True)

    assert ok and "would insert" in line
    assert "insert_one" not in alerts.method_names()


# -- refusals ---------------------------------------------------------------


def test_an_existing_alert_is_left_alone() -> None:
    alerts, users = FakeCollection(), FakeCollection()
    alerts.documents = [
        {
            "_id": "1",
            "ownerId": "42",
            "target": {"chain": "base", "address": LOWERCASED},
            "condition": {"kind": "percent_change", "changePercent": 10.0, "baselinePrice": None},
            "name": "LAPTOP",
        }
    ]

    ok, line = _add(alerts, users)

    assert ok and "already tracked" in line
    assert "insert_one" not in alerts.method_names()


def test_a_checksummed_duplicate_is_reported_as_unable_to_fire() -> None:
    alerts, users = FakeCollection(), FakeCollection()
    alerts.documents = [
        {
            "_id": "1",
            "ownerId": "42",
            "target": {"chain": "base", "address": CHECKSUMMED},
            "condition": {"kind": "percent_change", "changePercent": 10.0, "baselinePrice": None},
            "name": "LAPTOP",
        }
    ]

    ok, line = _add(alerts, users)

    assert ok and "cannot fire" in line
    assert "insert_one" not in alerts.method_names()


def test_an_unknown_chat_is_refused() -> None:
    alerts, users = FakeCollection(), FakeCollection()
    users.find_one_result = None

    ok, line = _add(alerts, users)

    assert not ok and "no user document" in line


def test_a_blocked_user_is_refused() -> None:
    alerts, users = FakeCollection(), FakeCollection()
    users.find_one_result = _user_document(status="blocked")

    ok, line = _add(alerts, users)

    assert not ok and "blocked" in line


def test_the_subscription_limit_is_enforced_unless_forced() -> None:
    alerts, users = FakeCollection(), FakeCollection()
    users.find_one_result = _user_document()
    alerts.count_result = 5  # SUBSCRIPTION_LIMIT_BASIC

    ok, line = _add(alerts, users)
    assert not ok and "limit" in line
    assert "insert_one" not in alerts.method_names()

    ok, _ = _add(alerts, users, force=True)
    assert ok and "insert_one" in alerts.method_names()


# -- helpers ----------------------------------------------------------------


def test_find_existing_ignores_case_but_not_chain() -> None:
    alert = Alert.new("42", "base", CHECKSUMMED, "LAPTOP", 1.0)

    assert laptop_add.find_existing([alert], "base", LOWERCASED) is alert
    assert laptop_add.find_existing([alert], "ethereum", LOWERCASED) is None


def test_env_file_parsing_skips_comments_and_strips_quotes() -> None:
    values = laptop_add.parse_env_file(
        '# comment\n\nexport MONGO_URI="mongodb://host/db"\nADMIN_CHAT_IDS=42,43\nbroken\n'
    )

    assert values == {"MONGO_URI": "mongodb://host/db", "ADMIN_CHAT_IDS": "42,43"}


def test_owners_fall_back_to_the_admin_ids() -> None:
    args = laptop_add.build_parser().parse_args([])

    assert laptop_add.resolve_owners(args, {"ADMIN_CHAT_IDS": "42, 43"}) == ["42", "43"]


def test_explicit_owners_win_and_are_deduplicated() -> None:
    args = laptop_add.build_parser().parse_args(["--owner", "7", "--owner", "7", "--owner", "8"])

    assert laptop_add.resolve_owners(args, {"ADMIN_CHAT_IDS": "42"}) == ["7", "8"]


def test_all_users_resolves_to_no_explicit_owner() -> None:
    args = laptop_add.build_parser().parse_args(["--owner", "7", "--all-users"])

    assert laptop_add.resolve_owners(args, {"ADMIN_CHAT_IDS": "42"}) == []


def test_the_defaults_are_the_laptop_token() -> None:
    args = laptop_add.build_parser().parse_args([])

    assert args.address == CHECKSUMMED
    assert args.chain == "base"
    assert args.name == "LAPTOP"
    assert args.percent == 1.0


def test_an_out_of_range_percent_exits_before_touching_mongo() -> None:
    assert laptop_add.main(["--owner", "42", "--percent", "0"]) == 2
    assert laptop_add.main(["--owner", "42", "--percent", "1001"]) == 2
