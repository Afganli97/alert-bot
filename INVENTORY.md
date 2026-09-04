# Inventory — legacy Node.js bot

`dex-alerts-bot` v2.0.0, tip `751fc81`, remote `Afganli97/DEX_alert_bot`. ~1.2k lines of handlers + ~700 lines elsewhere, 17 Jest test files.

## 1. Entry point and startup

`package.json` → `main: index.js`, `start: node index.js`.

`index.js:82 main()`:
1. `dotenv.config()` — reads `.env` from cwd (`index.js:4`, again `webhookServer.js:1`).
2. `connectToMongo(MONGO_URI)` (`lib/db.js:6`) — validates URI prefix, connects, pings `admin`, creates three `alerts` indexes.
3. `initializeModules()` (`index.js:18`) — injects the `users`/`alerts` collections into `lib/users`, `lib/telegram` (constructs `TelegramQueue`), `checkers/dexPriceChecker`, `handlers/commands`.
4. `startScheduler(ctx)` (`scheduler.js:21`) — self-rescheduling `setTimeout` loop (not `setInterval`); runs `runCycle` immediately, then every `DEX_CYCLE_INTERVAL_MS` (20 s).
5. `startSessionCleanup()` (`sessionCommands.js:40`) — `setInterval`, 5 min.
6. `startWebhookServer()` (`webhookServer.js:8`) — Express listener.
7. `setTelegramWebhook()` (`index.js:40`) — once per start; skipped with a warning if `WEBHOOK_URL` is unset.
8. `SIGINT`/`SIGTERM` → `shutdown()` (`index.js:66`): sets `global.shuttingDown`, polls `ctx.isChecking` every 500 ms until the cycle ends, closes HTTP + Mongo, `exit(0)`. Startup errors → `exit(1)`.

No Dockerfile, systemd unit, PM2 file, or `engines` field in the repo. `fetch`/`AbortController` are used as globals, so Node 18+ (`dexPriceChecker.js:3` says so).

**On this machine there is no `node`, no `node_modules`, no `.env`, no matching process and no systemd unit** — production runs elsewhere, and I could not inspect it.

## 2. External services

Four outbound call sites, two hosts. No RPC endpoints, no chain access, no other third party.

**Telegram Bot API** — `https://api.telegram.org`
- `POST /bot<TOKEN>/setWebhook` — `index.js:47`, body `{url: WEBHOOK_URL}`. **No `secret_token`.**
- `POST /bot<TOKEN>/sendMessage` — `telegramQueue.js:70`, body `{chat_id, text, parse_mode:'HTML', disable_web_page_preview:true}`.
- **Inbound**: `POST {WEBHOOK_PATH}` (default `/webhook`) on `WEBHOOK_PORT` (default 3000), `webhookServer.js:20`. Requires header `x-telegram-bot-api-secret-token == WEBHOOK_SECRET` else 403. Handles `update.message` only; always answers 200.

**DexScreener** — `https://api.dexscreener.com`, unauthenticated
- `GET /tokens/v1/{chainId}/{a1,a2,…}` — `dexPriceChecker.js:49`, batch poll, ≤30 addresses, 1 s between batches.
- `GET /latest/dex/tokens/{address}` — `tokenCommands.js:27`, one-shot lookup during `/add`.

Both via `lib/fetchWithRetry.js`: 3 attempts, 15 s abort timeout, 2 s backoff doubling. Retries **network/timeout errors only** — a non-2xx (e.g. DexScreener 429) is returned as-is and the batch is dropped for that cycle. On exhaustion returns a fake `{ok:false, status:0, json:()=>({})}`.

**MongoDB** — `MONGO_URI`, must start `mongodb://` or `mongodb+srv://`. Pool `maxPoolSize 10 / minPoolSize 1`, `serverSelectionTimeoutMS 5000`, `socketTimeoutMS 45000`, `connectTimeoutMS 10000`. DB name comes from the URI path (`client.db()` with no arg).

## 3. npm dependencies

