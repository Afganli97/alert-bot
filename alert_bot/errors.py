"""Domain exception types.

The base class plus the errors that cross module boundaries — an unknown chain, an
invalid address, a duplicate alert, a subscription limit reached, an exhausted HTTP
retry. Handlers map these to user-facing text from ``bot/texts.py``; nothing else is
caught by type.

Replaces the legacy pattern of raising bare ``Error('DUPLICATE_ALERT')`` and inspecting
the message or a driver-specific ``code`` at the call site (PLAN.md §6.5).

Only the storage errors exist so far; the chain, service and limit errors land with the
steps that raise them (PLAN.md §8).
"""

from __future__ import annotations


class AlertBotError(Exception):
    """Base class for every error this project raises deliberately."""


class StorageError(AlertBotError):
    """A database operation could not be completed as asked."""


class DuplicateAlertError(StorageError):
    """The owner already has an alert on this chain and address.

    Raised instead of leaking ``pymongo.errors.DuplicateKeyError``: the unique index
    ``{ownerId, target.chain, target.address}`` is a storage detail, and the handler only
    needs to know which message to send.
    """

    def __init__(self, owner_id: str, chain: str, address: str) -> None:
        super().__init__(f"alert already exists for {owner_id} on {chain}:{address}")
        self.owner_id = owner_id
        self.chain = chain
        self.address = address


class InvalidChatIdError(StorageError):
    """A chat id was empty or blank.

    Ports the ``Invalid chatId`` guard of ``lib/users.js:51``: an upsert keyed on an empty
    ``_id`` would create a junk user document that nothing can ever address.
    """
