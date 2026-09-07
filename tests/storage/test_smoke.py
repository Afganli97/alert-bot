"""Read-only smoke test against a real database (PLAN.md §8, step 2).

Skipped unless ``MONGO_SMOKE_URI`` is set, so it never runs by accident. It **reads
only**: counts, the index list and one document. Nothing here writes, creates an index or
drops anything, and it must be pointed at a clone (PLAN.md §9.3), never at production —
though even a mistake there cannot modify data.

    MONGO_SMOKE_URI="mongodb+srv://…/dexalerts_clone" .venv/bin/pytest \\
        tests/storage/test_smoke.py -v
"""

from __future__ import annotations

import os

import pytest

from alert_bot.config import MongoSettings
from alert_bot.storage import connect
from alert_bot.storage.models import Alert
from alert_bot.storage.users import reachable_filter
from tests.fakes import run

SMOKE_URI = os.environ.get("MONGO_SMOKE_URI", "")

pytestmark = pytest.mark.skipif(not SMOKE_URI, reason="MONGO_SMOKE_URI is not set")


def _settings() -> MongoSettings:
    return MongoSettings(
        uri=SMOKE_URI,
        database=os.environ.get("MONGO_SMOKE_DB_NAME", ""),
        max_pool_size=2,
        min_pool_size=1,
        server_selection_timeout_ms=5000,
        socket_timeout_ms=45000,
        connect_timeout_ms=10000,
    )


def test_reads_the_shared_schema() -> None:
    async def check() -> dict[str, object]:
        storage = await connect(_settings())
        try:
            summary: dict[str, object] = {
                "users": await storage.users.count_documents({}),
                "reachable_users": await storage.users.count_documents(reachable_filter()),
                "alerts": await storage.alerts.count_documents({}),
                "active_dex_alerts": await storage.alerts.count_documents(
                    {"source": "dex", "status": "active"}
                ),
                "alert_indexes": sorted(
                    (await storage.alerts.index_information()).keys()
                ),
                "sample_alert": await storage.alerts.find_one({}),
            }
            return summary
        finally:
            await storage.close()

    summary = run(check())

    print(  # noqa: T201 - the point of the smoke test is to show these numbers
        "\n".join(f"{key}: {value}" for key, value in summary.items() if key != "sample_alert")
    )
    assert summary["users"] >= 0
    assert isinstance(summary["alert_indexes"], list)

    sample = summary["sample_alert"]
    if sample is not None:
        alert = Alert.from_document(sample)
        assert alert.owner_id
        assert alert.chain
