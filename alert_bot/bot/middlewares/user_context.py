"""User upsert and activity tracking.

Runs before every handler: upserts the user document and refreshes ``lastActivityAt``,
then puts the loaded ``User`` in the handler context so handlers do not each re-read it.

Whether a user who blocked and then unblocked the bot should be restored to ``active``
here is an open question (PLAN.md §6.7); until it is answered the legacy behaviour holds
and the flag is never cleared.
"""
