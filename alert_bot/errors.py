"""Domain exception types.

The base class plus the errors that cross module boundaries — an unknown chain, an
invalid address, a duplicate alert, a subscription limit reached, an exhausted HTTP
retry. Handlers map these to user-facing text from ``bot/texts.py``; nothing else is
caught by type.

Replaces the legacy pattern of raising bare ``Error('DUPLICATE_ALERT')`` and inspecting
the message or a driver-specific ``code`` at the call site (PLAN.md §6.5).
"""
