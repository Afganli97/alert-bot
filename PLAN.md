# Plan — Python rewrite of the DEX alert bot

Companion to [`INVENTORY.md`](INVENTORY.md), which describes the legacy Node.js bot
(`dex-alerts-bot` v2.0.0, tip `751fc81`) still running in production. This document is the
target architecture, the dependency choices, and a triage decision for every issue the
inventory raised.

Scope of the current commit: **skeleton only** — layout, configuration, dependency pins.
No business logic. Every module listed below exists as an empty stub with a docstring
stating its future responsibility.

---

## 1. Guiding constraints

1. **The old bot keeps running.** The new bot must be comparable against it, so the
   MongoDB schema, the collection names and the user-visible message formats are
   reproduced exactly unless this document says otherwise.
2. **Ported bugs stay ported.** Where the legacy behaviour is odd but observable by
   users, it is reproduced and listed in §6 so the divergence is a deliberate decision,
   not an accident.
3. **Chains are data, not branches.** `ethereum`, `bsc` and `solana` today; the code must
   never grow an `if chain == ...` ladder.
4. **This project outlives the original.** Extension points (new alert conditions, new
   price sources, new chains, callback-query UI, localisation) are structural from day
   one even where the first implementation only fills in one case.

---

## 2. Stack and dependencies

| Package | Pin | Why |
|---|---|---|
| `aiogram` | 3.31.0 | Telegram layer (settled by the working agreement). Brings `aiohttp` and `pydantic` transitively — reused for the webhook server and for model validation, so neither is a separate dependency. |
| `httpx` | 0.28.1 | Outbound HTTP to DexScreener (settled by the working agreement). |
| `pymongo` | 4.18.0 | MongoDB. `pymongo.AsyncMongoClient` is the supported async driver; `motor` is deprecated and is deliberately **not** used. |

Nothing else. In particular:

- **No `python-dotenv`.** Configuration comes from the process environment; the systemd
  unit supplies it with `EnvironmentFile=`. `.env.example` documents the variables.
- **No `pydantic-settings`.** `alert_bot/config.py` is ~150 lines of `os.environ` plus
  frozen dataclasses, and it ports the legacy `num(name, fallback, min)` clamp semantics
  exactly (see §3.2).
- **No web framework.** aiogram's `aiohttp` webhook handler replaces Express.
- **No scheduler library.** One `asyncio` task, same self-rescheduling shape as the
  legacy `setTimeout` loop.

Python 3.12, one virtualenv at `.venv`, `pip install --no-cache-dir -r requirements.txt`.

## 3. Package layout

```
alert_bot/
  __main__.py            entry point: python -m alert_bot
  config.py              ALL environment reads, parsed once at import
  logging_setup.py       stdlib logging configuration
  errors.py              domain exception types

  chains/                pluggable per-chain behaviour  ← §4
    base.py              Chain protocol + shared helpers
    registry.py          register / get / detect / unknown-chain fallback
    evm.py               EvmChain, parameterised (ethereum, bsc, …)
    solana.py            SolanaChain (base58, case-sensitive)

  services/              one module per external service  ← §5
    http.py              shared httpx client + retry/timeout policy
    dexscreener.py       token lookup + batch price polling
    telegram_sender.py   outbound send queue (rate limit, 429/403 handling)

  storage/               MongoDB access, no business rules
    mongo.py             client lifecycle, index creation
    models.py            User / Alert dataclasses ↔ documents
    users.py             user repository
    alerts.py            alert repository

  bot/                   aiogram layer, no I/O of its own
    factory.py           Bot + Dispatcher construction, router wiring
    states.py            FSM states (replaces the in-memory sessions Map)
    texts.py             every user-facing string, one place  ← §6.9
    keyboards.py         inline keyboards (empty today, see §7)
    middlewares/
      user_context.py    ensureUser + activity timestamp
      rate_limit.py      10 commands / 60 s per chat
      errors.py          catch-all → generic error reply
    routers/
      common.py          /start /help /cancel /privacy /stop /delete_my_data
      alerts.py          /add /list /remove /change /change_all
      admin.py           /admin …, /broadcast, /reset_anchors

  monitor/               the price loop
    scheduler.py         periodic driver + graceful shutdown handshake
    cycle.py             one poll cycle: group → fetch → evaluate → send
    conditions.py        condition evaluators, registered by `kind`  ← §7
    formatting.py        price and alert-message rendering

  web/
    server.py            aiohttp app hosting the aiogram webhook
    health.py            GET /health for the supervisor

tests/                   pytest, mirrors the package layout
```

