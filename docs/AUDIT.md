# event-users Audit Findings

Audited: 2026-04-20

---

## CRITICAL

---

[CRITICAL] AES decryption errors are unhandled and will crash the sync loop iteration silently

Services affected: event-users (CRM sync), downstream notification/booking services that depend on up-to-date user data
Location: `event-users/event_users/crm/sync.py:30-55` (`decrypt_payload`), `sync.py:64-99` (`CrmSyncService.sync`)
Description: `decrypt_payload` makes no attempt to catch `ValueError`, `InvalidUnpadding`, `binascii.Error`, or `json.JSONDecodeError`. Any of the following will raise an unhandled exception that propagates up to `CrmSyncService.sync`, which catches it with a bare `except Exception`, logs it, and re-raises — causing `CrmSyncRunner.run` to swallow it and wait the full interval before retrying:
- Wrong encryption key (`CRM_ENCRYPTION_KEY` misconfigured or rotated)
- Malformed base64 in `iv` or `encrypted_data` fields
- Bad PKCS7 padding (truncated or corrupted payload)
- Non-JSON plaintext after decryption

The outer loop in `CrmSyncRunner.run` catches all non-`CancelledError` exceptions and silently sleeps until the next cycle. No alert, no metric, no dead-letter mechanism. The DB is left in its last-known-good state with no indication that sync has been broken for potentially hours.

Additionally, `decrypt_payload` is called inside the page loop (line 73). If decryption of page 2+ fails, already-upserted users from page 1 remain committed to the DB (no rollback), giving a **partial sync** with no way to detect it.

Recommendation:
1. Wrap the decryption call in a specific `except (ValueError, Exception) as e` block that logs the specific failure cause (wrong key vs. bad padding vs. bad JSON) and either skips the page with a metric or aborts the full sync.
2. Add a `last_successful_sync_at` timestamp in a config/status table so operators can detect sync staleness.
3. Consider a dedicated monitoring counter (Prometheus or structured log event) for each decryption failure.

---

[CRITICAL] Default JWT secret is a hardcoded development string shipped in config — **FIXED**

Services affected: event-users (all authenticated endpoints)
Location: `event-users/event_users/config.py:15`
Description: `jwt_secret_key` has a default value of `"dev-jwt-secret-change-in-prod"`. If the production `.env` file is missing or the variable is not set (e.g., during a first deploy, a misconfigured container, or a failed secret injection), the application starts silently with a known-public secret. Any actor who knows this default can forge valid JWT tokens for any role, including `admin`, and gain full write access to create/update users and read all contact data.

The field is not declared `strict=True` or made required (no `Field(...)` without a default), so Pydantic will never raise at startup.

**Resolution**: Field changed to `jwt_secret_key: str = Field(...)` — no default value. Pydantic now raises a `ValidationError` at startup if the variable is absent, preventing silent insecure startup.

---

## HIGH

---

[HIGH] CRM sync is row-by-row, non-transactional; partial syncs leave DB in inconsistent state

Services affected: event-users, event-admin-frontend, event-notifier
Location: `event-users/event_users/crm/sync.py:82-89` (`CrmSyncService.sync`), `event-users/event_users/adapters/users_db.py:215-247` (`upsert_user_from_crm`)
Description: Each user is upserted independently via `await self._db.upsert_user_from_crm(...)`. Inside `upsert_user_from_crm`, `SqlExecutor.execute()` calls `session.commit()` after every single SQL statement (line 25 of `sql.py`). This means:
- If sync fails after N users, users 1..N are permanently committed, the rest are not.
- There is no way to distinguish "user not yet synced this cycle" from "user deleted in CRM".
- A CRM API error mid-page leaves half a page committed.

Furthermore, the SELECT immediately after the upsert (lines 236-239 of `users_db.py`) is a separate read with no locking, creating a TOCTOU window: another process could delete the user between the INSERT...ON CONFLICT and the SELECT id.

Recommendation:
1. Use `execute_in_transaction` (already exists on `ISqlExecutor`) or open a single `AsyncSession` transaction covering all upserts in one sync cycle.
2. Alternatively, adopt a staging-table approach: bulk-insert to a temp table, then upsert from it in a single statement.
3. Replace the post-upsert SELECT with a `RETURNING id` clause on the upsert statement itself.

---

[HIGH] No backoff on CRM sync errors; 10-second default interval is not 5 minutes — **PARTIALLY FIXED**

