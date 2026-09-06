"""``/admin`` subcommands, ``/broadcast`` and ``/reset_anchors``.

Admin identity comes from the parsed ADMIN_CHAT_IDS set. Covers user lookup, block and
unblock, ``set_subscription``, the broadcast flow (still refusing above
BROADCAST_MAX_USERS, PLAN.md §6.9a) and baseline reset.

``/reset_anchors`` is wired to a handler that exists, unlike the legacy dispatch which
called an unexported name and always raised (PLAN.md §6.3).
"""
