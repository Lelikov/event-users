# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run the server:**
```bash
uvicorn event_users.main:app --reload
```

**Lint and format:**
```bash
ruff check .
ruff format .
```

**Tests:**
```bash
uv run pytest
```

**Pre-commit hooks:**
```bash
pre-commit run --all-files
```

**Alembic migrations:**
```bash
# Generate a new migration (autogenerate from models)
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Downgrade one step
alembic downgrade -1
```

**Configuration:** Requires a `.env` file. See `.env.example` for required variables.

## Architecture

Layered async FastAPI service for managing users and syncing them from an external CRM.

**Request flow:** `routes.py` → `controllers/` → `adapters/` → `adapters/sql.py` (SqlExecutor) → SQLAlchemy AsyncSession → PostgreSQL

**Key layers:**

- **`routes.py`** — FastAPI route handlers; convert request bodies/query params into DTOs, call controller via DI, convert result DTO to Pydantic response schema via `from_dto()`
- **`controllers/users.py`** — Business logic for create/update/get/list users
- **`adapters/users_db.py`** — All SQL query logic; executes raw SQL via SqlExecutor, maps `RowMapping` results to DTOs
- **`adapters/sql.py`** — `SqlExecutor` wraps `AsyncSession` with `text()` queries
- **`interfaces/`** — Protocol-based interfaces enabling loose coupling
- **`dto/users.py`** — Frozen dataclasses for inter-layer communication
- **`schemas/users.py`** — Pydantic models for HTTP requests/responses with `from_dto()` classmethods
- **`ioc.py`** — Dishka DI container; app-scoped (engine, session factory, settings) and request-scoped (session, executor, adapter, controller)
- **`db/models.py`** — SQLAlchemy ORM models (used by Alembic for migrations; queries are raw SQL in adapters)
- **`crm/`** — CRM sync: `client.py` fetches encrypted data, `sync.py` decrypts (AES-256-CBC) and upserts users
- **`consumer.py`** — RabbitMQ consumer for `user.email.change_requested` (queue `events.user.email`, bound to the `events` topic exchange); idempotent on CloudEvent `ce-id`
- **`webhook/`** — transactional outbox poller delivering `user.email.changed` to CRM (two-phase claim + deliver, multi-replica safe)
- **`adapters/changelog_db.py`** — email change audit log + webhook outbox writes
- **`auth.py`** — single token decode path (static service token or HS256 JWT, optional aud/iss); `require_admin` gates the entire `/api/users` router
- **`metrics.py`** — Prometheus metrics: HTTP RED middleware (`http_requests_total`, `http_request_duration_seconds` by route template; `/metrics` + `/health` excluded), `users_crm_sync_records_total{outcome}`, `users_crm_sync_cycles_total{outcome}`; exposed at `GET /metrics`

**CRM background sync:**
- Runs every 5 minutes (exponential backoff on failures, capped) as an asyncio background task started in `lifespan`
- Fetches encrypted user list from external CRM API with Bearer token auth
- Decrypts using AES-256-CBC (key from `CRM_ENCRYPTION_KEY`, IV from response); payload-level failures raise `CrmDecryptError`, malformed records are quarantined and counted
- Upserts users by unique `(email, role)` combination, one transaction per page
- Skips records matching admin-changed old emails (`email_source='admin'` guard); flips `email_source` back to `'crm'` on convergence

**DB Tables:**
- `users` — email, role (client|organizer), time_zone, email_source; unique on (email, role)
- `user_contacts` — channel (email, telegram, push, …), contact_id; unique on (user_id, channel)
- `user_email_changelog` — email change audit log; unique nullable `message_id` (consumer idempotency)
- `webhook_outbox` — transactional outbox for CRM webhooks (pending/processing/delivered/failed)

**DI scopes:**
- `APP` scope: `Settings`, `AsyncEngine`, `async_sessionmaker`, `CrmClient`, `CrmSyncRunner`, `RabbitBroker`, `EmailChangeConsumer`, `WebhookOutboxSender`, `ICacheNotifier`
- `REQUEST` scope: `AsyncSession`, `ISqlExecutor`, `IUsersDBAdapter`, `IEmailChangelogDBAdapter`, `IUsersController`

**Adding a new endpoint:** define route in `routes.py` → add method to `IUsersController` and `IUsersDBAdapter` protocols → implement in `UsersController` and `UsersDBAdapter` → add DTO in `dto/users.py` → add response schema in `schemas/users.py`.

## Service Documentation

- `docs/SERVICE_OVERVIEW.md` — architecture, maturity, known issues
- `docs/API_CONTRACTS.md` — HTTP endpoints, request/response schemas
- `docs/DATA_MODEL.md` — database tables, indexes, constraints
- `docs/DEPENDENCIES.md` — external service dependencies and failure modes
- `docs/AUDIT.md` — audit findings for this service

Cross-service architecture docs (message contracts, system topology, onboarding) are in `../docs/`.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