Services affected: event-users, CRM API (external)
Location: `event-users/event_users/crm/sync.py:117-132` (`CrmSyncRunner.run`), `event-users/event_users/config.py:38`
Description: Two issues:
1. `crm_sync_interval_seconds` defaults to `10` (line 38 of `config.py`), not 300 (5 minutes) as documented in CLAUDE.md and the service summary. If `.env` is not configured, syncs fire every 10 seconds, hammering the CRM API and the database continuously.
2. There is no exponential backoff on repeated errors. A transient CRM outage will cause the loop to retry at the same cadence indefinitely. With a 10-second interval and no backoff, a 1-hour CRM outage generates ~360 failed HTTP requests, all logged as exceptions — flooding log storage and potentially triggering rate-limits or bans from the CRM API.

**Resolution (partial)**:
- Issue 1 — **FIXED**: Default changed to `crm_sync_interval_seconds: int = 300`. Comment updated to `# default: 5 minutes`.
- Issue 2 — **OPEN**: Exponential backoff with jitter is not yet implemented. Repeated CRM failures still retry at the fixed interval. See recommendation below.

Recommendation (remaining):
- Implement exponential backoff with jitter on consecutive failures (e.g., double the interval up to a max of 30 minutes).
- Add a `consecutive_failures` counter; alert if it exceeds a threshold.

---

[HIGH] `list_users` makes N+1 queries: one SELECT per user for contacts

Services affected: event-users (GET /api/users), event-admin-frontend
Location: `event-users/event_users/adapters/users_db.py:209-212` (`list_users`)
Description: After fetching the user rows, the adapter executes a separate `_fetch_contacts(user_id)` query for every user in the result set (lines 209-211). With `limit` up to 500, this is 1 (count) + 1 (users) + 500 (contacts) = 502 sequential database round trips per request. Under modest load this will cause high latency and connection pool exhaustion.

Recommendation: Replace the per-user contact fetch with a single JOIN or a second batch query using `WHERE user_id = ANY(:ids)`, then group contacts by `user_id` in Python before assembling DTOs.

---

[HIGH] No test coverage whatsoever

Services affected: event-users (entire service)
Location: `event-users/` (no `tests/` directory exists)
Description: The graph search and filesystem glob both return no test files for the event-users service. Zero unit or integration tests exist for:
- CRM decryption logic (`decrypt_payload`)
- Upsert idempotency
- Auth middleware and JWT validation
- Controller timezone validation
- Route-level error handling

This means regressions in any of the above — particularly in the security-critical auth and decryption paths — will not be caught before deployment.

Recommendation: At minimum, add unit tests for `decrypt_payload` (correct key, wrong key, bad base64, bad JSON) and `verify_bearer_token` (expired token, missing token, admin vs. non-admin). Add integration tests for the upsert idempotency and the N+1 list query.

---

## MEDIUM

---

[MEDIUM] Double JWT validation: middleware + route-level dependency create inconsistency risk

Services affected: event-users (all routes)
Location: `event-users/event_users/middleware.py:12-40`, `event-users/event_users/auth.py:27-47`, `event-users/event_users/routes.py:8`
Description: JWT tokens are validated twice per request:
1. `JWTAuthMiddleware.dispatch` decodes the token for existence/validity (lines 34-38 of `middleware.py`).
2. `verify_bearer_token` (used as a FastAPI `Depends`) decodes it again in route handlers, this time also extracting `sub` and `role` claims.

The middleware's decode does NOT extract the payload — it only validates the signature. The route dependency decodes it a second time independently. This creates two problems:
- Any future algorithm change or secret rotation must be applied consistently to both code paths; they are not DRY.
- The middleware silently passes `OPTIONS` requests without auth (for CORS preflight), which is intentional, but the health endpoint (`/health`) is also **not** in `public_paths` and is therefore gated by JWT. This means liveness probes that do not carry a token will fail with 401, making the service appear unhealthy.

Recommendation:
1. Remove the middleware's JWT validation and rely solely on the FastAPI dependency for auth enforcement, or centralise into a single function.
2. Add `/health` to `public_paths` (or make it the only public path) so Kubernetes/load-balancer probes work unauthenticated.

---

[MEDIUM] `upsert_user_from_crm` uses `COALESCE` which silently ignores CRM-provided null updates

