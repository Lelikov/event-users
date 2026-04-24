# event-users: Service Overview

## Domain

User and contact management service with background CRM synchronisation. Maintains the canonical user registry consumed by other services in the event-driven system.

- **Users** are uniquely identified by `(email, role)` where role is `client` or `organizer`.
- **User contacts** store communication channel identifiers (Telegram, push tokens, email) per user.
- `participants.user_id` in `event-saver`'s database references the UUID primary key from this service.

## CRM Sync

A background asyncio task started in the FastAPI lifespan (`main.py:35-41`) periodically fetches user data from an external CRM API and upserts it into the local database.

| Aspect | Detail | Source |
|--------|--------|--------|
| Frequency | Every 300 seconds (5 minutes) by default | `config.py:38` |
| Toggle | Controlled by `IS_SYNC_ENABLED` env var (default `false`) | `config.py:32` |
| Transport | HTTPS GET to `{CRM_API_URL}/users` with Bearer token auth, paginated (page_size=100) | `crm/client.py:24-45` |
| Encryption | AES-256-CBC; IV provided per response, key from `CRM_ENCRYPTION_KEY` (64-char hex = 32 bytes) | `crm/sync.py:30-55` |
| Decryption | `cryptography` library: AES-CBC + PKCS7 unpadding, then JSON parse | `crm/sync.py:30-55` |
| Upsert logic | `INSERT ... ON CONFLICT (email, role) DO UPDATE` with `COALESCE` for name/time_zone | `adapters/users_db.py:228-258` |
| Runner loop | Catches all non-`CancelledError` exceptions, logs, sleeps, retries | `crm/sync.py:117-132` |

## user_contacts

Each user may have zero or more contacts. A contact is a `(channel, contact_id)` pair, unique per user.

- **Channels**: `email` (auto-created on user create/update), `telegram`, `push`, etc.
- **Population**: created via API (POST/PUT user with `contacts` array) or via CRM sync (contacts field in decrypted payload).
- **Constraint**: `UNIQUE(user_id, channel)` -- one contact_id per channel per user.
- **Cascade**: `ON DELETE CASCADE` from `users.id`.

## Runtime Dependencies

| Dependency | Purpose | Config var |
|------------|---------|------------|
| PostgreSQL (asyncpg) | User/contact storage | `POSTGRES_DSN` |
| External CRM API | Source of truth for user data (when sync enabled) | `CRM_API_URL`, `CRM_API_TOKEN` |
| event-admin | Cache invalidation notifications (outbound POST) | `EVENT_ADMIN_URL`, `EVENT_ADMIN_CACHE_TOKEN` |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POSTGRES_DSN` | Yes | -- | PostgreSQL connection string (async) |
| `JWT_SECRET_KEY` | Yes | -- | HS256 secret for JWT verification |
| `JWT_ALGORITHM` | No | `HS256` | JWT algorithm |
| `API_BEARER_TOKEN` | No | -- | Static bearer token granting `role=admin` (alternative to JWT for service-to-service calls) |
| `CORS_ORIGINS` | No | `http://localhost:3000` | Comma-separated list of allowed CORS origins |
| `CRM_API_URL` | Yes | -- | Base URL of CRM API |
| `CRM_API_TOKEN` | Yes | -- | Bearer token for CRM API |
| `CRM_ENCRYPTION_KEY` | Yes | -- | 64-char hex string (32-byte AES-256 key) |
| `IS_SYNC_ENABLED` | No | `false` | Enable/disable CRM background sync |
| `CRM_SYNC_INTERVAL_SECONDS` | No | `300` | Seconds between sync cycles |
| `EVENT_ADMIN_URL` | No | -- | Base URL of event-admin service for cache invalidation |
| `EVENT_ADMIN_CACHE_TOKEN` | No | -- | Bearer token for event-admin cache invalidation endpoint |
| `DEBUG` | No | `false` | Enable debug mode / console log renderer |
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG/INFO/WARNING/ERROR/CRITICAL) |

Source: `config.py:5-38`

## Known Limitations

1. **No test coverage** -- no `tests/` directory exists. CRM decryption, auth middleware, and upsert idempotency are untested (`audit:HIGH`).
2. **CRM decryption errors are unhandled** -- wrong key, bad base64, or corrupted payload crashes the sync iteration; outer loop swallows exception with no alerting (`audit:CRITICAL`, `crm/sync.py:30-55`).
3. **Partial CRM sync** -- each user is upserted in a separate implicit transaction; a failure mid-page leaves committed partial data with no detection mechanism (`audit:HIGH`, `adapters/users_db.py:228-258`).
4. **No exponential backoff** -- repeated CRM failures retry at the same fixed interval, now 300 s (`crm/sync.py:117-132`). Interval default fixed; backoff not yet implemented.
5. **COALESCE in upsert prevents clearing fields** -- CRM-sent nulls for `name`/`time_zone` are silently ignored (`adapters/users_db.py:242-243`).
6. **Double JWT validation** -- middleware + route dependency decode token independently; not DRY (`middleware.py` + `auth.py`).
7. **`httpx.AsyncClient` created per CRM page** -- no connection reuse across pages or sync cycles (`crm/client.py:25`).

The following previously listed limitations have been resolved:
- ~~CORS wildcard with credentials~~ — `CORS_ORIGINS` env var; safe default replaces wildcard.
- ~~Health endpoint requires JWT~~ — `/health` is now in `public_paths` of `BearerAuthMiddleware`.
