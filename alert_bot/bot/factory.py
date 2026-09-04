"""Bot and Dispatcher construction.

Builds the ``Bot`` (HTML parse mode, link previews disabled — matching the legacy
``sendMessage`` payload), the ``Dispatcher`` with its FSM storage and middleware stack,
and registers the routers in order.

``allowed_updates`` is restricted to ``["message"]``, reproducing the legacy scope: the
old bot sends no keyboards, so nothing in production can depend on callback queries
(PLAN.md §6.11). Widening it is a deliberate later step.
"""
