"""The ``users`` queries, asserted document by document.

Shapes are the contract here: the legacy bot reads and writes the same collection during
the dual run, so a filter that differs is a defect even when the result looks right.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from alert_bot.errors import InvalidChatIdError
from alert_bot.storage.users import UserRepository, excluded_filter, reachable_filter
from tests.fakes import FakeClock, FakeCollection, FakeUpdateResult, run

TTL_MS = 300_000  # the legacy BLOCKED_USERS_CACHE_TTL_MS default


def _repository(
    collection: FakeCollection | None = None, clock: FakeClock | None = None
) -> tuple[UserRepository, FakeCollection, FakeClock]:
    collection = collection or FakeCollection()
    clock = clock or FakeClock()
    repository = UserRepository(collection, excluded_cache_ttl_ms=TTL_MS, clock=clock)
    return repository, collection, clock


# -- ensure -----------------------------------------------------------------


def test_ensure_never_lists_username_in_both_operators() -> None:
    """PLAN.md §6.2: the legacy version raises ConflictingUpdateOperators."""
    repository, collection, _ = _repository()
    collection.find_one_and_update_result = {"_id": "42", "username": "alice"}

    run(repository.ensure("42", "alice"))

    call = collection.last("find_one_and_update")
    assert call.filter == {"_id": "42"}
    assert set(call.update["$setOnInsert"]) == {"createdAt", "status", "subscription"}
    assert call.update["$set"]["username"] == "alice"
    assert call.update["$currentDate"] == {"lastActivityAt": True}
    assert call.kwargs["upsert"] is True


def test_ensure_restores_deliverability_but_not_a_ban() -> None:
    repository, collection, _ = _repository()
    collection.find_one_and_update_result = {"_id": "42", "status": "blocked"}

    user = run(repository.ensure("42"))

    update = collection.last("find_one_and_update").update
    assert update["$set"]["deliverable"] is True
    assert "status" not in update["$set"]  # only /admin unblock_user clears a ban
    assert update["$setOnInsert"]["status"] == "active"
    assert user.is_banned is True


def test_ensure_accepts_an_integer_chat_id_and_stores_a_string() -> None:
    repository, collection, _ = _repository()

    run(repository.ensure(42))

    assert collection.last("find_one_and_update").filter == {"_id": "42"}


def test_ensure_rejects_a_blank_chat_id() -> None:
    repository, collection, _ = _repository()

    with pytest.raises(InvalidChatIdError):
        run(repository.ensure("   "))

    assert collection.calls == []


def test_ensure_drops_an_over_long_username() -> None:
    repository, collection, _ = _repository()

    run(repository.ensure("42", "u" * 101))

    assert collection.last("find_one_and_update").update["$set"]["username"] is None


# -- reads ------------------------------------------------------------------


def test_get_returns_none_when_absent() -> None:
    repository, collection, _ = _repository()
    collection.find_one_result = None

    assert run(repository.get("42")) is None
    assert collection.last("find_one").filter == {"_id": "42"}


def test_broadcast_audience_uses_the_read_compatible_filter() -> None:
    repository, collection, _ = _repository()
    collection.documents = [{"_id": "42"}, {"_id": "43", "deliverable": True}]

    async def collect() -> list[str]:
        return [user.chat_id async for user in repository.iter_reachable()]

    assert run(collect()) == ["42", "43"]
    assert collection.last("find").filter == {
        "status": {"$ne": "blocked"},
        "deliverable": {"$ne": False},
    }


def test_count_active_since_keeps_the_activity_window() -> None:
    repository, collection, _ = _repository()
    moment = datetime(2025, 1, 1, tzinfo=timezone.utc)

    run(repository.count_active_since(moment))

    assert collection.last("count_documents").filter == {
        "lastActivityAt": {"$gte": moment},
        **reachable_filter(),
    }


# -- the excluded set and its cache ------------------------------------------


def test_excluded_ids_query_covers_both_schema_versions() -> None:
    repository, collection, _ = _repository()
    collection.documents = [{"_id": "7"}, {"_id": 8}]

    ids = run(repository.excluded_recipient_ids())

    assert ids == frozenset({"7", "8"})
    call = collection.last("find")
    assert call.filter == excluded_filter()
    assert call.args[1] == {"_id": 1}


def test_excluded_ids_are_cached_until_the_ttl_expires() -> None:
    repository, collection, clock = _repository()
    collection.documents = [{"_id": "7"}]

    run(repository.excluded_recipient_ids())
    clock.advance(TTL_MS / 1000 - 1)
    run(repository.excluded_recipient_ids())

    assert collection.method_names().count("find") == 1

    clock.advance(2)
    run(repository.excluded_recipient_ids())
    assert collection.method_names().count("find") == 2


def test_banning_invalidates_the_cache() -> None:
    repository, collection, _ = _repository()
    run(repository.excluded_recipient_ids())

    run(repository.ban("42"))
    run(repository.excluded_recipient_ids())

    assert collection.method_names().count("find") == 2
    assert collection.last("update_one").update == {"$set": {"status": "blocked"}}


def test_marking_undeliverable_keeps_the_cache_as_the_legacy_bot_does() -> None:
    """Ported staleness: the 403 path never invalidated (lib/telegramQueue.js:85)."""
    repository, collection, _ = _repository()
    run(repository.excluded_recipient_ids())

    run(repository.mark_undeliverable("42"))
    run(repository.excluded_recipient_ids())

    assert collection.method_names().count("find") == 1
    assert collection.last("update_one").update == {"$set": {"deliverable": False}}


# -- writes -----------------------------------------------------------------


def test_unban_clears_only_the_status() -> None:
    repository, collection, _ = _repository()

    assert run(repository.unban("42")) is True
    assert collection.last("update_one").update == {"$set": {"status": "active"}}


def test_set_subscription_writes_the_tier() -> None:
    repository, collection, _ = _repository()

    run(repository.set_subscription("42", "pro"))

    assert collection.last("update_one").update == {"$set": {"subscription": "pro"}}


def test_write_to_an_unknown_user_reports_no_match() -> None:
    repository, collection, _ = _repository()
    collection.update_result = FakeUpdateResult(matched_count=0, modified_count=0)

    assert run(repository.ban("999")) is False
    assert run(repository.mark_undeliverable("999")) is False


def test_delete_removes_the_document() -> None:
    repository, collection, _ = _repository()

    assert run(repository.delete("42")) is True
    assert collection.last("delete_one").filter == {"_id": "42"}
