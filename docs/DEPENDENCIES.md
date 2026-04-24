# event-users: Dependencies

## Depends On

| Dependency | Type | Purpose | Config | Failure Impact |
|------------|------|---------|--------|----------------|
| **PostgreSQL** | Infrastructure | Persistent storage for users and contacts | `POSTGRES_DSN` | Service fully unavailable -- all reads and writes fail with 500 |
| **External CRM API** | External service | Source of truth for user data during sync | `CRM_API_URL`, `CRM_API_TOKEN` | Sync stops; local data becomes stale. API endpoints continue serving last-known-good data. No alerting mechanism exists (`crm/sync.py:128-131`). |
| **event-admin** | Internal service | Cache invalidation — `CacheNotifier` POSTs to event-admin's cache invalidation endpoint after user writes so that event-admin's read cache reflects the latest data | `EVENT_ADMIN_URL`, `EVENT_ADMIN_CACHE_TOKEN` | Cache invalidation silently fails; event-admin may serve stale user data until its cache TTL expires. User writes still succeed. |

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
          +------------------------+-----+------------------+
          |                |             |                  |
          v                v             v                  v
  +-----------+   +----------------+  +----------+  +------------+
  |  event-   |   | event-admin-   |  | event-   |  | event-     |
  |  notifier |   | frontend       |  | saver    |  | admin      |
  +-----------+   +----------------+  | (FK ref) |  | (cache     |
                                      +----------+  | invalidate)|
                                                    +------------+
```

## Network and Authentication

- **Inbound**: All API consumers must provide a valid Bearer token. Accepted forms: HS256-signed JWT (`JWT_SECRET_KEY`) or a static API token (`API_BEARER_TOKEN`). Write operations require `role=admin`. `/health` is exempt.
- **Outbound (CRM)**: Bearer token authentication (`CRM_API_TOKEN`). Response payloads are AES-256-CBC encrypted.
- **Outbound (event-admin)**: `CacheNotifier` sends a POST request to event-admin's cache invalidation endpoint using `EVENT_ADMIN_CACHE_TOKEN` as the bearer token. Called after any user write operation.
- **Database**: Standard PostgreSQL connection via async DSN. Connection pool: 10 base + 20 overflow (`ioc.py:38-43`).
