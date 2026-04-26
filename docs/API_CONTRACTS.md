# event-users: API Contracts

## Authentication

All endpoints require a valid Bearer token in the `Authorization` header, verified by `BearerAuthMiddleware` (`middleware.py:12-40`) and optionally re-verified by route-level dependencies (`auth.py:26-46`).

Two accepted token forms:
- **JWT**: HS256-signed JWT with `sub` (email) and `role` (`admin` | `user`) claims. Signed with `JWT_SECRET_KEY`.
- **Static API token**: If `API_BEARER_TOKEN` env var is set and the presented token matches it exactly, the request is granted `role=admin` without JWT verification. Intended for service-to-service calls where issuing JWTs is inconvenient.

- **Write endpoints** (POST, PATCH) additionally require `role=admin` via `require_admin` dependency (`auth.py:49-54`).
- **Health endpoint** (`/health`) IS exempt from `BearerAuthMiddleware` — unauthenticated liveness probes receive `200 {"status": "ok"}`.

---

## Endpoints

### POST /api/users

Create a new user.

| Aspect | Detail |
|--------|--------|
| Auth | Bearer JWT + admin role |
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
| Auth | Bearer JWT + admin role |
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

---

### POST /api/users/by-ids

Fetch multiple users by a list of UUIDs in a single request.

| Aspect | Detail |
|--------|--------|
| Auth | Bearer JWT (any role) |
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
| Auth | Bearer JWT (any role) |
| Status | 200 OK |
| Source | `routes.py:82-90` |

**Path params**: `user_id` (UUID)

**Response**: `UserResponse`

**Errors**: 404 (user not found).

---

### GET /api/users/roles/{role}/emails/{email}

Fetch a single user by email and role combination.

| Aspect | Detail |
|--------|--------|
| Auth | Bearer JWT (any role) |
| Status | 200 OK |
| Source | `routes.py:67-79` |

**Path params**:
- `role`: `"client"` | `"organizer"`
- `email`: string (note: special chars like `+` must be URL-encoded)

**Response**: `UserResponse`

**Errors**: 404 (user with given email+role not found).

---

### GET /api/users

List users with optional filtering and pagination.

| Aspect | Detail |
|--------|--------|
| Auth | Bearer JWT (any role) |
| Status | 200 OK |
| Source | `routes.py:93-111` |

**Query params** (`ListUsersParams`, `schemas/users.py:110-122`):

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `email` | string, optional | null | Case-insensitive partial match (ILIKE `%value%`) |
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

The `event-notifier` service looks up a user's contact details using:
```
GET /api/users?email=user@example.com&role=client&limit=1
```
This returns the matching user with their contact channels (telegram, push, email) so the notifier can dispatch messages. The ILIKE match is partial, so exact email + role filtering ensures a unique result when combined with `limit=1`.

---

### GET /api/users/{user_id}/email-changelog

Получить историю изменений email для конкретного пользователя.

| Aspect | Detail |
|--------|--------|
| Auth | Bearer JWT (any role) |
| Status | 200 OK |

**Path params**: `user_id` (UUID)

**Query params**:

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int (1-500) | 50 | Размер страницы |
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

**Errors**: 404 (пользователь не найден).

---

### GET /health

Health check endpoint.

| Aspect | Detail |
|--------|--------|
| Auth | None — exempt from `BearerAuthMiddleware` via `public_paths` |
| Status | 200 OK |
| Source | `routes.py:117-119` |

**Response**:
```json
{"status": "ok"}
```

Unauthenticated liveness and readiness probes (Kubernetes, load balancers) receive `200` without providing any token.
