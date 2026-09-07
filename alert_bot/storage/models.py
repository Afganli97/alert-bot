"""Documents as dataclasses.

``User`` and ``Alert``, with explicit to/from-document mapping. The mapping is where
legacy schema quirks are pinned down rather than spread through the code:

* ``users._id`` is the chat id **as a string**.
* ``alerts.condition.baselinePrice`` is nullable and is the only field the price loop
  mutates.
* ``alerts.status`` and ``alerts.repeat`` are written and never read; kept so documents
  stay byte-comparable with the legacy bot (PLAN.md §6.6).

It is also where the read compatibility of PLAN.md §9.2 lives: ``deliverable`` is a new
field, a document written by the legacy bot does not have it, and such a document must
read exactly as it behaves today.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping

from bson import ObjectId

#: The only value ``alerts.source`` has ever held; a second source is PLAN.md §7.
SOURCE_DEX = "dex"
#: The only registered ``condition.kind``.
KIND_PERCENT_CHANGE = "percent_change"
#: Written, never read (PLAN.md §6.6).
REPEAT_ALWAYS = "always"

STATUS_ACTIVE = "active"
STATUS_BLOCKED = "blocked"
SUBSCRIPTION_BASIC = "basic"

#: ``handlers/alertCommands.js:71`` truncates the token symbol to 30 characters.
NAME_MAX_LENGTH = 30
#: ``lib/users.js:54`` drops a username longer than this instead of storing it.
USERNAME_MAX_LENGTH = 100


def utcnow() -> datetime:
    """Creation timestamps, the equivalent of the legacy ``new Date()``."""
    return datetime.now(timezone.utc)


def _as_float(value: Any, default: float) -> float:
    """Coerce a stored number, falling back for anything that is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


@dataclass(frozen=True, slots=True)
class User:
    """A document of the ``users`` collection.

    ``status`` is the **admin ban and nothing else** and ``deliverable`` is whether
    Telegram still accepts messages for this chat — the split of PLAN.md §6.7. The price
    loop skips a user who is banned *or* undeliverable, which is exactly the set the
    legacy single ``status`` field excludes today.
    """

    chat_id: str
    username: str | None = None
    created_at: datetime | None = None
    last_activity_at: datetime | None = None
    status: str = STATUS_ACTIVE
    subscription: str = SUBSCRIPTION_BASIC
    deliverable: bool = True

    @property
    def is_banned(self) -> bool:
        return self.status == STATUS_BLOCKED

    @property
    def is_reachable(self) -> bool:
        return not self.is_banned and self.deliverable

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "User":
        """Map a stored document, in either schema version (PLAN.md §9.2).

        A missing ``deliverable`` reads as ``True``, except on a legacy
        ``status: "blocked"`` document, which reads as banned *and* undeliverable: the
        legacy field cannot say which of the two it meant, so it keeps excluding the user
        either way.
        """
        status = str(document.get("status") or STATUS_ACTIVE)
        stored = document.get("deliverable")
        deliverable = stored if isinstance(stored, bool) else status != STATUS_BLOCKED
        return cls(
            chat_id=str(document["_id"]),
            username=document.get("username") or None,
            created_at=document.get("createdAt"),
            last_activity_at=document.get("lastActivityAt"),
            status=status,
            subscription=str(document.get("subscription") or SUBSCRIPTION_BASIC),
            deliverable=deliverable,
        )


@dataclass(frozen=True, slots=True)
class Alert:
    """A document of the ``alerts`` collection.

    Field names and nesting are fixed by the schema the legacy bot writes; see
    :meth:`to_document`, which reproduces ``handlers/alertCommands.js:87-101`` exactly so
    that documents created by either bot are indistinguishable during the dual run.
    """

    owner_id: str
    chain: str
    address: str
    name: str
    change_percent: float
    baseline_price: float | None = None
    source: str = SOURCE_DEX
    kind: str = KIND_PERCENT_CHANGE
    repeat: str = REPEAT_ALWAYS
    status: str = STATUS_ACTIVE
    created_at: datetime | None = None
    #: ``None`` until the document is inserted.
    id: ObjectId | None = None

    @classmethod
    def new(
        cls,
        owner_id: str,
        chain: str,
        address: str,
        name: str,
        change_percent: float,
    ) -> "Alert":
        """Build an alert ready to insert, applying the schema's own normalisation.

        The chain id is lowercased and the name truncated as the legacy insert does. The
        address is stored **unchanged**: base58 is case-sensitive, so normalising it here
        would corrupt Solana addresses (PLAN.md §4). Address validation and the
        subscription limit are the caller's, not storage's.
        """
        return cls(
            owner_id=str(owner_id),
            chain=str(chain).lower(),
            address=address,
            name=(name or "")[:NAME_MAX_LENGTH],
            change_percent=float(change_percent),
            created_at=utcnow(),
        )

    def with_id(self, alert_id: ObjectId) -> "Alert":
        return replace(self, id=alert_id)

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "Alert":
        target = document.get("target") or {}
        condition = document.get("condition") or {}
        baseline = condition.get("baselinePrice")
        return cls(
            owner_id=str(document.get("ownerId", "")),
            chain=str(target.get("chain", "")),
            address=str(target.get("address", "")),
            name=str(document.get("name") or ""),
            change_percent=_as_float(condition.get("changePercent"), 0.0),
            baseline_price=None if baseline is None else _as_float(baseline, 0.0),
            source=str(document.get("source") or SOURCE_DEX),
            kind=str(condition.get("kind") or KIND_PERCENT_CHANGE),
            repeat=str(document.get("repeat") or REPEAT_ALWAYS),
            status=str(document.get("status") or STATUS_ACTIVE),
            created_at=document.get("createdAt"),
            id=document.get("_id"),
        )

    def to_document(self) -> dict[str, Any]:
        """Render the insert document, in the legacy field order."""
        document: dict[str, Any] = {
            "ownerId": self.owner_id,
            "source": self.source,
            "target": {
                "chain": self.chain,
                "address": self.address,
            },
            "condition": {
                "kind": self.kind,
                "changePercent": self.change_percent,
                "baselinePrice": self.baseline_price,
            },
            "repeat": self.repeat,
            "status": self.status,
            "name": self.name,
            "createdAt": self.created_at,
        }
        if self.id is not None:
            document["_id"] = self.id
        return document
