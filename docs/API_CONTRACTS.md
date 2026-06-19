# event-users: API Contracts

## Authentication

Every `/api/users` route (reads included — they expose PII) requires `role=admin`, enforced by a router-level `require_admin` dependency. Tokens are decoded exactly once, in `auth.verify_bearer_token` (there is no auth middleware).

Two accepted token forms:
- **JWT**: HS256-signed JWT with `sub` (email) and `role` (`admin` | `user`) claims, signed with `JWT_SECRET_KEY`. If `JWT_AUDIENCE` / `JWT_ISSUER` are configured, `aud` / `iss` claims MUST match; when unset they are not verified (rollout tolerance).
- **Static API token**: if `API_BEARER_TOKEN` is set and the presented token matches it (constant-time comparison), the request is granted `role=admin`. Intended for service-to-service calls.

- **Health endpoint** (`/health`) is intentionally public — unauthenticated liveness probes receive `200 {"status": "ok"}`.

---

## Endpoints

### POST /api/users

Create a new user.

| Aspect | Detail |
|--------|--------|
| Auth | Bearer token, admin role (router-level) |
| Status | 201 Created |
| Source | `routes.py:27-43` |

**Request body** (`CreateUserRequest`, `schemas/users.py:69-83`):
```json
{
  "email": "user@example.com",      // required, validated as EmailStr
  "name": "John Doe",               // optional, string
  "role": "client",                  // required, "client" | "organizer"
  "time_zone": "Europe/Moscow",     // optional, default "Europe/Moscow"
  "contacts": [                     // optional, default []
    {"channel": "telegram", "contact_id": "123456"}
  ]
}
```

