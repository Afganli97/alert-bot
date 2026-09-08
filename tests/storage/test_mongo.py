"""Index setup: the same keys and options the legacy bot creates, plus the new one."""

from __future__ import annotations

from alert_bot.storage.mongo import ensure_indexes
from tests.fakes import FakeDatabase, run


def _specifications(models: list) -> list[dict]:
    return [dict(model.document) for model in models]


def test_alert_indexes_match_the_legacy_ones() -> None:
    database = FakeDatabase()

    run(ensure_indexes(database))

    specs = _specifications(database["alerts"].last("create_indexes").args[0])
    keys = [spec["key"] for spec in specs]
    assert keys == [
        {"source": 1, "status": 1},
        {"ownerId": 1},
        {"ownerId": 1, "target.chain": 1, "target.address": 1},
    ]
    # Only the duplicate guard is unique, as in lib/db.js:30.
    assert [spec.get("unique", False) for spec in specs] == [False, False, True]


def test_alert_index_names_are_the_driver_defaults() -> None:
    """Re-creating an index the old bot made must be a no-op, not a name conflict."""
    database = FakeDatabase()

    run(ensure_indexes(database))

    specs = _specifications(database["alerts"].last("create_indexes").args[0])
    assert [spec["name"] for spec in specs] == [
        "source_1_status_1",
        "ownerId_1",
        "ownerId_1_target.chain_1_target.address_1",
    ]


def test_users_get_the_excluded_recipient_index() -> None:
    database = FakeDatabase()

    run(ensure_indexes(database))

    specs = _specifications(database["users"].last("create_indexes").args[0])
    assert [spec["key"] for spec in specs] == [{"status": 1, "deliverable": 1}]
    assert specs[0].get("unique", False) is False
