"""Shared outbound HTTP.

A single pooled ``httpx.AsyncClient`` plus the retry wrapper ported from
``lib/fetchWithRetry.js``: HTTP_RETRY_ATTEMPTS attempts, HTTP_TIMEOUT_MS per attempt,
HTTP_RETRY_BACKOFF_MS doubling between them, retrying transport and timeout errors only.

A non-2xx response is returned to the caller unretried, which is what makes a DexScreener
429 drop the batch for the cycle. That behaviour is deliberate here and open for review —
PLAN.md §9 question 4. On exhaustion this raises instead of returning the legacy fake
``{ok: false, status: 0}`` sentinel.
"""
