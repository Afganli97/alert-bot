"""aiogram layer: routers, middlewares, FSM and user-facing text.

Handlers orchestrate; they do not talk to HTTP or to MongoDB directly, they call
``services`` and ``storage``. Nothing outside this package imports aiogram.
"""