Services affected: event-users, data integrity
Location: `event-users/event_users/adapters/users_db.py:229-231`
Description: The ON CONFLICT DO UPDATE clause reads:
```sql
name = COALESCE(EXCLUDED.name, users.name),
time_zone = COALESCE(EXCLUDED.time_zone, users.time_zone),
```
This means if the CRM intentionally sends `null` for `name` or `time_zone` (to clear a field), the existing value is silently preserved. The upsert is not truly idempotent in the sense that a CRM-side deletion of a field is never reflected in the local DB. Over time, stale data accumulates without any log warning.

Recommendation: Decide on the intended contract: if the CRM is the source of truth, use direct assignment (`name = EXCLUDED.name`) and let CRM nulls clear fields. Document the decision explicitly in the adapter.

---

[MEDIUM] `crm_encryption_key` stored as hex string, parsed at provider startup — no validation of key length — **FIXED**

Services affected: event-users (CRM sync)
Location: `event-users/event_users/ioc.py:101`
Description: `bytes.fromhex(settings.crm_encryption_key)` is called at DI container construction time. There is no validation that:
- The string is valid hex (an odd-length string raises `ValueError` at runtime).
- The resulting bytes are exactly 32 bytes (AES-256 requires 32 bytes; fewer bytes will cause `cryptography` to raise `ValueError: The key must be 16, 24, or 32 bytes` at first sync, not at startup).

A misconfigured key will not surface until the first sync attempt, which may happen minutes after startup, making root cause analysis harder.

**Resolution**: A `field_validator` was added to `Settings.crm_encryption_key` that validates the string is valid hex and decodes to exactly 32 bytes. Startup now fails fast with a clear error if the key is malformed or wrong-length.

---

[MEDIUM] `SqlExecutor.execute` auto-commits after every statement, bypassing session-level transaction management

Services affected: event-users (all write operations)
Location: `event-users/event_users/adapters/sql.py:23-25`
Description: `SqlExecutor.execute` calls `await self.session.commit()` unconditionally after each statement. This means any multi-step write operation (e.g., `create_user` which inserts user then upserts contacts) commits in separate transactions. If the contact upsert fails after the user insert, the user row is stranded without contacts and the request returns a 500 — but the user is permanently persisted in the DB without the expected contacts. The session-level rollback in `ioc.py:provide_session` (lines 65-68) will not undo the already-committed user row.

Recommendation: Remove `await self.session.commit()` from `SqlExecutor.execute` and rely on the session lifecycle in `provide_session` (which commits on success, rolls back on exception) to manage transaction boundaries. Use `execute_in_transaction` explicitly only when a sub-transaction is needed.

---

[MEDIUM] `update_user` cannot clear `name`, `time_zone`, or `role` — PATCH semantics silently skip None

Services affected: event-users (PUT /api/users/id/{user_id})
Location: `event-users/event_users/adapters/users_db.py:108-143`
Description: The dynamic SQL builder skips any field in `UpdateUserDTO` that is `None`. A `PUT` endpoint is semantically a full replacement, but the implementation behaves like a `PATCH`: sending `{"email": "x@y.com"}` with no `name` preserves the existing name rather than clearing it. This is a semantic mismatch that will confuse API consumers and may introduce stale data bugs.

Recommendation: Either rename the endpoint/method to `PATCH`, or change the update logic so that explicitly-provided `null` values in the request body clear the corresponding field. Pydantic's `model_fields_set` can distinguish "not provided" from "explicitly null."

---

## LOW

---

[LOW] CORS is wide open (`allow_origins=["*"]` with `allow_credentials=True`) — **FIXED**

Services affected: event-users
Location: `event-users/event_users/main.py:59-65`
Description: `allow_origins=["*"]` combined with `allow_credentials=True` is technically forbidden by the CORS spec (browsers refuse credentials with wildcard origins), so this configuration is both overly permissive and broken for credential-bearing cross-origin requests. The combination will cause browser CORS errors for any frontend that sends cookies or Authorization headers in a cross-origin context.

**Resolution**: `allow_origins` is now configurable via the `CORS_ORIGINS` env var (comma-separated list). A safe default (e.g., `["http://localhost:3000"]`) is used when the variable is not set, replacing the wildcard.

---

[LOW] `CrmClient.fetch_users` creates a new `httpx.AsyncClient` per call (per page)

Services affected: event-users (CRM sync performance)
Location: `event-users/event_users/crm/client.py:24-45`
Description: A new `httpx.AsyncClient` is instantiated inside `fetch_users` and torn down after each request. For a paginated sync, this means a new TCP connection (and TLS handshake) per page. The client is also not shared across sync cycles. This is wasteful for performance.

