"""User repository.

Upsert-on-activity (the ``ensureUser`` equivalent), subscription reads and writes, admin
block/unblock, and the blocked-user set consumed by the price loop.

The upsert splits fields cleanly between ``$setOnInsert`` (creation-time only) and
``$set`` (every message), never listing the same field in both — the conflict that makes
the legacy version raise ``ConflictingUpdateOperators`` (PLAN.md §6.2).
"""
