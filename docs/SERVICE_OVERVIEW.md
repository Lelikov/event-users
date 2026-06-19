# event-users: Service Overview

## Domain

User and contact management service. Maintains the canonical user registry consumed by other services in the event-driven system.

- **Users** are uniquely identified by `(email, role)` where role is `client` or `organizer`.
- **User contacts** store communication channel identifiers (Telegram, push tokens, email) per user.
- `participants.user_id` in `event-saver`'s database references the UUID primary key from this service.

## Subsystems

| Subsystem | Entry point | Toggle |
|-----------|-------------|--------|
| HTTP API (`/api/users`) | `routes.py` | always on |
| RabbitMQ consumer (`events.user.email`) | `consumer.py` (`EmailChangeConsumer`) | `IS_CONSUMER_ENABLED` (default `true`) |
| event-admin cache invalidation | `adapters/cache_notifier.py` | `EVENT_ADMIN_URL` set |

## User Sync

User data is synchronised from cal.com via **event-db-sync**: a cal.com DB trigger publishes a `user.upserted` event that the `handle_user_upserted` consumer processes, calling `upsert_user_from_crm` to upsert the user into the local database.

## Email Change Flow (admin-initiated)

Both paths have identical semantics:

1. **RabbitMQ path**: `user.email.change_requested` (CloudEvent, queue `events.user.email`) → `handle_email_change`. Idempotent on `ce-id` (unique `user_email_changelog.message_id`).
2. **REST path**: `PATCH /api/users/id/{user_id}` with a new email → controller.

Both write, in one transaction: `users.email` + `email_source='admin'`, the email contact, and a `user_email_changelog` entry. The cache invalidation to event-admin fires only after commit.

## user_contacts

Each user may have zero or more contacts. A contact is a `(channel, contact_id)` pair, unique per user.

- **Channels**: `email` (auto-created on user create/update), `telegram`, `push`, etc.
- **Population**: via API (`contacts` array) or CRM sync; upserts are batched into a single `unnest()` statement.
- **Constraint**: `UNIQUE(user_id, channel)`; `ON DELETE CASCADE` from `users.id`.

## Runtime Dependencies

| Dependency | Purpose | Config var |
|------------|---------|------------|
| PostgreSQL (asyncpg) | User/contact storage | `POSTGRES_DSN` |
| RabbitMQ | `events.user.email` consumer (declares + binds the queue itself) | `RABBIT_URL` |
| event-admin | Cache invalidation notifications (outbound POST) | `EVENT_ADMIN_URL`, `EVENT_ADMIN_CACHE_TOKEN` |

## Environment Variables

See `.env.example` for the complete list with defaults. Required (no default): `POSTGRES_DSN`, `JWT_SECRET_KEY`.

Notable optional vars: `JWT_AUDIENCE`/`JWT_ISSUER` (aud/iss claim binding — enforced only when set; coordinate with event-admin token minting), `API_BEARER_TOKEN` (static service token, grants `role=admin`, compared constant-time), `IS_CONSUMER_ENABLED` (default `true` — the queue is always bound, so a disabled consumer means unbounded accumulation).

## Tracing

OpenTelemetry auto-instrumentation (FastAPI, httpx, asyncpg, RabbitMQ via FastStream middleware); exported via OTLP/gRPC to the collector → Tempo; gated by `OTEL_SDK_DISABLED` (off by default).

## Known Limitations

1. **COALESCE in upsert prevents clearing fields** — intentional: CRM `null` means "not provided", not "clear this field" (`adapters/users_db.py`).
2. **No index on `user_contacts.channel`** — channel-wide reverse lookups are unsupported; add the index with the first consumer that needs it.
3. **App import requires a populated `.env`** — `Settings` has required fields with no defaults; tooling that imports `main.py` needs at least the values from `.env.example`.
4. **`GET /roles/{role}/emails/{email}` was removed** — all callers use `GET /api/users/by-identity` (query params); the path-segment variant no longer exists.

For the full audit history and fix commits see `AUDIT.md`.