**Response** (`UserResponse`, `schemas/users.py:37-58`):
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "name": "John Doe",
  "role": "client",
  "time_zone": "Europe/Moscow",
  "contacts": [
    {"id": "uuid", "user_id": "uuid", "channel": "email", "contact_id": "user@example.com", "created_at": "...", "updated_at": "..."},
    {"id": "uuid", "user_id": "uuid", "channel": "telegram", "contact_id": "123456", "created_at": "...", "updated_at": "..."}
  ],
  "created_at": "2026-04-07T...",
  "updated_at": "2026-04-07T..."
}
```

**Errors**: 409 (email+role already exists), 422 (invalid timezone or request body).

---

### PATCH /api/users/id/{user_id}

Update an existing user (PATCH semantics -- only non-null fields are updated).

| Aspect | Detail |
|--------|--------|
| Auth | Bearer token, admin role (router-level) |
| Status | 200 OK |
| Source | `routes.py:46-64` |

**Path params**: `user_id` (UUID)

**Request body** (`UpdateUserRequest`, `schemas/users.py:86-100`):
```json
{
  "email": "new@example.com",       // optional
  "name": "New Name",              // optional
  "role": "organizer",             // optional, "client" | "organizer"
  "time_zone": "UTC",             // optional
  "contacts": [                   // optional; replaces contact set if provided
    {"channel": "telegram", "contact_id": "654321"}
  ]
}
```

**Response**: Same `UserResponse` schema.

**Errors**: 404 (user not found), 409 (email+role conflict), 422 (invalid timezone).

**Email-change semantics**: when `email` differs from the current value, the update also sets `email_source='admin'` and writes a `user_email_changelog` entry (`changed_by` = token `sub`) — same behaviour as the RabbitMQ consumer path.

---

### POST /api/users/by-ids

Fetch multiple users by a list of UUIDs in a single request.

| Aspect | Detail |
|--------|--------|
| Auth | Bearer token, admin role (router-level) |
| Status | 200 OK |
| Source | `routes.py` |

**Request body**:
```json
{
  "ids": ["uuid1", "uuid2", "..."]   // required; max 200 entries
}
```

**Response**:
```json
{
  "items": [ /* array of UserResponse */ ]
}
```

**Errors**: 422 (more than 200 IDs provided or invalid UUID format).

**Notes**: IDs not found in the database are silently omitted from `items`. Order of results is not guaranteed to match order of input `ids`.

---

### GET /api/users/id/{user_id}

Fetch a single user by UUID.

| Aspect | Detail |
|--------|--------|
| Auth | Bearer token, admin role (router-level) |
| Status | 200 OK |
| Source | `routes.py:82-90` |

**Path params**: `user_id` (UUID)

**Response**: `UserResponse`

**Errors**: 404 (user not found).

---

### GET /api/users/by-identity

Exact-match lookup by email + role (query params).

| Aspect | Detail |
|--------|--------|
| Auth | Bearer token, admin role (router-level) |
| Status | 200 OK |
| Source | `routes.py` (`get_user_by_identity`) |

**Query params**:
- `email`: string, exact match (required)
- `role`: `"client"` | `"organizer"` (required)

**Response**: `UserResponse`

**Errors**: 404 (user with given email+role not found).

This is the endpoint event-notifier and other services should use to resolve a user's contacts by email.

---

### GET /api/users

List users with optional filtering and pagination.

| Aspect | Detail |
|--------|--------|
| Auth | Bearer token, admin role (router-level) |
| Status | 200 OK |
| Source | `routes.py:93-111` |

**Query params** (`ListUsersParams`, `schemas/users.py:110-122`):

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `email` | string, optional | null | Case-insensitive partial match; `%`, `_` and `\\` in the term are escaped (no user-supplied wildcards) |
| `role` | `"client"` \| `"organizer"`, optional | null | Exact match filter |
| `limit` | int (1-500) | 50 | Page size |
| `offset` | int (>=0) | 0 | Pagination offset |

**Response** (`ListUsersResponse`, `schemas/users.py:103-107`):
```json
{
  "items": [ /* array of UserResponse */ ],
  "total": 142,
  "limit": 50,
  "offset": 0
}
```

#### Usage by event-notifier

event-notifier currently resolves recipients via `GET /api/users?email=…&role=…&limit=1`. **This is a substring search and can match the wrong user** (e.g. `ann@x.com` inside `joann@x.com`); it must migrate to the exact-match `GET /api/users/by-identity` endpoint.

---

### GET /api/users/{user_id}/email-changelog

Получить историю изменений email для конкретного пользователя.

| Aspect | Detail |
|--------|--------|
| Auth | Bearer token, admin role (router-level) |
| Status | 200 OK |

**Path params**: `user_id` (UUID)

**Query params**:

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int (1-100) | 20 | Размер страницы |
| `offset` | int (>=0) | 0 | Смещение для пагинации |

**Response**:
```json
{
  "items": [
    {
      "id": "uuid",
      "old_email": "old@example.com",
      "new_email": "new@example.com",
      "changed_by": "admin@example.com",
      "changed_at": "2026-04-26T12:00:00Z"
    }
  ],
  "total": 3
}
```

**Notes**: для неизвестного `user_id` возвращается пустой список (`items: [], total: 0`), а не 404.

---

### GET /health

Liveness probe (k8s `livenessProbe`): the process serves HTTP. Never calls dependencies.

| Aspect | Detail |
|--------|--------|
| Auth | None — registered on a separate router without `require_admin` |
| Status | 200 OK |
| Source | `routes.py` (`health_router`) |

**Response**:
```json
{"status": "ok"}
```

---

### GET /ready

Readiness probe (k8s `readinessProbe`): `SELECT 1` against PostgreSQL.

| Aspect | Detail |
|--------|--------|
| Auth | None |
| Status | 200 OK / 503 Service Unavailable |
| Source | `routes.py` (`health_router`) |

**Response** (`200`):
```json
{"status": "ready", "checks": {"database": true}}
```

**Response** (`503`, database down):
```json
{"status": "not_ready", "checks": {"database": false}}
```

Unauthenticated liveness and readiness probes (Kubernetes, load balancers) receive responses without providing any token.

### GET /metrics

Prometheus exposition endpoint (`prometheus_client.generate_latest`); `/metrics` and `/health`
are excluded from the RED counters.

| Aspect | Detail |
|--------|--------|
| Auth | None |
| Status | 200 OK, `text/plain; version=0.0.4; charset=utf-8` |
| Source | `routes.py` (`health_router`), `metrics.py` |

**Exposed metrics**:

| Metric | Type | Labels |
|---|---|---|
| `http_requests_total` | counter | `method`, `route` (route template, `unmatched` for 404s), `status` |
| `http_request_duration_seconds` | histogram | `method`, `route` |
