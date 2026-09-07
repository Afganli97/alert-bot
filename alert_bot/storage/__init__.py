"""MongoDB access.

Repositories return domain objects and take domain arguments; no query document escapes
this package, and no business rule enters it. The schema is shared with the running
Node.js bot for the duration of the dual run, so field names and types are fixed.
"""

from .alerts import AlertRepository
from .models import Alert, User
from .mongo import Storage, connect, ensure_indexes
from .users import UserRepository, excluded_filter, reachable_filter

__all__ = [
    "Alert",
    "AlertRepository",
    "Storage",
    "User",
    "UserRepository",
    "connect",
    "ensure_indexes",
    "excluded_filter",
    "reachable_filter",
]
