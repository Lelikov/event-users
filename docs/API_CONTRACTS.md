# event-users: API Contracts

## Authentication

All endpoints require a valid JWT Bearer token in the `Authorization` header, verified by `JWTAuthMiddleware` (`middleware.py:12-40`) and optionally re-verified by route-level dependencies (`auth.py:26-46`).

- **Token format**: HS256-signed JWT with `sub` (email) and `role` (`admin` | `user`) claims.
- **Write endpoints** (POST, PUT) additionally require `role=admin` via `require_admin` dependency (`auth.py:49-54`).
- **Health endpoint** (`/health`) is NOT exempt from JWT middleware -- probes need a token or the middleware must be reconfigured.

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

### PUT /api/users/id/{user_id}

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

### GET /health

Health check endpoint.

| Aspect | Detail |
|--------|--------|
| Auth | Bearer JWT (middleware does NOT exempt this path) |
| Status | 200 OK |
| Source | `routes.py:117-119` |

**Response**:
```json
{"status": "ok"}
```

**Note**: Currently gated by `JWTAuthMiddleware` -- unauthenticated probes will receive 401. See known limitations in SERVICE_OVERVIEW.md.