| Package | Locked | Used for |
|---|---|---|
| `mongodb` | 5.9.2 | `MongoClient` (`db.js:1`); `ObjectId` is imported at `alertCommands.js:5` but **never used** |
| `express` | 4.22.2 | webhook server, one POST route |
| `body-parser` | 1.20.6 | `bodyParser.json()` (`webhookServer.js:10`) — redundant, Express 4.16+ has `express.json()` |
| `dotenv` | 17.4.2 | loads `.env` |
| `bs58` | 6.0.0 | Solana validation only: `decode(addr).length === 32` (`alertCommands.js:49`). Imported as `require('bs58').default` |

Dev: `jest` 30.4.2, `eslint` 9.39.5 + `@eslint/js` (flat config, globals listed by hand). 477 packages total in the lockfile (v3), nearly all transitive. No HTTP client dependency — global `fetch`.

## 4. Configuration and secrets

All env vars via `dotenv`; `.env` gitignored, `.env.template` checked in. Nothing read from a config file or the DB.

Direct `process.env` reads: `TELEGRAM_TOKEN` (secret, read per request — not cached), `MONGO_URI` (secret), `WEBHOOK_SECRET` (secret; server throws if unset), `WEBHOOK_URL`, `WEBHOOK_PORT` (3000), `WEBHOOK_PATH` (`/webhook`), `ADMIN_CHAT_IDS` (comma-separated, **re-parsed on every `isAdmin()` call**, `users.js:82`).

Via `config.js num()`: `DEX_CYCLE_INTERVAL_MS` 20000, `DEX_BATCH_SIZE` 30, `DEX_BATCH_DELAY_MS` 1000, `TG_QUEUE_DELAY_MS` 35, `SUBSCRIPTION_LIMIT_{BASIC,PRO,PREMIUM}` 5/15/50, `BLOCKED_USERS_CACHE_TTL_MS` 300000.

Two mismatches: `TG_QUEUE_DELAY_MS` is parsed into `config.telegram.queueDelayMs` and **never read** — `telegramQueue.js:56` hardcodes `sleep(35)`, so the variable is a no-op. `BLOCKED_USERS_CACHE_TTL_MS` is used (`dexPriceChecker.js:29`) but missing from `.env.template`.

## 5. Persistent state

**MongoDB only.** No files written, no local cache, no Redis.

`users` — `_id` is the chat id **as a string**:
```js
{ _id:"123", username:string|null, createdAt:Date,
  status:"active"|"blocked", subscription:"basic"|"pro"|"premium", lastActivityAt:Date }
```
Written by `ensureUser` (upsert on every message), admin block/unblock, `set_subscription`, and by the queue on Telegram 403 (`telegramQueue.js:85`). No index beyond `_id`.

`alerts` — one doc per (user, token):
```js
{ _id:ObjectId, ownerId:"123", source:"dex",
  target:{chain:"ethereum", address:"0x…"},
  condition:{kind:"percent_change", changePercent:10, baselinePrice:null|Number},
  repeat:"always", status:"active", name:"symbol", createdAt:Date }
```
Indexes created at startup (`db.js:27-33`): `{source,status}`, `{ownerId}`, unique `{ownerId,'target.chain','target.address'}`.

`condition.baselinePrice` is the anchor and the only field the hot loop mutates: `null` at creation → set on the first cycle that sees a price → reset to current price each time an alert fires. So the semantics are **percent change since the last alert**, not a rolling window; sub-threshold moves accumulate indefinitely.

**In-memory, lost on restart:** `sessions` Map (`sessionCommands.js:21`, multi-step flow state, 30 min idle eviction) · `commandTimestamps` Map (rate limit, 10 cmd/60 s per chat) · `blockedUsersCache` (Set, 5 min TTL, invalidated by admin block/unblock) · `TelegramQueue.queue` (unbounded FIFO, ~35 ms/send ≈ 28 msg/s; on 429 the message goes to the **tail** and the whole queue sleeps `min(retry_after, 60)` s; on 403 the user is marked blocked and the message dropped). `shutdown()` does not drain the queue.

## 6. Open questions

Several of these look like live bugs. Per the working agreement I have not touched them.

