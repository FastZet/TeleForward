# TeleRoute MTProto Core

Self-hosted Telegram personal-account message automation, deterministic media classification, caption transformation, and historical backfill platform.

## 1. Architecture Proposal & Modular Monolith Design

TeleRoute MTProto Core is architected as a single-binary **modular monolith** backed by embedded **SQLite in WAL mode** (`PRAGMA journal_mode = WAL; PRAGMA busy_timeout = 5000; PRAGMA foreign_keys = ON;`) for low-memory Linux VPS deployments (512 MB–1 GB RAM), with an optional PostgreSQL profile for multi-replica installations.

### Domain Module Boundaries (`src-rust/` & `src/server/`)

| Module | Responsibility |
| :--- | :--- |
| `api` | Versioned `/api/v1/*` REST routes, administrative session & CSRF middleware, SSE real-time stream (`/api/v1/events`). |
| `telegram` | MTProto personal-account session lifecycle, phone login code & 2FA challenge flow, dialog discovery, bounded history scanning, forward/copy execution, and source edit/delete listener isolated behind the `TelegramAdapter` trait. |
| `rules` | Rule domain models, priority ordering (`priority DESC, secondary_order ASC, id ASC`), exclusive-stop semantics, and non-destructive dry-run rule testing. |
| `filters` | Typed message-type filter (`ALL`, `TEXT_ONLY`, `MEDIA_ONLY`, `PHOTO`, `VIDEO`, `DOCUMENT`, `AUDIO`, `VOICE`), numeric sender ID & admin/verified filters, ANY/ALL keyword filters, linear-time regex filters (`regex` crate with size/length caps), and byte-accurate file filters. |
| `classifier` | Offline, deterministic release classifier detecting `MOVIE`, `TV_SHOW`, `COMBINED`, and `SPLIT` categories from filenames and captions with `ALL` vs `ANY` matching. |
| `transform` | Deterministic 6-stage Copy-mode caption transformation pipeline (clean-filename mode, trailing promo stripping after extension while preserving `.001` multipart suffixes, link/@username/#hashtag/emoji/symbol cleanup, ordered regex/literal replacements, header/footer injection, and 1024/4096 length validation). |
| `router` | Evaluates active rules for a source message, respects `exclusive_stop` only after a confirmed match, checks persistent deduplication (`PER_RULE` or `PER_DESTINATION`), and emits atomic delivery jobs. |
| `queue` | Durable SQLite-backed asynchronous delivery queue with configurable concurrency, per-rule delay (0–120s), global send delay, minimum send interval, `FLOOD_WAIT_X` deferral, and bounded exponential backoff. |
| `backfill` | Historical message scanner supporting `ALL_ACCESSIBLE`, `LAST_N` (50–5,000), `UNPROCESSED_ONLY`, and `MESSAGE_ID_RANGE`, oldest-first/newest-first direction, dry-run preview, pause/resume/stop/restart, and crash-resilient cursor persistence. |
| `catchup` | Startup (`auto_catchup_on_startup`) and manual gap detection comparing `source_cursors.last_processed_message_id` against the source chat's latest message ID. |
| `sync` | Tracks `source_message_id -> destination_message_id` mappings in `message_mappings` to propagate source caption edits (in Copy mode) and source message deletions. |
| `storage` | Normalized 17-table relational schema, transactional job/dedup writes, WAL checkpointing, and safe online backup (`VACUUM INTO`). |
| `scheduler` | IANA timezone (`chrono-tz` / `Intl`) schedule window evaluator supporting overnight windows crossing midnight and configurable arrival vs deferral semantics. |
| `observability` | Redacted operational event logs (`app_events`), persistent aggregate counters (`stats_counters`), and `/api/v1/health` readiness probes. |
| `security` | Argon2id/scrypt administrator password hashing, AES-256-GCM encryption for Telegram session material at rest, `HttpOnly`/`SameSite=Lax` session cookies, CSRF validation, and rate limiting. |

---

## 2. Feasibility Assessment of Rust MTProto (`grammers` v0.7) & Telegram API Limitations

| Telegram Operation | Support in `grammers-client` / MTProto | Implementation & Honest Limitations |
| :--- | :--- | :--- |
| Personal account login (API ID/Hash + Phone + Code) | **Supported** (`request_login_code`, `sign_in`) | Protected by `LoginFlowLock` mutex so concurrent browser requests cannot corrupt the pending login token. |
| 2FA cloud password (`SessionPasswordNeeded`) | **Supported** (`check_password`) | Password is verified via SRP and zeroized immediately; never logged or stored. |
| Session persistence & auto-reconnect | **Supported** (`grammers-session`) | Serialized session bytes are encrypted with **AES-256-GCM** using `SESSION_ENCRYPTION_KEY` before saving to `telegram_session_encrypted`. |
| Dialogs & chat inspection (Channels, Supergroups, Groups, Private) | **Supported** (`iter_dialogs`) | Uses stable numeric peer IDs (`-100...` for channels/supergroups, `-...` for groups, positive for users). |
| Historical message iteration & ID ranges | **Supported** (`iter_messages`) | Fetched in bounded pages (`BACKFILL_BATCH_SIZE`, default 50–100) so large histories never accumulate in RAM. |
| Forward mode (with attribution) | **Supported** (`forward_messages`) | Preserves native Telegram `FwdFrom` header. Cannot modify captions or strip attribution in Forward mode. |
| Copy mode (without attribution + transformed caption) | **Supported with documented limits** | Re-sends existing media handle (`InputMedia`) with transformed caption without re-uploading bytes. **Limitation:** Channels with Telegram's `noforwards` ("Restrict saving content") flag block both Forward and server-side media reference copying; attempting to copy from a protected chat returns `CHAT_FORWARDS_RESTRICTED` (classified as permanent error, not retried). |
| Media albums / grouped messages (`grouped_id`) | **Partially supported** | Each rule provides an explicit `album_policy` (`PROCESS_ITEMS`, `FIRST_ITEM_ONLY`, `SKIP_ALBUMS`). In Copy mode, album items are delivered with caption transformations applied to the captioned item. |
| Source edit synchronization | **Supported for Copy mode only** | Telegram's MTProto protocol does not permit editing the text/caption of a native forwarded message (`FORWARD` mode). Edit sync updates tracked `COPY` mode destination messages and logs `UNSUPPORTED_FORWARD_MODE` if invoked on a forwarded message. |
| Source delete synchronization | **Supported with permission limits** | Uses `UpdateDeleteChannelMessages` / `UpdateDeleteMessages`. Note: Telegram only emits delete updates containing message IDs (without peer ID in non-channel chats unless already cached in `message_mappings`). Furthermore, in broadcast channels where the user lacks `delete_messages` admin rights, deletion fails with `MESSAGE_DELETE_FORBIDDEN`. |
| Exactly-once delivery guarantee | **At-least-once with narrow crash window** | Telegram MTProto does not support distributed two-phase commit with local SQLite. A job is marked `PROCESSING` before `send_message`/`forward_messages` and committed as `COMPLETED` + recorded in `deduplication_records` immediately upon RPC return. If the VPS loses power in the ~5ms window *after* Telegram accepts the packet but *before* SQLite commits, a restart recovery could re-send that single message. |

---

## 3. Repository Structure

```text
├── Cargo.toml                         # Pinned Rust dependencies (Axum, Tokio, SQLx, Grammers, Regex, AES-GCM)
├── Dockerfile                         # Multi-stage build (Frontend -> Rust release -> Non-root Debian slim)
├── compose.yaml                       # Docker Compose (Default SQLite WAL + optional Postgres & Caddy HTTPS)
├── .env.example                       # Documented environment variables
├── migrations/
│   └── 0001_initial_schema.sql        # Normalized 17-table schema with indexes & foreign keys
├── recipes/
│   ├── simple-mirror.json             # Recipe 1: 1:1 chat mirror
│   ├── movies-clean-captions.json     # Recipe 2: Movie routing with caption cleanup
│   ├── keyword-and-schedule.json      # Recipe 3: 2160p UHD filter + overnight schedule
│   └── media-routing-rules.json       # Recipe 4: 6-tier ordered priority routing taxonomy
├── src-rust/                          # Rust modular monolith source & unit tests
│   ├── main.rs
│   ├── lib.rs
│   ├── api.rs
│   ├── telegram.rs
│   ├── rules.rs
│   ├── filters.rs
│   ├── classifier.rs
│   ├── transform.rs
│   ├── router.rs
│   ├── queue.rs
│   ├── backfill.rs
│   ├── catchup.rs
│   ├── sync.rs
│   ├── storage.rs
│   ├── scheduler.rs
│   ├── observability.rs
│   ├── security.rs
│   └── tests.rs
├── server.ts                          # Full-stack runtime server for interactive web preview & SQLite execution
├── src/
│   ├── server/                        # SQLite WAL engine, MTProto adapter, classifier, router, queue & tests
│   └── ...                            # React + TypeScript + Tailwind CSS + TanStack Query UI
└── docs/
    └── ARCHITECTURE.md                # Deep-dive schema, state machines, security, backup & benchmark guide
```

---

## 4. Deployment, Upgrades, Backup & Restoration

### Quick Start (Default SQLite Deployment on Linux VPS)

```bash
cp .env.example .env
# Generate required 32-byte cryptographic secrets:
sed -i "s/^SESSION_ENCRYPTION_KEY=.*/SESSION_ENCRYPTION_KEY=$(openssl rand -hex 32)/" .env
sed -i "s/^ADMIN_SESSION_SECRET=.*/ADMIN_SESSION_SECRET=$(openssl rand -hex 32)/" .env

docker compose up -d --build
```

Open `http://127.0.0.1:3000` (or via your HTTPS reverse proxy) to complete the **Initial Administrator Setup** and connect your Telegram account.

### Safe Online SQLite Backup & Restoration

Because SQLite runs in WAL mode, never copy `teleroute.db` without `.db-wal` or while writes are active. Instead, use the built-in online snapshot command or API endpoint (`POST /api/v1/maintenance/backup`):

```bash
# Safe atomic online backup while container is running:
docker exec teleroute sqlite3 /data/teleroute.db "VACUUM INTO '/data/teleroute-backup-$(date +%F).db';"
docker cp teleroute:/data/teleroute-backup-$(date +%F).db ./
```

**To Restore:**
1. Stop the container: `docker compose stop teleroute`
2. Replace `/data/teleroute.db` (and remove any stale `/data/teleroute.db-wal` and `/data/teleroute.db-shm`).
3. Ensure `SESSION_ENCRYPTION_KEY` in `.env` matches the key used when the backup was created.
4. Start the container: `docker compose start teleroute`

### Updating the Container Without Losing Data
```bash
git pull
docker compose build --pull
docker compose up -d
```
All persistent data resides in the `teleroute_data` Docker volume mounted at `/data`. Automatic SQL migrations run idempotently on startup.

---

## 5. Feature-Completion Matrix

| Subsystem / Requirement | Status | Verification Notes |
| :--- | :--- | :--- |
| Administrator Setup & Auth (`HttpOnly` cookie, CSRF, rate limiting) | **Implemented and tested** | Enforces initial setup with no default credentials; verified in automated test suite. |
| Personal-Account Telegram MTProto Auth (API ID/Hash, Phone, Code, 2FA, AES-256-GCM session persistence) | **Implemented and tested** | Real MTProto flow (`Grammers` in Rust / `GramJS` in Node runtime) + encrypted session storage in `telegram_session_encrypted`. |
| Chat & Destination Management (Channels, Supergroups, Groups, Private) | **Implemented and tested** | Searchable, filterable by type, stable numeric peer IDs, explicit permission flags (`can_read`, `can_send`, `can_edit`, `can_delete`). |
| Rule CRUD, Priority (0–100), Deterministic Tie-Break & Exclusive-Stop | **Implemented and tested** | Full 10-section editor, inline validation, duplicate, reorder, enable/disable, and dry-run Rule Tester. |
| Filters: Message Type, Numeric Sender IDs, Keywords, Safe Regex, File Size/Name/Extensions | **Implemented and tested** | Verified by unit tests covering positive/negative cases, missing metadata policies, and regex validation. |
| Offline Media Classifier (`MOVIE`, `TV_SHOW`, `COMBINED`, `SPLIT` + `ALL`/`ANY`) | **Implemented and tested** | Deterministic regex classifier with unit tests for standard, combined pack, multipart split, and ambiguous filenames. |
| Copy-Mode Caption Transformation Pipeline & Live Preview | **Implemented and tested** | Deterministic 6-step pipeline preserving `.001` multipart suffixes and enforcing 1024/4096 char limits. |
| Durable Delivery Queue, Pacing, Flood-Wait Deferral & Persistent Deduplication (`PER_RULE` / `PER_DESTINATION`) | **Implemented and tested** | SQLite transactional job queue with idempotency keys, retry attempts tracking, and cancellation. |
| Historical Backfill (4 Modes, Oldest/Newest First, Dry-Run Preview, Pause/Resume/Stop/Restart) | **Implemented and tested** | Bounded batch scanning with incremental cursor persistence in `backfill_jobs`. |
| Automatic & Manual Missed-Message Catch-Up (`source_cursors`) | **Implemented and tested** | Detects message-ID gaps per source chat and enqueues missed messages idempotently. |
| Source Edit & Delete Synchronization (`message_mappings`) | **Implemented and tested** | Tracks created destination messages; propagates edits (Copy mode) and deletions. |
| Operational Logs (Redacted, Paginated) & Persistent Statistics (`stats_counters`) | **Implemented and tested** | Counters survive log retention cleanup; full filterable log viewer. |
| Rule JSON Export, Validated Import with Preview & ID Remapping, and 4 Built-in Recipes | **Implemented and tested** | Ships with `simple-mirror`, `movies-clean-captions`, `keyword-and-schedule`, and `media-routing-rules`. |
| Protected Content (`noforwards`) Bypass | **Unsupported by Telegram API / Policy** | Intentionally rejected with `CHAT_FORWARDS_RESTRICTED` per security requirements. |
