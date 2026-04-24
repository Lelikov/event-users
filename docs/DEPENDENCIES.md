# event-users: Dependencies

## Depends On

| Dependency | Type | Purpose | Config | Failure Impact |
|------------|------|---------|--------|----------------|
| **PostgreSQL** | Infrastructure | Persistent storage for users and contacts | `POSTGRES_DSN` | Service fully unavailable -- all reads and writes fail with 500 |
| **External CRM API** | External service | Source of truth for user data during sync | `CRM_API_URL`, `CRM_API_TOKEN` | Sync stops; local data becomes stale. API endpoints continue serving last-known-good data. No alerting mechanism exists (`crm/sync.py:128-131`). |

## Provides To

| Consumer | What it uses | How |
|----------|--------------|-----|
| **event-notifier** | User contact lookup (email, telegram, push tokens) | `GET /api/users?email=...&role=...&limit=1` -- retrieves user with contacts to determine delivery channels |
| **event-admin-frontend** | User listing, user detail display | `GET /api/users` (paginated list), `GET /api/users/id/{user_id}` (single user) |
| **event-saver** | User UUID as foreign key | `participants.user_id` in event-saver's DB references `users.id` from this service (data-level dependency, not runtime API call) |

## What Breaks If event-users Goes Down

| Affected System | Impact | Severity |
|-----------------|--------|----------|
| **event-notifier** | Cannot resolve user contacts for notification delivery. Notifications to users will fail or be delayed until service recovers. | HIGH |
| **event-admin-frontend** | User management UI becomes non-functional. Cannot view, create, or update users. Booking views that reference users will show incomplete data. | MEDIUM |
| **event-saver** | No immediate runtime impact (no API calls to event-users). However, new participants cannot be validated against the user registry if such validation is added. | LOW |
| **CRM sync** | Sync loop stops. User data drifts from CRM source of truth. Once service recovers, next sync cycle reconciles all pages. No partial-sync detection exists. | MEDIUM |

## Dependency Diagram

```
                  +-----------------+
                  |  External CRM   |
                  |    API          |
                  +--------+--------+
                           |
                    (HTTPS, Bearer token,
                     AES-256-CBC encrypted)
                           |
                           v
               +-----------+-----------+
               |                       |
               |     event-users       |
               |                       |
               +--+--------+--------+--+
                  |        |        |
                  | (asyncpg)       |
                  v                 |
          +------+------+          |
          |  PostgreSQL  |         |
          |  (users DB)  |         |
          +-------------+          |
                                   |
          +------------------------+-----+
          |                |             |
          v                v             v
  +-----------+   +----------------+  +----------+
  |  event-   |   | event-admin-   |  | event-   |
  |  notifier |   | frontend       |  | saver    |
  +-----------+   +----------------+  | (FK ref) |
                                      +----------+
```

## Network and Authentication

- **Inbound**: All API consumers must provide a valid JWT Bearer token (HS256, signed with `JWT_SECRET_KEY`). Write operations require `role=admin` in the token.
- **Outbound (CRM)**: Bearer token authentication (`CRM_API_TOKEN`). Response payloads are AES-256-CBC encrypted.
- **Database**: Standard PostgreSQL connection via async DSN. Connection pool: 10 base + 20 overflow (`ioc.py:38-43`).
