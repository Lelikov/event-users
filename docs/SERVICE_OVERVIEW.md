# event-users: Service Overview

## Domain

User and contact management service with background CRM synchronisation. Maintains the canonical user registry consumed by other services in the event-driven system.

- **Users** are uniquely identified by `(email, role)` where role is `client` or `organizer`.
- **User contacts** store communication channel identifiers (Telegram, push tokens, email) per user.
- `participants.user_id` in `event-saver`'s database references the UUID primary key from this service.

## Subsystems

| Subsystem | Entry point | Toggle |
|-----------|-------------|--------|
| HTTP API (`/api/users`) | `routes.py` | always on |
| CRM background sync | `crm/sync.py` (`CrmSyncRunner`) | `IS_SYNC_ENABLED` (default `false`) |
| RabbitMQ consumer (`events.user.email`) | `consumer.py` (`EmailChangeConsumer`) | `IS_CONSUMER_ENABLED` (default `true`) |
| CRM webhook outbox poller | `webhook/sender.py` (`WebhookOutboxSender`) | `IS_WEBHOOK_ENABLED` (default `false`) |
| event-admin cache invalidation | `adapters/cache_notifier.py` | `EVENT_ADMIN_URL` set |

## CRM Sync

A background asyncio task started in the FastAPI lifespan periodically fetches user data from an external CRM API and upserts it into the local database.

| Aspect | Detail | Source |
|--------|--------|--------|
| Frequency | Every `CRM_SYNC_INTERVAL_SECONDS` (default 300 s); exponential backoff on repeated failures (interval × 2^failures, capped at `CRM_SYNC_MAX_BACKOFF_SECONDS`) | `crm/sync.py` (`CrmSyncRunner`) |
| Transport | HTTPS GET to `{CRM_API_URL}/users` with Bearer token auth, paginated (page_size=100), shared `httpx.AsyncClient` | `crm/client.py` |
| Encryption | AES-256-CBC; IV per response, key from `CRM_ENCRYPTION_KEY` (64-char hex = 32 bytes) | `crm/sync.py` (`decrypt_payload`) |
| Error handling | Payload-level failures raise `CrmDecryptError` (cycle fails, backoff kicks in); malformed individual records are quarantined and counted | `crm/sync.py` |
| Transactions | One commit per page; a failure on a later page keeps earlier pages | `CrmSyncService.sync` |
| Admin guard | One `get_admin_changed_email_roles()` query per cycle; CRM records matching an admin-changed old email are skipped | `adapters/changelog_db.py` |
| Upsert | `INSERT ... ON CONFLICT (email, role) DO UPDATE` with `COALESCE` for name/time_zone, `RETURNING id`; flips `email_source` back to `'crm'` on convergence | `adapters/users_db.py` (`upsert_user_from_crm`) |
| Accounting | `SyncReport` (synced / skipped_admin_guard / quarantined) logged per cycle; runner tracks `last_success_at` and `consecutive_failures` | `crm/sync.py` |

## Email Change Flow (admin-initiated)

Both paths have identical semantics:

1. **RabbitMQ path**: `user.email.change_requested` (CloudEvent, queue `events.user.email`) → `handle_email_change`. Idempotent on `ce-id` (unique `user_email_changelog.message_id`).
2. **REST path**: `PATCH /api/users/id/{user_id}` with a new email → controller.

Both write, in one transaction: `users.email` + `email_source='admin'`, the email contact, a `user_email_changelog` entry, and a `webhook_outbox` row (`user.email.changed` → CRM). The cache invalidation to event-admin fires only after commit.

`email_source='admin'` arms the CRM-sync guard so the sync cannot resurrect the old email as a duplicate user. It flips back to `'crm'` only when the CRM export converges on the new email (upsert conflict), not when the webhook is merely delivered.

## Webhook Outbox

Two-phase poller, safe with multiple replicas: (1) claim a batch atomically (`status='processing'`, `next_retry_at` pushed by `WEBHOOK_VISIBILITY_TIMEOUT_SECONDS`, `FOR UPDATE SKIP LOCKED`), commit; (2) deliver each row and finalize (`delivered` / `pending` with quadratic backoff / `failed` after `max_attempts`).

## user_contacts

Each user may have zero or more contacts. A contact is a `(channel, contact_id)` pair, unique per user.

- **Channels**: `email` (auto-created on user create/update), `telegram`, `push`, etc.
- **Population**: via API (`contacts` array) or CRM sync; upserts are batched into a single `unnest()` statement.
- **Constraint**: `UNIQUE(user_id, channel)`; `ON DELETE CASCADE` from `users.id`.

## Runtime Dependencies

| Dependency | Purpose | Config var |
|------------|---------|------------|
| PostgreSQL (asyncpg) | User/contact storage | `POSTGRES_DSN` |
| External CRM API | Source of truth for user data (when sync enabled) | `CRM_API_URL`, `CRM_API_TOKEN` |
| RabbitMQ | `events.user.email` consumer (declares + binds the queue itself) | `RABBIT_URL` |
| CRM webhook endpoint | Outbound `user.email.changed` delivery | `CRM_WEBHOOK_URL`, `CRM_WEBHOOK_TOKEN` |
| event-admin | Cache invalidation notifications (outbound POST) | `EVENT_ADMIN_URL`, `EVENT_ADMIN_CACHE_TOKEN` |

## Environment Variables

See `.env.example` for the complete list with defaults. Required (no default): `POSTGRES_DSN`, `JWT_SECRET_KEY`, `CRM_API_URL`, `CRM_API_TOKEN`, `CRM_ENCRYPTION_KEY`.

Notable optional vars: `JWT_AUDIENCE`/`JWT_ISSUER` (aud/iss claim binding — enforced only when set; coordinate with event-admin token minting), `API_BEARER_TOKEN` (static service token, grants `role=admin`, compared constant-time), `IS_CONSUMER_ENABLED` (default `true` — the queue is always bound, so a disabled consumer means unbounded accumulation), `CRM_SYNC_MAX_BACKOFF_SECONDS`, `WEBHOOK_VISIBILITY_TIMEOUT_SECONDS`.

## Known Limitations

1. **COALESCE in upsert prevents clearing fields** — intentional: CRM `null` means "not provided", not "clear this field" (`adapters/users_db.py`).
2. **No index on `user_contacts.channel`** — channel-wide reverse lookups are unsupported; add the index with the first consumer that needs it.
3. **App import requires a populated `.env`** — `Settings` has required fields with no defaults; tooling that imports `main.py` needs at least the values from `.env.example`.
4. **`GET /roles/{role}/emails/{email}` is deprecated** — use `GET /api/users/by-identity` (query params); the path variant is kept until event-notifier migrates.

For the full audit history and fix commits see `AUDIT.md`.
