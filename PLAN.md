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
5. **One user today, many tomorrow.** The community is private and the legacy bot has
   exactly one user, the operator. This is **temporary**: the community will be opened
   once the bots are ready. It is a licence to simplify one-off migration and dual-run
   tooling — §9.2 and §9.3 — and nothing else. The send queue, the rate limits, the 429
   handling, the undeliverable-user cache, the subscription limits, the indexes and the
   broadcast batching are sized for the reopened community and are not to be downscaled on
   the grounds of today's headcount.

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

### 2.1 Transport

**Webhook. Decided, not to be revisited.** The bot ran on long polling before and the move
to a webhook was a deliberate choice; polling was reconsidered while triaging §6.1 and
rejected again. The `web/` package stays, and so does step 7 of §8.

- `setWebhook` is called with `secret_token=WEBHOOK_SECRET`, and aiogram's request handler
  validates the `x-telegram-bot-api-secret-token` header against the same value.
  Registration and verification finally use one secret, which is the whole of §6.1.
- `allowed_updates=["message"]` is passed at registration (§6.11), so Telegram stops
  queueing update types the bot does not handle.
- Startup fails loudly, before the listener binds, when `WEBHOOK_URL` is unset or does not
  start with `https://`, and when `WEBHOOK_SECRET` is unset. The message names the variable.
- **TLS is terminated outside this process.** nginx terminates it (§9.1) and forwards to
  `WEBHOOK_HOST:WEBHOOK_PORT` over plain HTTP. The bot never reads a
  certificate, never binds 443 and has no HTTPS code path. `WEBHOOK_URL` is only the public
  https address handed to Telegram. See §9.1.
- There is no `BOT_MODE` variable: there is one transport.

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

tests/                   pytest, mirrors the package layout
deploy/                  systemd unit, no secrets in it (§9.1)
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

- `services/http.py` — a single shared `httpx.AsyncClient` with connection pooling, plus
  the retry wrapper that ports `fetchWithRetry`: 3 attempts, 15 s timeout, 2 s backoff
  doubling, retrying transport and timeout errors as the legacy does — **and 5xx**, on the
  same backoff. On **429** the `Retry-After` is honoured only when it is 5 s or less;
  anything longer abandons the request, and the next cycle retries the batch. Every wait is
  bounded by the caller's deadline.
- **The cycle deadline.** `monitor/cycle.py` opens each cycle with a budget of
  `DEX_CYCLE_INTERVAL_MS` and passes the remaining time into every request. The wrapper
  starts no attempt, and sleeps no backoff and no `Retry-After`, that would run past the
  deadline; it raises instead and the batch is skipped until the next cycle. A cycle
  therefore cannot overrun its interval. Two cycles never overlap either, because the
  scheduler re-arms only after the cycle returns — the shape of the legacy
  `setTimeout` loop (`scheduler.js:30`), kept deliberately.
- `services/dexscreener.py` — `fetch_token_info(address)` and
  `fetch_batch_prices(chain_id, addresses)`; batching, the ≤30 cap and the 1 s inter-batch
  delay live here, not in the cycle. The `/add` lookup runs outside the cycle: it gets the
  retry policy, but no deadline.
- `services/telegram_sender.py` — the FIFO send queue: one message per
  `TG_QUEUE_DELAY_MS`, 429 → requeue at the tail and sleep `min(retry_after, 60)`,
  403 → set the recipient's `deliverable: false` (§6.7) and drop the message. Every send
  attempt and its outcome are logged at INFO; that log is the artefact the dual run
  diffs (§9.3).

## 6. Triage of every issue in INVENTORY.md

Legend: **port as-is** = reproduced deliberately, listed for review · **fix now** =
implemented correctly in the new bot · **decided** = was deferred to the human, now
answered · **answered** = a question, not a defect. Nothing is left deferred.

