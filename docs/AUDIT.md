# event-users Audit Findings

Audited: 2026-06-10 (audit v2) — fixes applied 2026-06-11 on branch `audit-fixes`.
Full finding details: `../../docs/audit/v2/findings/event-users.json` (+ cross-service findings in
`rabbitmq-topology.json`, `security.json`, `delivery-reliability.json`, `flow-e2e.json`).
The April 2026 (v1) report this file previously contained is superseded; v1 items that were still
open were re-verified and carried into v2.

## Status Summary

| # | Severity | Finding | Status |
|---|----------|---------|--------|
| 1 | CRITICAL | CRM sync never commits — every cycle's writes silently rolled back | **REMOVED**: CRM poller removed (`chore/remove-crm-machinery`); sync now via event-db-sync |
| 2 | HIGH | AES decryption errors unhandled — silent sync breakage, no accounting | **REMOVED**: CRM poller removed (`chore/remove-crm-machinery`) |
| 3 | HIGH | No test coverage | **FIXED** `3686179` + follow-ups: pytest suite (auth, routes, controller, adapters, consumer) |
| 4 | HIGH | event-notifier resolves recipients via ILIKE substring `list_users` — wrong-user risk | **PARTIALLY FIXED** `931c41a`: ILIKE wildcards escaped; exact-match `GET /api/users/by-identity` added. event-notifier must switch to it (its own fix) |
| 5 | HIGH | PATCH email updates bypass email_source/changelog guard — CRM resurrects old email | **FIXED** `48b42f3`: REST path now mirrors the consumer (email_source='admin', changelog entry) |
| 6 | HIGH | Consumer subscribes to `events.user.email` without binding it to the `events` exchange | **FIXED** `8c6b031`: exchange declared + queue bound, matching `event_schemas.queues.USER_EMAIL_QUEUE` |
| 7 | MEDIUM | No exponential backoff on repeated CRM sync failures | **REMOVED**: CRM poller removed (`chore/remove-crm-machinery`) |
| 8 | MEDIUM | Double bearer-token validation (middleware + dependency) | **FIXED** `1c57be5`: middleware removed; single decode path in `auth.verify_bearer_token` |
| 9 | MEDIUM | `update_user` IntegrityError → 500 instead of 409 | **FIXED** `7e77bac` |
| 10 | MEDIUM | Webhook delivery resets `email_source='crm'` before CRM applies the change | **REMOVED**: webhook outbox removed (`chore/remove-crm-machinery`); `email_source` is now informational only |
| 11 | MEDIUM | Outbox poller commits per row inside FOR UPDATE SKIP LOCKED — duplicate sends with >1 replica | **REMOVED**: webhook outbox removed (`chore/remove-crm-machinery`) |
| 12 | MEDIUM | Email-change consumer not idempotent — redelivery duplicates changelog + webhooks | **FIXED** `3a69f84`: ce-id persisted as unique `user_email_changelog.message_id` (migration 0005); webhook outbox removed |
| 13 | MEDIUM | CRM sync ~4-5 queries per user | **REMOVED**: CRM poller removed (`chore/remove-crm-machinery`) |
| 14 | MEDIUM | Cache invalidation before request transaction commits | **FIXED** `612d61a`: routes commit before notifying event-admin |
| 15 | MEDIUM | Read endpoints not admin-gated — PII enumeration with any valid token | **FIXED** `1c57be5`: `require_admin` on the whole `/api/users` router |
| 16 | MEDIUM | JWT verification omits aud/iss | **FIXED** `1c57be5`: optional `JWT_AUDIENCE`/`JWT_ISSUER` settings (enforced when set; rollout-tolerant when unset). event-admin must mint matching claims before enabling |
| 17 | MEDIUM | `events.user.email` bound by event-receiver but consumer off by default — unbounded accumulation | **FIXED**: `IS_CONSUMER_ENABLED` defaults to `true` |
| 18 | LOW | Email as URL path segment in `/roles/{role}/emails/{email}` | **FIXED** `931c41a`: query-param `GET /by-identity` added; deprecated path endpoint removed in audit-v2 follow-up #2 |
| 19 | LOW | No index on `user_contacts.channel` | **OPEN (documented)**: no code performs channel-wide lookups; add the index with the first consumer that needs it |
| 20 | LOW | Dead code (NotFoundError, ISqlExecutorFactory, execute_in_transaction, unused 'processing' status) | **FIXED** `5b482c5` |
| 21 | LOW | Unused dependencies (cloudevents, colorama, rich, tenacity) | **FIXED** `5b482c5` |
| 22 | LOW | Static API token compared non-constant-time | **FIXED** `1c57be5`: `hmac.compare_digest` |
| 23 | LOW | Two independent Settings instances | **FIXED**: `get_settings()` is the single `lru_cache` instance, also used by the DI provider. (Importing the app still requires a populated `.env` — accepted) |
| 24 | LOW | `.env.example` missing JWT_SECRET_KEY and consumer variables | **FIXED** `5b482c5` |
| 25 | LOW | Documentation drift | **FIXED**: docs rewritten 2026-06-11; updated for CRM removal 2026-06-19 |

## Notes for other services

- **event-notifier** must stop resolving recipients via `GET /api/users?email=…&limit=1`
  (substring search) and use `GET /api/users/by-identity?email=…&role=…` (exact match) instead.
- **event-admin**: when `JWT_AUDIENCE`/`JWT_ISSUER` are configured here, event-admin must mint
  tokens carrying those claims. Until then leave both unset (tokens with extra aud/iss still pass).
- `COALESCE` in `upsert_user_from_crm` is intentional: NULL from the source means "not provided", not "clear field".
