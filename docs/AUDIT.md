# event-users Audit Findings

Audited: 2026-06-10 (audit v2) — fixes applied 2026-06-11 on branch `audit-fixes`.
Full finding details: `../../docs/audit/v2/findings/event-users.json` (+ cross-service findings in
`rabbitmq-topology.json`, `security.json`, `delivery-reliability.json`, `flow-e2e.json`).
The April 2026 (v1) report this file previously contained is superseded; v1 items that were still
open were re-verified and carried into v2.

## Status Summary

| # | Severity | Finding | Status |
|---|----------|---------|--------|
| 1 | CRITICAL | CRM sync never commits — every cycle's writes silently rolled back | **FIXED** `92530c6`: commit per page in `CrmSyncService.sync` |
| 2 | HIGH | AES decryption errors unhandled — silent sync breakage, no accounting | **FIXED** `92530c6`: `CrmDecryptError` for payload-level failures; malformed records quarantined + counted; `SyncReport` + `last_success_at` |
| 3 | HIGH | No test coverage | **FIXED** `3686179` + follow-ups: pytest suite (auth, routes, controller, adapters, decrypt, sync, sender, consumer) |
| 4 | HIGH | event-notifier resolves recipients via ILIKE substring `list_users` — wrong-user risk | **PARTIALLY FIXED** `931c41a`: ILIKE wildcards escaped; exact-match `GET /api/users/by-identity` added. event-notifier must switch to it (its own fix) |
| 5 | HIGH | PATCH email updates bypass email_source/changelog guard — CRM resurrects old email | **FIXED** `48b42f3`: REST path now mirrors the consumer (email_source='admin', changelog, webhook outbox) |
| 6 | HIGH | Consumer subscribes to `events.user.email` without binding it to the `events` exchange | **FIXED** `8c6b031`: exchange declared + queue bound, matching `event_schemas.queues.USER_EMAIL_QUEUE` |
| 7 | MEDIUM | No exponential backoff on repeated CRM sync failures | **FIXED** `92530c6`: interval × 2^failures, capped at `CRM_SYNC_MAX_BACKOFF_SECONDS` |
| 8 | MEDIUM | Double bearer-token validation (middleware + dependency) | **FIXED** `1c57be5`: middleware removed; single decode path in `auth.verify_bearer_token` |
| 9 | MEDIUM | `update_user` IntegrityError → 500 instead of 409 | **FIXED** `7e77bac` |
| 10 | MEDIUM | Webhook delivery resets `email_source='crm'` before CRM applies the change | **FIXED** `afa16ed`: reset moved to CRM-sync convergence (upsert conflict on the new email) |
| 11 | MEDIUM | Outbox poller commits per row inside FOR UPDATE SKIP LOCKED — duplicate sends with >1 replica | **FIXED** `090f6a1`: two-phase claim (`status='processing'` + visibility timeout) then per-row delivery |
| 12 | MEDIUM | Email-change consumer not idempotent — redelivery duplicates changelog + webhooks | **FIXED** `3a69f84`: ce-id persisted as unique `user_email_changelog.message_id` (migration 0005) |
| 13 | MEDIUM | CRM sync ~4-5 queries per user | **FIXED** `92530c6` + `afa16ed`: one guard query per cycle, `RETURNING id` upsert, batched `unnest()` contact upsert |
| 14 | MEDIUM | Cache invalidation before request transaction commits | **FIXED** `612d61a`: routes commit before notifying event-admin |
| 15 | MEDIUM | Read endpoints not admin-gated — PII enumeration with any valid token | **FIXED** `1c57be5`: `require_admin` on the whole `/api/users` router |
| 16 | MEDIUM | JWT verification omits aud/iss | **FIXED** `1c57be5`: optional `JWT_AUDIENCE`/`JWT_ISSUER` settings (enforced when set; rollout-tolerant when unset). event-admin must mint matching claims before enabling |
| 17 | MEDIUM | `events.user.email` bound by event-receiver but consumer off by default — unbounded accumulation | **FIXED**: `IS_CONSUMER_ENABLED` defaults to `true` |
| 18 | LOW | Email as URL path segment in `/roles/{role}/emails/{email}` | **FIXED** `931c41a`: query-param `GET /by-identity` added; path endpoint kept but deprecated |
| 19 | LOW | No index on `user_contacts.channel` | **OPEN (documented)**: no code performs channel-wide lookups; add the index with the first consumer that needs it |
| 20 | LOW | Dead code (NotFoundError, ISqlExecutorFactory, execute_in_transaction, unused 'processing' status) | **FIXED** `5b482c5` (and 'processing' is now actually used by the outbox claim phase) |
| 21 | LOW | Unused dependencies (cloudevents, colorama, rich, tenacity) | **FIXED** `5b482c5` |
| 22 | LOW | Static API token compared non-constant-time | **FIXED** `1c57be5`: `hmac.compare_digest` |
| 23 | LOW | Two independent Settings instances | **FIXED**: `get_settings()` is the single `lru_cache` instance, also used by the DI provider. (Importing the app still requires a populated `.env` — accepted) |
| 24 | LOW | `.env.example` missing JWT_SECRET_KEY and consumer/webhook variables | **FIXED** `5b482c5` |
| 25 | LOW | Documentation drift | **FIXED**: docs rewritten 2026-06-11 |

## Notes for other services

- **event-notifier** must stop resolving recipients via `GET /api/users?email=…&limit=1`
  (substring search) and use `GET /api/users/by-identity?email=…&role=…` (exact match) instead.
- **event-admin**: when `JWT_AUDIENCE`/`JWT_ISSUER` are configured here, event-admin must mint
  tokens carrying those claims. Until then leave both unset (tokens with extra aud/iss still pass).
- `COALESCE` in the CRM upsert is intentional: CRM `null` means "not provided", not "clear field".
