"""FSM states for multi-step commands.

Replaces the legacy in-memory ``sessions`` Map: the add-token flow, the threshold change
flow, the removal flow and the broadcast confirmation. SESSION_TTL_MS keeps the 30-minute
idle expiry; ``/cancel`` clears the state.

Storage is in-memory for now, so flows are still lost on restart exactly as today. Moving
to a persistent FSM storage is a later, isolated change.
"""