Boundaries: `bot/` and `monitor/` may call `storage/` and `services/`; `storage/` and
`services/` never import from `bot/` or `monitor/`; `chains/` imports nothing from the
project except `errors`.

### 3.2 Configuration

One module, `alert_bot/config.py`, parsed once on first use into frozen dataclasses
(`Settings`, with `telegram`, `mongo`, `webhook`, `dex`, `http`, `limits` and `runtime`
sections). `load_settings(env)` takes the mapping explicitly so tests never read the real
environment; `get_settings()` is the cached process-wide accessor.

- Secrets (`TELEGRAM_TOKEN`, `MONGO_URI`, `WEBHOOK_SECRET`) are read from the environment
  only, never from a literal, and are never logged.
- `_int_env(name, fallback, minimum)` reproduces the legacy `config.num` contract: a value
  that is not an integer, or is below `minimum`, silently falls back to the default.
- Required variables are validated at startup and the process exits with a readable
  message naming the variable, instead of failing later inside a handler.
- Every variable, including the ones the legacy `.env.template` omitted, is listed in
  `.env.example` with a comment and its default.

## 4. Chains as plugins

A chain is an object satisfying `chains.base.Chain`:

```python
class Chain(Protocol):
    id: str                                   # DexScreener chainId, the stored value
    display_name: str
    aliases: tuple[str, ...]
    def validate_address(self, address: str) -> bool: ...
    def normalize_address(self, address: str) -> str: ...   # cache + storage key
    def explorer_url(self, address: str) -> str: ...
```

- `EvmChain` is one class instantiated per network: `EvmChain("ethereum", "Ethereum",
  "https://etherscan.io/token/{}")`, `EvmChain("bsc", …)`. Adding Base or Arbitrum is one
  line in `registry.py`, no other file changes.
- `SolanaChain` validates by base58-decoding to exactly 32 bytes (the legacy `bs58` check,
  reimplemented on the stdlib — base58 is ~20 lines and does not justify a dependency)
  and normalises to the **unchanged** string, because base58 is case-sensitive.
- `registry.detect(address)` returns the chains whose validator accepts an address; the
  legacy `isValidTokenAddress` (EVM regex *or* base58/32) is exactly the union of the
  registered validators, so behaviour is preserved by construction.
- `registry.get(chain_id)` falls back to `UnknownChain`, which accepts anything and
  normalises to the identity. This is required for parity: the legacy bot stores whatever
  `chainId` DexScreener reports and never checks it against a list, so a token on a chain
  we have not registered must keep working.

The only chain-aware decision in the hot path is `normalize_address`, which is what makes
issue §6.4 fixable without special-casing Solana in the price checker.

## 5. External services

One module per service, each owning its own client and its own failure policy.

- `services/http.py` — a single shared `httpx.AsyncClient` with connection pooling,
  plus the retry wrapper that ports `fetchWithRetry`: 3 attempts, 15 s timeout, 2 s
  backoff doubling, retrying transport/timeout errors only. See §6 row *fetchWithRetry
  and HTTP 429* for the one open question about that policy.
- `services/dexscreener.py` — `fetch_token_info(address)` and
  `fetch_batch_prices(chain_id, addresses)`; batching, the ≤30 cap and the 1 s inter-batch
  delay live here, not in the cycle.
- `services/telegram_sender.py` — the FIFO send queue: one message per
  `TG_QUEUE_DELAY_MS`, 429 → requeue at the tail and sleep `min(retry_after, 60)`,
  403 → mark the user undeliverable and drop the message.

## 6. Triage of every issue in INVENTORY.md

Legend: **port as-is** = reproduced deliberately, listed for review · **fix now** =
implemented correctly in the new bot · **defer** = not decided, question for the human.

