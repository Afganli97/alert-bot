"""Client lifecycle and schema setup.

Opens ``pymongo.AsyncMongoClient`` with the pool and timeout settings from
``config.MongoSettings``, pings ``admin`` to fail fast on a bad URI, and creates the
indexes at startup exactly as ``lib/db.js`` does:

* ``alerts``: ``{source, status}``, ``{ownerId}``, unique ``{ownerId, target.chain,
  target.address}``
* ``users``: ``{status, deliverable}`` — new, so the excluded-recipient query stops
  scanning the collection (PLAN.md §9.2). Adding it changes no result.

The connection is owned by :class:`Storage`, which hands the two collections to the
repositories. The legacy bot kept them in module-level globals initialised by
``initCollections`` (``lib/users.js:7``); here nothing is global, so a test can build a
repository over a fake collection without touching a driver.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pymongo import ASCENDING, AsyncMongoClient, IndexModel

from ..config import MongoSettings

if TYPE_CHECKING:  # pragma: no cover - import cost only, annotations are strings
    from pymongo.asynchronous.collection import AsyncCollection
    from pymongo.asynchronous.database import AsyncDatabase

logger = logging.getLogger(__name__)

USERS_COLLECTION = "users"
ALERTS_COLLECTION = "alerts"


def alert_indexes() -> list[IndexModel]:
    """The three indexes ``lib/db.js:27-32`` creates, with the same keys and options.

    The names are left to the driver, which derives the same defaults the legacy bot
    got, so re-creating them against a database the old bot already indexed is a no-op
    rather than a conflict.
    """
    return [
        IndexModel([("source", ASCENDING), ("status", ASCENDING)]),
        IndexModel([("ownerId", ASCENDING)]),
        IndexModel(
            [
                ("ownerId", ASCENDING),
                ("target.chain", ASCENDING),
                ("target.address", ASCENDING),
            ],
            unique=True,
        ),
    ]


def user_indexes() -> list[IndexModel]:
    """The index the excluded-recipient query needs (PLAN.md §9.2, §6 notes)."""
    return [IndexModel([("status", ASCENDING), ("deliverable", ASCENDING)])]


class Storage:
    """Owns the client and exposes the two collections the repositories need."""

    __slots__ = ("_client", "database")

    def __init__(self, client: "AsyncMongoClient[Any]", database: "AsyncDatabase[Any]") -> None:
        self._client = client
        self.database = database

    @property
    def users(self) -> "AsyncCollection[Any]":
        return self.database[USERS_COLLECTION]

    @property
    def alerts(self) -> "AsyncCollection[Any]":
        return self.database[ALERTS_COLLECTION]

    async def close(self) -> None:
        await self._client.close()
        logger.info("MongoDB connection closed")


async def connect(settings: MongoSettings) -> Storage:
    """Open a client, verify the connection, and return the storage handle.

    Raises whatever the driver raises when the cluster is unreachable — after closing the
    half-open client, as ``lib/db.js:36`` does — so a misconfigured process dies at
    startup instead of inside the first cycle.
    """
    client: AsyncMongoClient[Any] = AsyncMongoClient(
        settings.uri,
        maxPoolSize=settings.max_pool_size,
        minPoolSize=settings.min_pool_size,
        serverSelectionTimeoutMS=settings.server_selection_timeout_ms,
        socketTimeoutMS=settings.socket_timeout_ms,
        connectTimeoutMS=settings.connect_timeout_ms,
        # Dates come back as aware UTC instead of naive; what is written is unchanged.
        tz_aware=True,
    )
    try:
        await client.admin.command("ping")
    except Exception:
        await client.close()
        raise

    # An empty MONGO_DB_NAME means "the database in the URI", which is what the legacy
    # bot always uses; setting it is how the dual run points at the clone (PLAN.md §9.3).
    database = client.get_database(settings.database or None)
    logger.info("Connected to MongoDB, database %s", database.name)
    return Storage(client, database)


async def ensure_indexes(database: "AsyncDatabase[Any]") -> None:
    """Create the indexes both bots rely on. Idempotent, and safe to run on a shared DB."""
    await database[ALERTS_COLLECTION].create_indexes(alert_indexes())
    await database[USERS_COLLECTION].create_indexes(user_indexes())
    logger.info("Indexes ensured on %s and %s", ALERTS_COLLECTION, USERS_COLLECTION)
