"""MongoDB access.

Repositories return domain objects and take domain arguments; no query document escapes
this package, and no business rule enters it. The schema is shared with the running
Node.js bot for the duration of the dual run, so field names and types are fixed.
"""
