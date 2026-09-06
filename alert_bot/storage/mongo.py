"""Client lifecycle and schema setup.

Opens ``pymongo.AsyncMongoClient`` with the pool and timeout settings from
``config.MongoSettings``, pings ``admin`` to fail fast on a bad URI, and creates the
indexes at startup exactly as ``lib/db.js`` does:

* ``alerts``: ``{source, status}``, ``{ownerId}``, unique ``{ownerId, target.chain,
  target.address}``
* ``users``: ``{status}`` — new, so the blocked-user sweep stops scanning the collection
  (PLAN.md, smaller notes). Adding it changes no result.
"""
