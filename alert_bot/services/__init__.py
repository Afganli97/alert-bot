"""Clients for external services. One module per service, each owning its policy.

Nothing here imports from ``bot`` or ``monitor``; these modules know about HTTP and about
their own payload shapes, not about alerts or users.
"""
