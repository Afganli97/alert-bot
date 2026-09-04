"""Documents as dataclasses.

``User`` and ``Alert``, with explicit to/from-document mapping. The mapping is where
legacy schema quirks are pinned down rather than spread through the code:

* ``users._id`` is the chat id **as a string**.
* ``alerts.condition.baselinePrice`` is nullable and is the only field the price loop
  mutates.
* ``alerts.status`` and ``alerts.repeat`` are written and never read; kept so documents
  stay byte-comparable with the legacy bot (PLAN.md §6.6).
"""
