"""User repository.

Upsert-on-activity (the ``ensureUser`` equivalent), subscription reads and writes, admin
block/unblock, and the excluded-recipient set consumed by the price loop.

The upsert splits fields cleanly between ``$setOnInsert`` (creation-time only) and
``$set`` (every message), never listing the same field in both — the conflict that makes
the legacy version raise ``ConflictingUpdateOperators`` (PLAN.md §6.2).

Two query shapes appear here and nowhere else, both served by the ``{status,
deliverable}`` index of PLAN.md §9.2:

* :func:`reachable_filter` — users a broadcast may write to;
* :func:`excluded_filter` — its complement, the set the price loop skips.

Both cover the legacy document shape as well as the new one, so no document has to be
rewritten for the split of PLAN.md §6.7.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from pymongo import ReturnDocument

from ..errors import InvalidChatIdError
from .models import (
    STATUS_ACTIVE,
    STATUS_BLOCKED,
    SUBSCRIPTION_BASIC,
    USERNAME_MAX_LENGTH,
    User,
    utcnow,
)

if TYPE_CHECKING:  # pragma: no cover
    from pymongo.asynchronous.collection import AsyncCollection

logger = logging.getLogger(__name__)


def reachable_filter() -> dict[str, Any]:
    """Users who are neither banned nor undeliverable.

    ``$ne`` rather than equality on purpose: a legacy document has no ``deliverable``
    field at all, and a missing field is not ``False``, so it stays included exactly as
    it is today (PLAN.md §9.2).
    """
    return {"status": {"$ne": STATUS_BLOCKED}, "deliverable": {"$ne": False}}


def excluded_filter() -> dict[str, Any]:
    """The complement of :func:`reachable_filter`: banned **or** undeliverable."""
    return {"$or": [{"status": STATUS_BLOCKED}, {"deliverable": False}]}


def _normalise_chat_id(chat_id: str | int) -> str:
    """Return the chat id as the stored string, or raise.

    Ports ``lib/users.js:51``. The id is a string in the database and must stay one —
    both bots read the same documents (PLAN.md §6, "``users._id`` is the chat id as a
    string").
    """
    value = str(chat_id).strip()
    if not value:
        raise InvalidChatIdError("chat id is empty")
    return value


def _normalise_username(username: str | None) -> str | None:
    """Drop an over-long username, as ``lib/users.js:54`` does, rather than truncating."""
    if not username:
        return None
    return username if len(username) <= USERNAME_MAX_LENGTH else None


class UserRepository:
    """Every read and write of the ``users`` collection."""

    __slots__ = ("_collection", "_cache_ttl_s", "_clock", "_cached_excluded", "_cached_at")

    def __init__(
        self,
        collection: "AsyncCollection[Any]",
        *,
        excluded_cache_ttl_ms: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._collection = collection
        self._cache_ttl_s = excluded_cache_ttl_ms / 1000
        self._clock = clock
        self._cached_excluded: frozenset[str] | None = None
        self._cached_at = 0.0

    # -- writes on activity -------------------------------------------------

    async def ensure(self, chat_id: str | int, username: str | None = None) -> User:
        """Create the user or refresh their activity, and return the stored document.

        ``username`` is in ``$set`` only. The legacy version listed it in ``$setOnInsert``
        *and* ``$set``, which MongoDB rejects with ``ConflictingUpdateOperators`` —
        invisible today only because no update ever reaches a handler (PLAN.md §6.2).

        Any message also restores ``deliverable``: a user who blocked the bot and came
        back is reachable again (PLAN.md §6.7). ``status`` is untouched, so an admin ban
        survives — clearing it is ``/admin unblock_user`` and nothing else.
        """
        key = _normalise_chat_id(chat_id)
        document = await self._collection.find_one_and_update(
            {"_id": key},
            {
                "$setOnInsert": {
                    "createdAt": utcnow(),
                    "status": STATUS_ACTIVE,
                    "subscription": SUBSCRIPTION_BASIC,
                },
                "$set": {
                    "username": _normalise_username(username),
                    "deliverable": True,
                },
                "$currentDate": {"lastActivityAt": True},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return User.from_document(document)

    # -- reads --------------------------------------------------------------

    async def get(self, chat_id: str | int) -> User | None:
        document = await self._collection.find_one({"_id": _normalise_chat_id(chat_id)})
        return None if document is None else User.from_document(document)

    async def count_all(self) -> int:
        return await self._collection.count_documents({})

    async def count_reachable(self) -> int:
        """The admin panel's "active users" and the broadcast's audience size."""
        return await self._collection.count_documents(reachable_filter())

    async def count_active_since(self, moment: datetime) -> int:
        """Reachable users seen since ``moment`` (``handlers/adminCommands.js:44``)."""
        return await self._collection.count_documents(
            {"lastActivityAt": {"$gte": moment}, **reachable_filter()}
        )

    async def iter_reachable(self) -> AsyncIterator[User]:
        """Stream the broadcast audience.

        A cursor, not ``toArray``: the legacy bot loaded every user document into memory
        at once, which is the shape that made ``BROADCAST_MAX_USERS`` look necessary
        (PLAN.md §6.9a).
        """
        cursor = self._collection.find(reachable_filter())
        async for document in cursor:
            yield User.from_document(document)

    async def excluded_recipient_ids(self) -> frozenset[str]:
        """Chat ids the price loop must skip, cached for the configured TTL.

        Ports ``getBlockedUsers`` (``checkers/dexPriceChecker.js:89``) including its
        staleness: a user marked undeliverable by a 403 is still sent to until the cache
        expires, exactly as today. Only the admin ban path invalidates eagerly.
        """
        now = self._clock()
        cached = self._cached_excluded
        if cached is not None and now - self._cached_at < self._cache_ttl_s:
            return cached

        cursor = self._collection.find(excluded_filter(), {"_id": 1})
        ids = frozenset([str(document["_id"]) async for document in cursor])
        self._cached_excluded = ids
        self._cached_at = now
        return ids

    def invalidate_excluded_cache(self) -> None:
        self._cached_excluded = None
        self._cached_at = 0.0

    # -- writes -------------------------------------------------------------

    async def ban(self, chat_id: str | int) -> bool:
        """``/admin block_user``. Sets the ban and nothing else (PLAN.md §6.7)."""
        return await self._set_status(chat_id, STATUS_BLOCKED)

    async def unban(self, chat_id: str | int) -> bool:
        """``/admin unblock_user``. Clears the ban; ``deliverable`` is not touched."""
        return await self._set_status(chat_id, STATUS_ACTIVE)

    async def _set_status(self, chat_id: str | int, status: str) -> bool:
        result = await self._collection.update_one(
            {"_id": _normalise_chat_id(chat_id)}, {"$set": {"status": status}}
        )
        self.invalidate_excluded_cache()
        return result.matched_count > 0

    async def set_subscription(self, chat_id: str | int, subscription: str) -> bool:
        result = await self._collection.update_one(
            {"_id": _normalise_chat_id(chat_id)}, {"$set": {"subscription": subscription}}
        )
        return result.matched_count > 0

    async def mark_undeliverable(self, chat_id: str | int) -> bool:
        """Telegram answered 403 for this chat: stop sending until they write again.

        The legacy queue wrote ``status: "blocked"`` here (``lib/telegramQueue.js:85``),
        which is what conflated the two meanings. The cache is deliberately **not**
        invalidated, so the loop keeps its current behaviour for the rest of the TTL.
        """
        result = await self._collection.update_one(
            {"_id": _normalise_chat_id(chat_id)}, {"$set": {"deliverable": False}}
        )
        if result.matched_count:
            logger.info("Marked chat %s undeliverable", chat_id)
        return result.matched_count > 0

    async def delete(self, chat_id: str | int) -> bool:
        """``/stop`` and ``/delete_my_data``; the alerts go with :class:`AlertRepository`."""
        result = await self._collection.delete_one({"_id": _normalise_chat_id(chat_id)})
        self.invalidate_excluded_cache()
        return result.deleted_count > 0