| Item | Decision | Rationale |
|---|---|---|
| §6.1 `setWebhook` never sends `secret_token` while the server 403s without it | fix now | Confirmed broken in production; aiogram sends `secret_token` on registration and validates the header, so the check becomes real instead of unsatisfiable. |
| §6.2 `ensureUser` puts `username` in both `$setOnInsert` and `$set` | fix now | Confirmed broken in production (`ConflictingUpdateOperators`); `username` goes in `$set` only, `$setOnInsert` keeps just the creation-time fields. |
| §6.3 `/reset_anchors` calls `utilityCommands.handleResetAnchors`, which is not exported | fix now | A call to a function that does not exist can never have worked; the command is wired to the real handler. |
| §6.4 Price cache keyed on lowercased address, looked up with the raw stored address | fix now | A lookup that can never match is a defect, not a behaviour. Fixed by `chain.normalize_address` on both sides — lowercase for EVM, unchanged for Solana. **Visible consequence: Solana and checksummed-EVM alerts start firing** (see §7). |
| §6.5 `addAlert` raises `Error('DUPLICATE_ALERT')`, caller tests `e.code === 11000` | fix now | Dead error branch; a typed `DuplicateAlertError` restores the "уже отслеживается" message the code always intended to send. |
| §6.6 `alerts.status` written but never changed; `repeat:'always'` never read | port as-is | Both fields are written with the same values, so the documents stay identical for dual-run comparison. Whether a pause feature was planned is a §7 roadmap question, not a fix. |
| §6.7 `users.status:'blocked'` conflates admin ban and user-blocked-the-bot; never cleared | defer | Splitting them changes who receives alerts and could silently un-ban admin-banned users. **Question: separate `status` (admin ban) from a `deliverable` flag, and should a user who messages again be restored automatically?** |
| §6.8 Baseline written after the send, per alert (crash re-fires; failed send still advances) | port as-is | Making it atomic changes which alerts fire around a restart, which is exactly what dual-run comparison measures. Listed for review; the atomic variant is in §7. |
| §6.9a Broadcast aborts above 1000 active users instead of batching | defer | The cap may be a deliberate guard against a rate-limit storm. **Question: batch through the send queue with progress reporting, or keep the 1000-user refusal?** |
| §6.9b Broadcast text is HTML-escaped, so admins cannot use formatting | port as-is | Escaping also prevents a malformed tag from failing every send in the batch. Enabling admin HTML is an admin-facing decision to make explicitly, not a silent change. |
| §6.10a Downward moves render as `🔻 SYM 5.00%`, no minus sign | port as-is | The arrow already carries the direction and users read this message hundreds of times a day; changing it breaks both expectations and output comparison. |
| §6.10b `formatPrice` has no guard for `price <= 0` | port as-is | Same formatting for the same input, including JS exponent spelling (`1.000e-5`, not Python's `1.000e-05`) — a parity requirement covered by tests. |
| §6.11 Only `update.message` with non-empty text is handled | port as-is | The legacy bot sends no keyboards, so nothing in production can depend on callback queries; `allowed_updates=["message"]` keeps the surface identical. Buttons are §7. |
| §6.12 Deployment facts absent from the repo (Node version, supervisor, `.env` path, Mongo location, TLS) | defer | **Question: where does the new unit run, is MongoDB local or Atlas, and what terminates TLS in front of the webhook?** Needed before a systemd unit can be written. |
| §4 `TG_QUEUE_DELAY_MS` parsed into config but never read (35 ms hardcoded) | fix now | The variable is a no-op today, so nobody can depend on it; the queue reads it, with 35 ms as the default, preserving current timing. |
| §4 `BLOCKED_USERS_CACHE_TTL_MS` used but missing from `.env.template` | fix now | Documentation-only; the variable is in `.env.example` with its default. |
| §4 `TELEGRAM_TOKEN` re-read and `ADMIN_CHAT_IDS` re-parsed on every call | fix now | `process.env` does not change after `dotenv` loads it, so re-parsing is pure waste with no observable effect. Read once in `config.py`. |
| §5 `condition.baselinePrice` = change since the last alert, accumulating indefinitely | port as-is | This is the product behaviour users experience, however unusual. A rolling-window variant belongs in §7 as a new condition `kind`, not as a redefinition of the existing one. |
| §5 `shutdown()` does not drain the send queue | fix now | Nobody can rely on losing a queued message; shutdown drains for up to `SHUTDOWN_DRAIN_TIMEOUT_MS`, then exits regardless. |
| §2 `fetchWithRetry` does not retry non-2xx, so a DexScreener 429 drops the batch for the cycle | defer | Retrying changes request volume and cycle duration under load. **Question: retry 429/5xx honouring `Retry-After`, or keep dropping the batch until the next 20 s cycle?** |
| §2 Retry exhaustion returns a fake `{ok:false, status:0}` response | fix now | An internal sentinel with no user-visible effect; the Python port raises a typed error the caller handles at the same place. |
| §5 `users._id` is the chat id as a **string** | port as-is | Mandatory schema compatibility — both bots must read and write the same documents. |
| Notes `handleAdminCommand` always returns `true`, making `if (handled)` constant | fix now | Dead branch with no behaviour attached; aiogram routers express the same dispatch without it. |
| Notes `getBlockedUsers` scans `users` with no index on `status` | fix now | Pure performance; adding the index changes no result. |
| Notes `/start` ≡ `/help`; `/stop` and `/delete_my_data` differ only in wording | port as-is | User-visible command surface, kept identical including the wording difference. |
| Notes `addAlert` counts alerts of all sources against the subscription limit | port as-is | Identical behaviour while `dex` is the only source; revisit when a second source is added. |
| Notes All user-facing strings are Russian | port as-is | Same strings, same wording — but routed through `bot/texts.py` so localisation is a later addition rather than a rewrite. |
| §3 Node-only cruft: unused `ObjectId`/`ensureUser`/`sleep` imports, redundant `body-parser` | fix now | Not carried over; no equivalent exists in the Python layout. |

### Behaviour changes users will notice

Only one entry above is visible to end users rather than to admins or operators:

- **§6.4** — alerts on Solana tokens, and on EVM addresses pasted in checksummed form,
  currently never fire. After the fix they fire. Affected users will start receiving
  notifications they have never received, with a first-cycle baseline. Flagging this
  because it changes traffic volume and may surprise long-idle users.

Items §6.1 and §6.2, though "confirmed broken", should make no difference to a healthy
production bot: if the webhook were truly rejecting every update, no command would ever
have worked. Both fixes are correct regardless, but their apparent no-op is itself a hint
that a proxy or an out-of-band registration exists — which is what §6.12 asks about.

## 7. Room to grow

Deliberate extension points, each already a module or a registry rather than a TODO:

- **New condition kinds.** `monitor/conditions.py` dispatches on `condition.kind`;
  `percent_change` is the only registered evaluator today. Absolute price thresholds,
  rolling windows and volume/liquidity conditions register alongside it without touching
  the cycle.
- **New price sources.** `alerts.source` already exists in the schema (`"dex"`). A second
  source is a new module under `services/` plus a registration, not a fork of the cycle.
- **New chains.** One line in `chains/registry.py`.
- **Button UI.** `bot/keyboards.py` and the FSM in `bot/states.py` are in place; enabling
  callback queries is widening `allowed_updates` and adding a router.
- **Localisation.** All strings already isolated in `bot/texts.py`.
- **Alert pausing.** The `status` and `repeat` fields (§6.6) are the natural home if the
  team confirms the feature was intended.
- **Atomic baseline updates.** The §6.8 improvement, once dual-run comparison is finished.

## 8. Delivery order

1. **This commit** — skeleton: layout, `config.py`, `.env.example`, `requirements.txt`.
2. Storage layer against the existing schema, plus a read-only smoke test on a copy.
3. `chains/` with its validation/normalisation tests (the §6.4 fix lands here).
4. `services/` — DexScreener and the send queue, tested against recorded responses.
5. `monitor/` — the cycle and conditions, byte-compared against legacy message output.
6. `bot/` — routers and FSM, replacing the sessions Map.
7. `web/` — webhook with a real `secret_token` (§6.1).
8. Dual run against a cloned database, output diffed, then cutover.

## 9. Open questions, collected

1. §6.7 — split admin ban from bot-blocked, and auto-restore on activity?
2. §6.9a — batch broadcasts above 1000 users, or keep the refusal?
3. §6.12 — host, supervisor, MongoDB location, TLS termination, `.env` path?
4. §2 — retry DexScreener 429/5xx, or keep dropping the batch?
5. Is the webhook registered out-of-band, or does a proxy inject the secret header?
   (§6.1's fix stands either way, but the answer decides the cutover procedure.)
