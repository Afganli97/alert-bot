"""Alert repository.

Create, list per user, delete, change threshold, read the active set for the price loop,
and update a baseline. The unique index on ``(ownerId, target.chain, target.address)``
surfaces as a typed duplicate error rather than a driver code the caller has to recognise
(PLAN.md §6.5).

Business rules stay out: address validation belongs to ``chains/`` and the subscription
limit to the handler, because both produce user-facing messages this package must not
know about. What does live here is the shape of every query the legacy bot issues, so
that the two bots read and write the same documents during the dual run.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from ..errors import DuplicateAlertError
from .models import SOURCE_DEX, STATUS_ACTIVE, Alert

if TYPE_CHECKING:  # pragma: no cover
    from pymongo.asynchronous.collection import AsyncCollection

logger = logging.getLogger(__name__)

BASELINE_FIELD = "condition.baselinePrice"
THRESHOLD_FIELD = "condition.changePercent"


class AlertRepository:
    """Every read and write of the ``alerts`` collection."""

    __slots__ = ("_collection",)

    def __init__(self, collection: "AsyncCollection[Any]") -> None:
        self._collection = collection

    # -- the price loop -----------------------------------------------------

    async def active_dex_alerts(self) -> list[Alert]:
        """The cycle's input (``checkers/dexPriceChecker.js:83``)."""
        cursor = self._collection.find({"source": SOURCE_DEX, "status": STATUS_ACTIVE})
        return [Alert.from_document(document) for document in await cursor.to_list(None)]

    async def update_baseline(self, alert_id: ObjectId, price: float) -> bool:
        """Move the anchor after a firing — the only field the loop writes.

        Written per alert and after the send, as ``updateAlertBaseline`` does; making it
        atomic with the send would change which alerts fire around a restart, which is
        what the dual run measures (PLAN.md §6.8).
        """
        result = await self._collection.update_one(
            {"_id": alert_id}, {"$set": {BASELINE_FIELD: float(price)}}
        )
        return result.matched_count > 0

    # -- per user -----------------------------------------------------------

    async def list_for_owner(self, owner_id: str) -> list[Alert]:
        """``/list``: this owner's DEX alerts, in natural order as the legacy bot shows."""
        cursor = self._collection.find({"ownerId": owner_id, "source": SOURCE_DEX})
        return [Alert.from_document(document) for document in await cursor.to_list(None)]

    async def count_for_owner(self, owner_id: str) -> int:
        """Alerts counted against the subscription limit.

        Counts **all sources**, not just ``dex``, because that is what the legacy limit
        check does; identical while ``dex`` is the only source (PLAN.md §6 notes).
        """
        return await self._collection.count_documents({"ownerId": owner_id})

    async def count_all(self) -> int:
        return await self._collection.count_documents({})

    async def create(self, alert: Alert) -> Alert:
        """Insert a new alert, or raise :class:`DuplicateAlertError`.

        The caller has already validated the address and checked the subscription limit;
        the duplicate is the one failure only the database can detect.
        """
        try:
            result = await self._collection.insert_one(alert.to_document())
        except DuplicateKeyError as exc:
            raise DuplicateAlertError(alert.owner_id, alert.chain, alert.address) from exc
        logger.info(
            "Alert created for %s on %s:%s at %s%%",
            alert.owner_id,
            alert.chain,
            alert.address,
            alert.change_percent,
        )
        return alert.with_id(result.inserted_id)

    async def delete(self, alert_id: ObjectId, owner_id: str) -> bool:
        """``/remove``. The owner is part of the filter so no one can delete another's."""
        result = await self._collection.delete_one({"_id": alert_id, "ownerId": owner_id})
        return result.deleted_count > 0

    async def delete_for_owner(self, owner_id: str) -> int:
        """``/stop`` and ``/delete_my_data`` (``handlers/utilityCommands.js:82``)."""
        result = await self._collection.delete_many({"ownerId": owner_id})
        return result.deleted_count

    async def set_threshold(self, alert_id: ObjectId, owner_id: str, percent: float) -> bool:
        """``/change``. Range validation is the handler's, as in the legacy bot."""
        result = await self._collection.update_one(
            {"_id": alert_id, "ownerId": owner_id},
            {"$set": {THRESHOLD_FIELD: float(percent)}},
        )
        return result.matched_count > 0

    async def set_threshold_for_owner(self, owner_id: str, percent: float) -> int:
        """``/change_all``."""
        result = await self._collection.update_many(
            {"ownerId": owner_id}, {"$set": {THRESHOLD_FIELD: float(percent)}}
        )
        return result.modified_count

    async def reset_baselines_for_owner(self, owner_id: str) -> int:
        result = await self._collection.update_many(
            {"ownerId": owner_id}, {"$set": {BASELINE_FIELD: None}}
        )
        return result.modified_count

    async def reset_all_baselines(self) -> int:
        """``/reset_anchors``: every alert re-anchors on the next cycle.

        Never run against production during the dual run — it creates a difference
        between the two databases instead of removing one (PLAN.md §9.3).
        """
        result = await self._collection.update_many({}, {"$set": {BASELINE_FIELD: None}})
        logger.info("Reset %d baselines", result.modified_count)
        return result.modified_count