1. **The webhook secret looks unsatisfiable.** `setWebhook` sends only `{url}` (`index.js:52`) — never `secret_token` — but the server 403s anything without a matching `x-telegram-bot-api-secret-token` header, and refuses to start without the variable. As written, Telegram would never send that header and every update would be rejected. Is the webhook registered out-of-band, or does a proxy inject the header?

2. **`ensureUser` puts `username` in both `$setOnInsert` and `$set`** (`users.js:60-69`) — normally a `ConflictingUpdateOperators` error. Git history shows the team hitting exactly that (`21c055b`, `118df23`) and then re-adding the field "for test compatibility" (`b301db0`). The test mocks the collection, so it proves nothing. Does this throw in production? If so, every command dies in the `handleMessage` catch and users only see "❌ Произошла ошибка", while price alerts keep working (`runCycle` never calls `ensureUser`).

3. **`/reset_anchors` calls a function that does not exist.** `commands.js:75` calls `utilityCommands.handleResetAnchors`, but that function is in `sessionCommands.js:449` and `utilityCommands.js` does not export it → TypeError → generic error. `test/commands.test.js:33` mocks `utilityCommands` *with* the method, so the suite passes.

4. **Token address case.** Addresses are stored exactly as typed (`alertCommands.js:92`, deliberate for base58), but the price cache is keyed on `baseToken.address.toLowerCase()` (`dexPriceChecker.js:62,169`) while the lookup uses the raw stored address (line 184). Any checksummed EVM or Solana address should miss the cache and never fire. Both tests use the literal `'0xabc'`. Since the bot demonstrably sends alerts — do users paste lowercase, or is only a subset firing?

5. **Duplicate-token message is dead code.** `addAlert` converts Mongo `11000` into `new Error('DUPLICATE_ALERT')` (`alertCommands.js:106`), but the caller checks `e.code === 11000` (`sessionCommands.js:428`), which the new Error doesn't carry. Users get the generic failure instead of "уже отслеживается".

6. **`alerts.status` is write-only** — set to `'active'`, filtered on by `getDexAlerts`, never changed; `getUserAlerts` ignores it. Was a pause feature planned? Same for `repeat:'always'`, stored and never read.

7. **`users.status:'blocked'` conflates two meanings** — admin ban vs. user blocked the bot (`telegramQueue.js:85`). Nothing clears it: `ensureUser` never restores `'active'`. A user who blocks then unblocks the bot stays excluded from the price loop forever.

8. **Baseline is written after the send, per alert** (`dexPriceChecker.js:217-225`). A crash or shutdown between the two re-fires the alert; a failed send still advances the baseline.

9. **Broadcast**: >1000 active users aborts the whole broadcast instead of batching (`sessionCommands.js:126`), and the text is HTML-escaped (line 140) so admins cannot use formatting.

10. **Message formatting**: downward moves render as `🔻 SYM 5.00%` with no minus sign — `sign` is `''` for `down` and `changePct` is already absolute (`dexPriceChecker.js:202-205`). `formatPrice` has no guard for `price <= 0`.

11. **Update scope**: only `update.message` with non-empty text. No callback queries, inline keyboards, or `edited_message`. Confirm nothing in production depends on button UI.

12. **Deployment facts not in the repo**: Node version, process supervisor, `.env` location, MongoDB local vs Atlas, and what terminates TLS in front of the webhook.

**Smaller notes:** `index.js:6` imports `ensureUser`/`isAdmin` and declares `client`, all unused; `telegram.js:5` imports `sleep` unused · `handleAdminCommand` always returns `true`, so the `if (handled)` guard at `commands.js:106` is constant · `/start` ≡ `/help`; `/stop` and `/delete_my_data` differ only in wording · `addAlert` counts all sources for the subscription limit though only `dex` exists · `getBlockedUsers` scans `users` with no index on `status` · all user-facing strings are Russian.

---

**Not verified:** I read the source only. With no Node runtime, no `node_modules` and no `.env` here, I did not run the test suite and reproduced none of the suspected bugs against a live MongoDB or Telegram. Items 1–4 in particular need confirmation against production before anything is ported.
