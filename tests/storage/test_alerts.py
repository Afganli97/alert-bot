"""The ``alerts`` queries, asserted document by document."""

from __future__ import annotations

import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from alert_bot.errors import DuplicateAlertError
from alert_bot.storage.alerts import AlertRepository
from alert_bot.storage.models import Alert
from tests.fakes import FakeCollection, FakeDeleteResult, FakeUpdateResult, run

ALERT_ID = ObjectId()


def _repository(collection: FakeCollection | None = None) -> tuple[AlertRepository, FakeCollection]:
    collection = collection or FakeCollection()
    return AlertRepository(collection), collection


def _document(**overrides) -> dict:
    document = {
        "_id": ALERT_ID,
        "ownerId": "42",
        "source": "dex",
        "target": {"chain": "ethereum", "address": "0xabc"},
        "condition": {"kind": "percent_change", "changePercent": 10.0, "baselinePrice": None},
        "repeat": "always",
        "status": "active",
        "name": "TKN",
    }
    document.update(overrides)
    return document


# -- the price loop ---------------------------------------------------------


def test_active_dex_alerts_is_the_legacy_cycle_query() -> None:
    repository, collection = _repository()
    collection.documents = [_document()]

    alerts = run(repository.active_dex_alerts())

    assert collection.last("find").filter == {"source": "dex", "status": "active"}
    assert [alert.id for alert in alerts] == [ALERT_ID]
    assert alerts[0].chain == "ethereum"


def test_update_baseline_touches_only_the_anchor() -> None:
    repository, collection = _repository()

    assert run(repository.update_baseline(ALERT_ID, 1.5)) is True

    call = collection.last("update_one")
    assert call.filter == {"_id": ALERT_ID}
    assert call.update == {"$set": {"condition.baselinePrice": 1.5}}


# -- per user ---------------------------------------------------------------


def test_list_for_owner_filters_by_source() -> None:
    repository, collection = _repository()
    collection.documents = [_document()]

    alerts = run(repository.list_for_owner("42"))

    assert collection.last("find").filter == {"ownerId": "42", "source": "dex"}
    assert len(alerts) == 1


def test_count_for_owner_counts_every_source() -> None:
    """The subscription limit counts all sources, as handlers/alertCommands.js:78 does."""
    repository, collection = _repository()

    run(repository.count_for_owner("42"))

    assert collection.last("count_documents").filter == {"ownerId": "42"}


def test_create_inserts_the_document_and_returns_the_id() -> None:
    repository, collection = _repository()
    alert = Alert.new("42", "ethereum", "0xabc", "TKN", 10)

    created = run(repository.create(alert))

    assert created.id == collection.inserted_id
    assert collection.last("insert_one").args[0]["ownerId"] == "42"


def test_duplicate_key_becomes_a_domain_error() -> None:
    """PLAN.md §6.5: the caller must not have to know about driver code 11000."""
    repository, collection = _repository()
    collection.insert_error = DuplicateKeyError("E11000 duplicate key error")
    alert = Alert.new("42", "ethereum", "0xabc", "TKN", 10)

    with pytest.raises(DuplicateAlertError) as excinfo:
        run(repository.create(alert))

    assert excinfo.value.owner_id == "42"
    assert excinfo.value.address == "0xabc"


def test_delete_is_scoped_to_the_owner() -> None:
    repository, collection = _repository()

    assert run(repository.delete(ALERT_ID, "42")) is True
    assert collection.last("delete_one").filter == {"_id": ALERT_ID, "ownerId": "42"}


def test_delete_reports_a_miss() -> None:
    repository, collection = _repository()
    collection.delete_result = FakeDeleteResult(deleted_count=0)

    assert run(repository.delete(ALERT_ID, "42")) is False


def test_delete_for_owner_removes_every_alert() -> None:
    repository, collection = _repository()
    collection.delete_result = FakeDeleteResult(deleted_count=3)

    assert run(repository.delete_for_owner("42")) == 3
    assert collection.last("delete_many").filter == {"ownerId": "42"}


def test_set_threshold_writes_a_float() -> None:
    repository, collection = _repository()

    run(repository.set_threshold(ALERT_ID, "42", 7))

    call = collection.last("update_one")
    assert call.filter == {"_id": ALERT_ID, "ownerId": "42"}
    assert call.update == {"$set": {"condition.changePercent": 7.0}}


def test_set_threshold_for_owner_updates_the_whole_list() -> None:
    repository, collection = _repository()
    collection.update_result = FakeUpdateResult(matched_count=4, modified_count=4)

    assert run(repository.set_threshold_for_owner("42", 12.5)) == 4
    assert collection.last("update_many").filter == {"ownerId": "42"}


def test_reset_baselines_for_owner_nulls_the_anchor() -> None:
    repository, collection = _repository()

    run(repository.reset_baselines_for_owner("42"))

    call = collection.last("update_many")
    assert call.filter == {"ownerId": "42"}
    assert call.update == {"$set": {"condition.baselinePrice": None}}


def test_reset_all_baselines_matches_every_alert() -> None:
    repository, collection = _repository()

    run(repository.reset_all_baselines())

    assert collection.last("update_many").filter == {}
