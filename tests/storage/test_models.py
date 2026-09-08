"""Document mapping, including the read compatibility of PLAN.md §9.2."""

from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId

from alert_bot.storage.models import Alert, User


# -- users ------------------------------------------------------------------


def test_legacy_document_without_deliverable_reads_as_reachable() -> None:
    user = User.from_document({"_id": "42", "username": "alice", "status": "active"})

    assert user.chat_id == "42"
    assert user.deliverable is True
    assert user.is_banned is False
    assert user.is_reachable is True


def test_legacy_blocked_document_reads_as_banned_and_undeliverable() -> None:
    """The legacy field cannot say which it meant, so it keeps excluding either way."""
    user = User.from_document({"_id": "42", "status": "blocked"})

    assert user.is_banned is True
    assert user.deliverable is False
    assert user.is_reachable is False


def test_stored_deliverable_wins_over_the_legacy_reading() -> None:
    user = User.from_document({"_id": "42", "status": "active", "deliverable": False})

    assert user.is_banned is False
    assert user.deliverable is False
    assert user.is_reachable is False


def test_user_defaults_for_a_sparse_document() -> None:
    user = User.from_document({"_id": 42})

    assert user.chat_id == "42"  # the id is a string in the schema, always
    assert user.username is None
    assert user.status == "active"
    assert user.subscription == "basic"


# -- alerts -----------------------------------------------------------------


def test_new_alert_normalises_chain_name_and_percent() -> None:
    alert = Alert.new(
        owner_id="42",
        chain="Ethereum",
        address="0xAbCdEf0123456789012345678901234567890123",
        name="X" * 40,
        change_percent=10,
    )

    assert alert.chain == "ethereum"
    assert alert.address == "0xAbCdEf0123456789012345678901234567890123"  # case kept
    assert alert.name == "X" * 30
    assert isinstance(alert.change_percent, float)
    assert alert.created_at is not None


def test_insert_document_matches_the_legacy_shape() -> None:
    alert = Alert.new("42", "solana", "So11111111111111111111111111111111111111112", "SOL", 5)

    document = alert.to_document()

    assert set(document) == {
        "ownerId",
        "source",
        "target",
        "condition",
        "repeat",
        "status",
        "name",
        "createdAt",
    }
    assert document["source"] == "dex"
    assert document["target"] == {
        "chain": "solana",
        "address": "So11111111111111111111111111111111111111112",
    }
    assert document["condition"] == {
        "kind": "percent_change",
        "changePercent": 5.0,
        "baselinePrice": None,
    }
    assert document["repeat"] == "always"
    assert document["status"] == "active"
    assert "_id" not in document  # MongoDB generates it


def test_alert_round_trip_keeps_every_field() -> None:
    alert_id = ObjectId()
    created = datetime(2025, 1, 1, tzinfo=timezone.utc)
    document = {
        "_id": alert_id,
        "ownerId": "42",
        "source": "dex",
        "target": {"chain": "bsc", "address": "0xabc"},
        "condition": {"kind": "percent_change", "changePercent": 7.5, "baselinePrice": 1.25},
        "repeat": "always",
        "status": "active",
        "name": "CAKE",
        "createdAt": created,
    }

    alert = Alert.from_document(document)

    assert alert.id == alert_id
    assert alert.baseline_price == 1.25
    assert alert.to_document() == document


def test_zero_baseline_is_not_read_as_missing() -> None:
    alert = Alert.from_document(
        {"_id": ObjectId(), "condition": {"changePercent": 1, "baselinePrice": 0}}
    )

    assert alert.baseline_price == 0.0


def test_null_baseline_stays_none() -> None:
    alert = Alert.from_document(
        {"_id": ObjectId(), "condition": {"changePercent": 1, "baselinePrice": None}}
    )

    assert alert.baseline_price is None
