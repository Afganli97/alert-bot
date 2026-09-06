"""Alert repository.

Create, list per user, delete, change threshold, read the active set for the price loop,
and update a baseline. The unique index on ``(ownerId, target.chain, target.address)``
surfaces as a typed duplicate error rather than a driver code the caller has to recognise
(PLAN.md §6.5).
"""
