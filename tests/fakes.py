"""Test doubles for the MongoDB driver, plus the coroutine runner.

The repositories are judged on the query documents they build — that is what keeps the
two bots reading and writing the same documents during the dual run — so the double
records every call verbatim instead of simulating a database. It plays the role
``test/mocks/mockCollection.js`` plays in the legacy suite.

``run`` is why there is no ``pytest-asyncio``: an async test is an ordinary test function
that drives one coroutine.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Iterable, TypeVar

from bson import ObjectId

T = TypeVar("T")


def run(coro: Awaitable[T]) -> T:
    """Drive a coroutine to completion inside a test."""
    return asyncio.run(coro)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Call:
    """One recorded driver call."""

    method: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]

    @property
    def filter(self) -> Any:
        return self.args[0]

    @property
    def update(self) -> Any:
        return self.args[1]


@dataclass
class FakeUpdateResult:
    matched_count: int = 1
    modified_count: int = 1


@dataclass
class FakeDeleteResult:
    deleted_count: int = 1


@dataclass
class FakeInsertOneResult:
    inserted_id: ObjectId


class FakeCursor:
    """What :meth:`FakeCollection.find` returns: iterable once, ``to_list`` once."""

    def __init__(self, documents: Iterable[dict[str, Any]]) -> None:
        self._documents = list(documents)

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        return list(self._documents)

    def __aiter__(self) -> "FakeCursor":
        self._iterator = iter(self._documents)
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._iterator)
        except StopIteration:  # pragma: no cover - loop termination
            raise StopAsyncIteration from None


class FakeCollection:
    """Records calls and returns whatever the test set on it."""

    def __init__(self, documents: Iterable[dict[str, Any]] | None = None) -> None:
        self.calls: list[Call] = []
        #: Documents any ``find`` returns.
        self.documents: list[dict[str, Any]] = list(documents or [])
        self.find_one_result: dict[str, Any] | None = None
        self.find_one_and_update_result: dict[str, Any] = {"_id": "0"}
        self.count_result = 0
        self.insert_error: Exception | None = None
        self.inserted_id = ObjectId()
        self.update_result = FakeUpdateResult()
        self.delete_result = FakeDeleteResult()

    # -- assertions ---------------------------------------------------------

    def last(self, method: str) -> Call:
        """The most recent call to ``method``; fails the test if there was none."""
        for call in reversed(self.calls):
            if call.method == method:
                return call
        raise AssertionError(f"no {method} call was made; got {[c.method for c in self.calls]}")

    def method_names(self) -> list[str]:
        return [call.method for call in self.calls]

    def _record(self, method: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append(Call(method, args, kwargs))

    # -- driver surface -----------------------------------------------------

    def find(self, filter: Any = None, projection: Any = None, **kwargs: Any) -> FakeCursor:
        self._record("find", filter, projection, **kwargs)
        return FakeCursor(self.documents)

    async def find_one(self, filter: Any, **kwargs: Any) -> dict[str, Any] | None:
        self._record("find_one", filter, **kwargs)
        return self.find_one_result

    async def find_one_and_update(self, filter: Any, update: Any, **kwargs: Any) -> dict[str, Any]:
        self._record("find_one_and_update", filter, update, **kwargs)
        return self.find_one_and_update_result

    async def count_documents(self, filter: Any, **kwargs: Any) -> int:
        self._record("count_documents", filter, **kwargs)
        return self.count_result

    async def insert_one(self, document: Any, **kwargs: Any) -> FakeInsertOneResult:
        self._record("insert_one", document, **kwargs)
        if self.insert_error is not None:
            raise self.insert_error
        return FakeInsertOneResult(self.inserted_id)

    async def update_one(self, filter: Any, update: Any, **kwargs: Any) -> FakeUpdateResult:
        self._record("update_one", filter, update, **kwargs)
        return self.update_result

    async def update_many(self, filter: Any, update: Any, **kwargs: Any) -> FakeUpdateResult:
        self._record("update_many", filter, update, **kwargs)
        return self.update_result

    async def delete_one(self, filter: Any, **kwargs: Any) -> FakeDeleteResult:
        self._record("delete_one", filter, **kwargs)
        return self.delete_result

    async def delete_many(self, filter: Any, **kwargs: Any) -> FakeDeleteResult:
        self._record("delete_many", filter, **kwargs)
        return self.delete_result

    async def create_indexes(self, indexes: Any, **kwargs: Any) -> list[str]:
        self._record("create_indexes", indexes, **kwargs)
        return [index.document["name"] for index in indexes]


@dataclass
class FakeDatabase:
    """Just enough of ``AsyncDatabase`` for :func:`alert_bot.storage.ensure_indexes`."""

    name: str = "dexalerts"
    collections: dict[str, FakeCollection] = field(default_factory=dict)

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


class FakeClock:
    """A monotonic clock the test advances by hand, so no test ever sleeps."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