Recommendation: Instantiate `httpx.AsyncClient` once in `CrmClient.__init__` and close it in a `close()` method called from the lifespan shutdown, or use a shared client at the `AppProvider` scope.

---

[LOW] `get_user_by_email_role` endpoint path uses path params — email with special chars will break routing

Services affected: event-users
Location: `event-users/event_users/routes.py:67`
Description: The route `GET /api/users/roles/{role}/emails/{email}` encodes the email as a path segment. Emails can legally contain `+`, `.`, and `%` characters. URL-encoding a `+` as `%2B` may be decoded differently by different proxies or FastAPI versions, and a `.` in the path can confuse some reverse proxies.

Recommendation: Either use query parameters for the email lookup (`GET /api/users/by-identity?email=&role=`) or document the required encoding explicitly and test with special-character emails.

---

[LOW] No index on `user_contacts.channel` — contact lookup by channel at scale will be slow

Services affected: event-users
Location: `event-users/event_users/db/models.py:69-72`, `event-users/alembic/versions/0001_initial.py`
Description: `user_contacts` has an index on `user_id` but not on `channel`. If a consumer needs to find all users with a given Telegram channel ID (for deduplication or lookup), a full table scan is required. The `_upsert_contacts` loop also does per-row upserts which rely on the `(user_id, channel)` unique constraint but not an explicit index on `channel` alone.

Recommendation: Add `Index("ix_user_contacts_channel", "channel")` if channel-based lookups are anticipated. At minimum, document that channel lookups are unsupported.

---

[LOW] `health` endpoint is protected by JWT middleware — liveness probes will fail without a token — **FIXED**

Services affected: event-users (operations/Kubernetes)
Location: `event-users/event_users/main.py:58`, `event-users/event_users/middleware.py:23-24`
Description: `JWTAuthMiddleware` is registered with an empty `public_paths` frozenset. The `/health` route is included in `root_router` but is not exempt. Any unauthenticated liveness probe (Kubernetes, load balancer, uptime checker) will receive a `401 Missing bearer token` response instead of `200 {"status": "ok"}`. This could trigger false restarts of a healthy pod.

**Resolution**: `BearerAuthMiddleware` is now instantiated with `public_paths=frozenset({"/health"})`. Unauthenticated requests to `/health` are passed through without token validation.

---

[LOW] `crm_sync_interval_seconds` comment says "5 minutes" but default is 10 seconds — **FIXED**

Services affected: event-users (operations documentation)
Location: `event-users/event_users/config.py:38`
Description: `crm_sync_interval_seconds: int = 10  # 5 minutes` — the comment contradicts the value. This is almost certainly a copy-paste or development leftover, but it means production deployments without an explicit `.env` setting will sync every 10 seconds, not every 5 minutes. (This overlaps with the HIGH finding on backoff, but the comment-vs-value mismatch warrants its own entry.)

**Resolution**: Default changed to `crm_sync_interval_seconds: int = 300` with comment updated to `# default: 5 minutes`. Covered by the PARTIALLY FIXED HIGH finding above.

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 2     |
| HIGH     | 4     |
| MEDIUM   | 5     |
| LOW      | 5     |
| **Total**| **16**|

### Top 3 Concerns

1. **CRITICAL — Unhandled AES decryption exceptions cause silent partial syncs (`crm/sync.py:30-55`, `sync.py:82-89`)**: A wrong key or malformed CRM payload crashes mid-sync with no partial-sync detection, no alerting, and no rollback — leaving the user DB silently stale. Combined with the row-by-row commit pattern, partial data can persist indefinitely. **Still open.**

2. **HIGH — Row-by-row non-transactional upsert + `SqlExecutor.execute` auto-commits (`adapters/sql.py:25`, `adapters/users_db.py:215-247`)**: Every write commits immediately. A failure mid-operation (user inserted, contacts not yet written) leaves the DB in an inconsistent state that the session rollback in `ioc.py` cannot undo. This affects both CRM sync and the API create/update paths. **Still open.**

3. **HIGH — No exponential backoff on CRM sync errors (`crm/sync.py:117-132`)**: The interval default (300 s) is now fixed, but repeated failures still retry at the same cadence with no backoff, risking CRM rate-limits during outages. **Still open.**