| Item | Decision | Rationale |
|---|---|---|
| §6.1 `setWebhook` never sends `secret_token` while the server 403s without it | fix now | **Verified against production: the webhook reports a token error and no command is answered.** The check really is unsatisfiable, so this is the reason every command fails — not a cosmetic fix. aiogram registers the secret and validates the header, and §2.1 adds the startup checks on `WEBHOOK_URL`. |
| §6.2 `ensureUser` puts `username` in both `$setOnInsert` and `$set` | fix now | `ConflictingUpdateOperators`, never observable today because §6.1 kills the update before a handler runs — it is the *next* failure once updates arrive. `username` goes in `$set` only, `$setOnInsert` keeps just the creation-time fields. |
| §6.3 `/reset_anchors` calls `utilityCommands.handleResetAnchors`, which is not exported | fix now | A call to a function that does not exist can never have worked; the command is wired to the real handler. |
| §6.4 Price cache keyed on lowercased address, looked up with the raw stored address | fix now | A lookup that can never match is a defect, not a behaviour. Fixed by `chain.normalize_address` on both sides — lowercase for EVM, unchanged for Solana. **Visible consequence: Solana and checksummed-EVM alerts start firing** (see §7). |
| §6.5 `addAlert` raises `Error('DUPLICATE_ALERT')`, caller tests `e.code === 11000` | fix now | Dead error branch; a typed `DuplicateAlertError` restores the "уже отслеживается" message the code always intended to send. |
| §6.6 `alerts.status` written but never changed; `repeat:'always'` never read | port as-is | Both fields are written with the same values, so the documents stay identical for dual-run comparison. Whether a pause feature was planned is a §7 roadmap question, not a fix. |
| §6.7 `users.status:'blocked'` conflates admin ban and user-blocked-the-bot; never cleared | fix now (decided) | The two meanings are split. **`status`** is the admin ban and nothing else, set and cleared only by `/admin block_user` and `/admin unblock_user`. **`deliverable`** is a boolean, set `false` on a Telegram 403 and back to `true` when the user sends any message. The price loop skips a user who is banned **or** undeliverable, so the exclusion set stays what it is today. No migration: legacy documents are handled on read, §9.2. |
| §6.8 Baseline written after the send, per alert (crash re-fires; failed send still advances) | port as-is | Making it atomic changes which alerts fire around a restart, which is exactly what dual-run comparison measures. Listed for review; the atomic variant is in §7. |
| §6.9a Broadcast aborts above 1000 active users instead of batching | fix now (decided) | The refusal is removed. Written now, exercised later: today's audience is one person, but the community reopens (§1.5) and this is the code that has to survive it. The broadcast goes through the existing send queue in batches, so the 429 handling and the `TG_QUEUE_DELAY_MS` pacing already guard against a rate-limit storm. The admin gets a progress line every 100 recipients and a final total, and is asked to confirm before the first send when the audience exceeds 500. `BROADCAST_MAX_USERS` is replaced by `BROADCAST_CONFIRM_THRESHOLD` (500) and `BROADCAST_PROGRESS_EVERY` (100). |
| §6.9b Broadcast text is HTML-escaped, so admins cannot use formatting | port as-is | Escaping also prevents a malformed tag from failing every send in the batch. Enabling admin HTML is an admin-facing decision to make explicitly, not a silent change. |
| §6.10a Downward moves render as `🔻 SYM 5.00%`, no minus sign | port as-is | The arrow already carries the direction and users read this message hundreds of times a day; changing it breaks both expectations and output comparison. |
| §6.10b `formatPrice` has no guard for `price <= 0` | port as-is | Same formatting for the same input, including JS exponent spelling (`1.000e-5`, not Python's `1.000e-05`) — a parity requirement covered by tests. |
| §6.11 Only `update.message` with non-empty text is handled | port as-is | The legacy bot sends no keyboards, so nothing in production can depend on callback queries; `allowed_updates=["message"]` keeps the surface identical. Buttons are §7. |
| §6.12 Deployment facts absent from the repo (Node version, supervisor, `.env` path, Mongo location, TLS) | answered | The legacy bot's own host (Ubuntu 24.04, 1 GB RAM), MongoDB Atlas, a systemd unit with `MemoryMax=` and `EnvironmentFile=` for secrets, and TLS terminated by the nginx already on that host, which gains one `/webhook-v2` location. Written up in §9.1. |
| §4 `TG_QUEUE_DELAY_MS` parsed into config but never read (35 ms hardcoded) | fix now | The variable is a no-op today, so nobody can depend on it; the queue reads it, with 35 ms as the default, preserving current timing. |
| §4 `BLOCKED_USERS_CACHE_TTL_MS` used but missing from `.env.template` | fix now | Documentation-only; the variable is in `.env.example` with its default. |
| §4 `TELEGRAM_TOKEN` re-read and `ADMIN_CHAT_IDS` re-parsed on every call | fix now | `process.env` does not change after `dotenv` loads it, so re-parsing is pure waste with no observable effect. Read once in `config.py`. |
| §5 `condition.baselinePrice` = change since the last alert, accumulating indefinitely | port as-is | This is the product behaviour users experience, however unusual. A rolling-window variant belongs in §7 as a new condition `kind`, not as a redefinition of the existing one. |
| §5 `shutdown()` does not drain the send queue | fix now | Nobody can rely on losing a queued message; shutdown drains for up to `SHUTDOWN_DRAIN_TIMEOUT_MS`, then exits regardless. |
| §2 `fetchWithRetry` does not retry non-2xx, so a DexScreener 429 drops the batch for the cycle | fix now (decided) | 5xx is retried with the existing backoff. On 429 the `Retry-After` is honoured only when it is 5 s or less; a longer one skips the batch and the next 20 s cycle retries it. The cycle deadline in §5 makes the request volume safe: no retry can stretch a cycle past its interval. |
| §2 Retry exhaustion returns a fake `{ok:false, status:0}` response | fix now | An internal sentinel with no user-visible effect; the Python port raises a typed error the caller handles at the same place. |
| §5 `users._id` is the chat id as a **string** | port as-is | Mandatory schema compatibility — both bots must read and write the same documents. |
| Notes `handleAdminCommand` always returns `true`, making `if (handled)` constant | fix now | Dead branch with no behaviour attached; aiogram routers express the same dispatch without it. |
| Notes `getBlockedUsers` scans `users` with no index on `status` | fix now | Pure performance; adding the index changes no result. |
| Notes `/start` ≡ `/help`; `/stop` and `/delete_my_data` differ only in wording | port as-is | User-visible command surface, kept identical including the wording difference. |
| Notes `addAlert` counts alerts of all sources against the subscription limit | port as-is | Identical behaviour while `dex` is the only source; revisit when a second source is added. |
| Notes All user-facing strings are Russian | port as-is | Same strings, same wording — but routed through `bot/texts.py` so localisation is a later addition rather than a rewrite. |
| §3 Node-only cruft: unused `ObjectId`/`ensureUser`/`sleep` imports, redundant `body-parser` | fix now | Not carried over; no equivalent exists in the Python layout. |

### Behaviour changes users will notice

**Every command is broken in production today.** Verified against the running bot: it does
not answer `/help`, and the webhook reports a token error. Only price alerts still work,
which fits exactly — `runCycle` never calls a command handler. An earlier revision of this
document assumed the opposite and called §6.1 and §6.2 apparent no-ops. That was wrong:
§6.1 is *why* every command fails, and §6.2 is what would break them next. There is no
proxy injecting the header and no out-of-band registration.

- **The command surface comes back.** `/start`, `/help`, `/add`, `/list`, `/remove`,
  `/change`, `/change_all`, `/stop`, `/delete_my_data` and the admin panel all start
  answering. Users who tried the bot during the outage and got silence will find it
  responsive.
- **Nothing is replayed.** Telegram has been retrying rejected deliveries, so a backlog of
  up to 24 hours of commands is pending on the token. The cutover registration passes
  `drop_pending_updates=true` (§9.4) so the first minutes after cutover do not act on
  commands users sent days ago and have forgotten.
- **§6.4** — alerts on Solana tokens, and on EVM addresses stored in checksummed form,
  currently never fire. After the fix they fire. Affected users start receiving
  notifications they have never received, with a first-cycle baseline. §9.6 counts those
  alerts off Atlas before cutover, so the traffic change is known in advance rather than
  after.

One inference, flagged as an inference rather than a measurement: with `/add` unreachable,
no alert can have been created since the webhook broke, so the production alert corpus is
frozen. Everything firing today predates the outage. That is what makes the dual-run
comparison in §9.3 meaningful — both bots are evaluating a static set of alerts.

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
2. Storage layer against the existing schema, including the backward-compatible read of
   §9.2, plus a read-only smoke test on a copy.
3. `chains/` with its validation/normalisation tests (the §6.4 fix lands here).
4. `services/` — DexScreener and the send queue, tested against recorded responses.
5. `monitor/` — the cycle and conditions, byte-compared against legacy message output,
   including the watchdog notifier of §9.1.
6. `bot/` — routers and FSM, replacing the sessions Map.
7. `web/` — webhook with a real `secret_token` (§6.1, §2.1).
8. Dual run on the second bot token against a cloned database, output diffed, then the
   cutover of §9.4.

## 9. Deployment, migration and cutover

### 9.1 Host and process

- **The same host as the legacy bot** (`dexscreener-bot-v3`), Ubuntu 24.04, 1 GB RAM, now
  shared with the legacy process as well as everything else on it. With one user, a second
  instance would buy an independence we do not need yet, and retiring the legacy host is a
  separate task for after the cutover. Both bots share the 1 GB, which is what `MemoryMax=`
  is sized against once the dual run has measured the resident set.
- Python 3.12, one virtualenv, `pip install --no-cache-dir`.
- **systemd**, unit checked into `deploy/` with no secrets in it: `EnvironmentFile=` supplies
  `TELEGRAM_TOKEN`, `MONGO_URI` and `WEBHOOK_SECRET`; `MemoryMax=` is set, sized from the
  resident set measured during the dual run rather than guessed now; `Restart=on-failure`.
  Long-running processes are started by systemd, never by hand.
- **Liveness is a systemd watchdog, not an HTTP endpoint.** The unit is `Type=notify` with
  `WatchdogSec=90` — roughly four `DEX_CYCLE_INTERVAL_MS` intervals against the 20 s cycle, so
  ordinary slowness under swap pressure never restarts a bot that is merely slow. The value
  lives in the unit in `deploy/`, with a comment naming that ratio so the two are changed
  together. `monitor/scheduler.py` sends `WATCHDOG=1` to `$NOTIFY_SOCKET` after each completed
  cycle. That is a datagram on a unix socket written with the stdlib `socket` module: no
  dependency, nothing added to §2. `READY=1` is sent once on startup, after the webhook is
  registered and the first cycle has completed. A price loop that stalls without the process
  dying is therefore restarted — the failure `Restart=on-failure` cannot catch on its own.
  Nothing is exposed on the network, there is no `/health` route and no `web/health.py` in the
  §3 layout, and when `NOTIFY_SOCKET` is unset — a local run, a test — the notifier is a
  no-op, never a crash.
- **MongoDB Atlas.** The driver handles TLS to the cluster. One operational precondition is
  already satisfied — the egress address is on the Atlas IP allowlist, because it is the
  legacy bot's — and one remains: `MONGO_MAX_POOL_SIZE` (10, the legacy value) must fit the
  cluster tier's connection limit, checked against 20 for the duration of the dual run, when
  two bots share the cluster (§9.3).
- **TLS is terminated by the nginx already running on this host**, which listens on 80 and
  443 for `dex-alert-bot.duckdns.org` (DuckDNS) with a Let's Encrypt certificate renewed
  there by certbot, valid to 2026-11-27. The bot never handles a certificate, never binds
  443 and has no HTTPS code path. It serves plain HTTP on `WEBHOOK_PORT` and binds
  `WEBHOOK_HOST`. `WEBHOOK_URL` is only the public https address given to Telegram, and
  §2.1 rejects a non-https value at startup. Neither the domain nor the certificate changes,
  now or at cutover.
- **One new nginx location, and the addresses that follow from it.** nginx already proxies
  `https://dex-alert-bot.duckdns.org/webhook` to `http://127.0.0.1:3000/webhook`, the legacy
  bot. The Python bot gets a second location, `/webhook-v2` → `http://127.0.0.1:3001`,
  checked into `deploy/` next to the systemd unit. So:
  `WEBHOOK_HOST=127.0.0.1` — nothing but nginx may reach the process — `WEBHOOK_PORT=3001`,
  the legacy bot holds 3000, `WEBHOOK_PATH=/webhook-v2`, read from the environment and never
  hardcoded, and `WEBHOOK_URL=https://dex-alert-bot.duckdns.org/webhook-v2`. These are the
  defaults in `.env.example`, so a missing `EnvironmentFile` entry cannot make the new bot
  collide with the legacy port.
- **The legacy bot is supervised by PM2** (God Daemon v7.0.1, process list under
  `/home/ubuntu/.pm2`), not by systemd; only the new bot is a systemd unit. Removing PM2 and
  Node.js from the host once the Python bot has proved stable is a separate later task, not
  part of the cutover — §9.4 rollback needs both of them in place.

### 9.2 The `users` schema change, read-compatible

`deliverable: bool` is added and `status` now means the admin ban only (§6.7). **There is no
migration script.** With one user (§1.5) there is nothing to migrate, so the split lands as
mapping rules in `storage/models.py` and query shape in `storage/users.py` instead — which
removes a script, a rollback hazard and the admin-ban question at once.

- **On read:** a missing `deliverable` reads as `true`; a legacy `status: "blocked"`
  document reads as `deliverable: false`.
- **On write:** new writes always use the split fields. No document is ever rewritten in
  bulk, in any collection, by either bot.
- **The loop's exclusion query** covers both shapes at once:
  `{"status": {"$ne": "blocked"}, "deliverable": {"$ne": false}}` — banned or undeliverable
  is skipped, and a legacy document is excluded exactly as it is today.
- The index becomes `{status: 1, deliverable: 1}` instead of the `{status: 1}` planned for
  that query. This is startup schema setup, not migration tooling, so it stays.
- The field is additive and the legacy bot ignores unknown fields, so both bots can run
  against the same schema throughout.

A legacy `blocked` document still cannot say whether an admin banned the user or the user
blocked the bot, so it is read as both and stays excluded either way. Reading it costs
nothing because no such document exists today — one user, not blocked, a number §9.6
confirms off Atlas. Should one ever appear, `/admin unblock_user` clears the ban and the
user's next message restores `deliverable`.

### 9.3 Dual run on a second token

Telegram delivers a token's updates to exactly one webhook registration, so the two bots
cannot share one. The human creates a second BotFather token for the Python bot.

- The Python bot runs as its own unit on the shared host with token #2, the `/webhook-v2`
  address of §9.1, and a **cloned** database — cloned as described below, once per
  comparison window. Production is untouched throughout: the legacy unit keeps token #1,
  port 3000 and the production database, and nothing in nginx moves.
- **Sends are real and they arrive.** There is no dry-run mode and no `DRY_RUN` flag: a
  switch that silently disables all sending is a dangerous thing to carry in a bot whose
  only job is to send. The operator presses **Start** on bot #2 before the window opens, so
  bot #2 is allowed to message them and every send succeeds.
- Consequently **no 403s, `deliverable` stays `true` on the clone, and nothing has to be
  reset between comparison windows** — every cycle in the window is comparable, not just the
  first. This rests on the temporary single-user situation of §1.5: with a real audience,
  the members who never started bot #2 would answer 403, each one would go undeliverable
  after its first cycle, and the dual run would need a different design.
- The comparison uses two artefacts: the queue's INFO send log (§5), which records the
  intended chat id and message text for every attempt, and **the two message streams the
  operator receives** — one per bot, read side by side — for the same cycle window. The
  §6.4 alerts that only the new bot fires are expected extras and are listed separately
  rather than counted as differences.

**How the clone is made.** The Atlas free tier has no snapshot restore, so the clone is a
`mongodump`/`mongorestore` pair into a **second database inside the same cluster**, under a
different name:

```
mongodump    --uri="$MONGO_URI" --out "$TMP/dump"
mongorestore --uri="$MONGO_URI" --drop \
             --nsFrom 'dexalerts.*' --nsTo 'dexalerts_clone.*' "$TMP/dump"
```

- The tools are `mongodb-database-tools`, run by the operator. They are not a project
  dependency and no code in this repository clones anything.
- The Python bot is pointed at the clone with `MONGO_DB_NAME=dexalerts_clone`, which already
  exists in `.env.example` and overrides the database name embedded in the URI; the connection
  string itself is unchanged. The legacy bot cannot be misdirected the same way — it calls
  `client.db()` with no argument (`lib/db.js:25`) and always uses the name in its own URI.
- `--drop` acts only on the namespaces being restored, and both names are visible in the one
  command, so it is checked before it is run. Production is never a restore target.
- Both bots then talk to **one cluster and share its connection budget**: two processes at
  `maxPoolSize` 10 is up to 20 connections, before anything the operator's own tools hold.
  The Atlas precondition in §9.1 is therefore checked against 20 for the duration of the dual
  run, not 10. The clone also doubles the stored data against the tier's storage quota;
  today's corpus is small enough that this is a note rather than a constraint.
- The dump is not a point-in-time snapshot, and it does not need to be: `/add` is unreachable
  in production (§6), so the alert corpus is frozen and `condition.baselinePrice` is the only
  field a concurrent production cycle can move.

**Comparison drift is structural, and it caps the window length.**

Both databases start identical, so the first cycles are directly comparable. They stop being
comparable the moment the two bots write different baselines for the same alert, and that is
guaranteed to happen:

- A §6.4 alert — Solana, or a checksummed EVM address — fires only on the new bot.
  `updateAlertBaseline` (`checkers/dexPriceChecker.js:120`) rewrites `condition.baselinePrice`
  on the clone; production keeps what it holds, which for these alerts is a value written
  before the address stopped matching, or `null`. From that moment the two documents for that
  alert differ permanently.
- Because the baseline is the anchor for the *next* comparison and is reset to the current
  price at every firing (§5, `conditionEvaluator.js:25-40`), the divergence compounds: each
  later firing is measured from a different anchor on each side, so the firings drift further
  apart with every one of them.
- The same happens, more slowly, to alerts both bots fire: two independent 20 s loops sample
  at different instants, each side anchors at a slightly different price, and those
  differences accumulate too.

Three consequences, none of them optional:

- **Windows are short** — hours, not days.
- **Every window starts from a fresh clone.** Re-cloning is the only thing that
  re-synchronises the baselines. `/reset_anchors` is not a substitute: it nulls the baselines
  on one database, so it creates a difference instead of removing one, and it is never run
  against production.
- **Differences observed late in a long window are not evidence of a new defect.** Divergence
  is the expected end state of a long run. Only a difference seen in a window that started
  from a fresh clone counts as a finding.

**The dual-run procedure**, once per window:

1. Drop the previous clone database, if one is left over. Only the clone name is ever dropped.
2. `mongodump` production and `mongorestore` under the clone name, as above.
3. In the new unit's `EnvironmentFile`: token #2 in `TELEGRAM_TOKEN`, the clone name in
   `MONGO_DB_NAME`. `MONGO_URI` is otherwise production's.
4. Start the unit. Check that bot #2 answers `/help`, and that the operator has pressed Start
   on it so no send can 403.
5. Run the window. Read the two message streams side by side against the queue's INFO send
   log (§5).
6. Stop the unit. Write down the differences; list the §6.4 extras separately.
7. For the next window, return to step 1. A clone is never reused across windows.

### 9.4 Cutover

The old bot is stopped **before** the new one claims the token. The reverse order would run
two price loops against the same production documents: users would get each alert twice and
both loops would write `condition.baselinePrice` on the same alerts.

1. The dual-run diff is clean apart from the expected §6.4 extras.
2. Record `getWebhookInfo` on the production token: `pending_update_count` and
   `last_error_message`. This is where the token error is visible, and the count says how
   large a backlog step 4 is about to discard.
3. Stop the old bot under PM2 — it is a PM2 process, not a systemd unit (§9.1). Take the
   process name from `pm2 list`, then:

   ```
   pm2 stop <name>
   pm2 delete <name>
   pm2 save
   ```

   Save `pm2 describe <name>` — script path, cwd, interpreter, env — before the `delete`:
   the repository has no `ecosystem.config.js`, so once the entry is gone from the process
   list, step 6 needs those values to bring it back.

   All three matter. Killing the process instead makes PM2 restart it immediately, which is
   exactly the two-bots-on-one-token state this step exists to prevent, and without
   `pm2 save` the saved process list survives and PM2 resurrects the bot on the next reboot.
   Its price loop ends here. Leave its working directory, its environment file and its
   `/webhook` nginx location intact for the rollback; port 3000 simply falls idle.
4. Put the production `TELEGRAM_TOKEN`, the production `MONGO_URI` and the real
   `ADMIN_CHAT_IDS` into the new unit's `EnvironmentFile`, then start it. Startup calls
   `setWebhook` with the secret token, `allowed_updates=["message"]` and
   `drop_pending_updates=true` — which redirects the production token to `/webhook-v2` and
   discards the backlog Telegram accumulated while every delivery was being rejected. The
   URL is the one the dual run already used, so there is no nginx edit, no certificate step
   and no DNS change at cutover. There is no data step either: §9.2 changed nothing in the
   database.
5. Watch the first cycles: alert volume against the dual-run figures, resident set against
   `MemoryMax`, Atlas connection count, and whether commands now answer.
6. **Rollback:** start the old bot again with `pm2 start <name>`, not a `systemctl` call —
   from the entry step 3 recorded, if PM2 no longer knows the name after the delete. It
   calls `setWebhook` with its own `WEBHOOK_URL` at startup and re-claims the token — that
   part is unchanged — so rollback is that one command plus stopping the new unit; its
   `/webhook` location was never removed from nginx, so the address it registers still
   resolves to it. Nothing has to be restored, because no document was ever
   bulk-rewritten: the
   old bot ignores the `deliverable` field it does not know about, and a user the new bot
   marked undeliverable is simply retried until its own 403 sets `status: "blocked"`, which
   is what it does today.

### 9.5 `.env.example` changes

These land with the implementation, not with this document:

- remove `BOT_MODE` — one transport (§2.1);
- remove `BROADCAST_MAX_USERS`; add `BROADCAST_CONFIRM_THRESHOLD` (500) and
  `BROADCAST_PROGRESS_EVERY` (100), §6.9a;
- add `DEX_RETRY_AFTER_MAX_MS` (5000), the 429 threshold of §5;
- update the `HTTP_RETRY_*` comments: 5xx is retried, and the cycle deadline bounds
  every wait.

### 9.6 To measure, not to decide

Three numbers to read off the database before the cutover, none of them a question for
anyone. **Manual checks, not code:** the operator reads the first two in Atlas and the third
from `getWebhookInfo`. No script, no counting queries in the delivery order.

1. Alerts whose stored address differs from its normalised form — the size of the §6.4
   traffic change.
2. The count of `status: "blocked"` users, expected to be zero — this confirms that the
   legacy-document read path of §9.2 is empty in practice today.
3. `pending_update_count` on the production token (§9.4 step 2).
