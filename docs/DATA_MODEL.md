# event-users: Data Model

## ER Diagram

```mermaid
erDiagram
    users {
        uuid id PK "gen_random_uuid()"
        text email "NOT NULL"
        text name "NULLABLE"
        text role "NOT NULL (client|organizer)"
        text time_zone "NULLABLE"
        timestamptz created_at "NOT NULL, default now()"
        timestamptz updated_at "NOT NULL, default now()"
    }

    user_contacts {
        uuid id PK "gen_random_uuid()"
        uuid user_id FK "NOT NULL, CASCADE on delete"
        text channel "NOT NULL"
        text contact_id "NOT NULL"
        timestamptz created_at "NOT NULL, default now()"
        timestamptz updated_at "NOT NULL, default now()"
    }

    users ||--o{ user_contacts : "has"
```

## Table: `users`

Source: `db/models.py:11-39`, migration `alembic/versions/0001_initial.py:24-52`

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | `UUID` | NO | `gen_random_uuid()` | Primary key |
| `email` | `TEXT` | NO | -- | User's email address |
| `name` | `TEXT` | YES | NULL | Added in migration 0002 |
| `role` | `TEXT` | NO | -- | `"client"` or `"organizer"` (renamed from `"volunteer"` in migration 0003) |
| `time_zone` | `TEXT` | YES | NULL | IANA timezone string (e.g., `"Europe/Moscow"`) |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation time |
| `updated_at` | `TIMESTAMPTZ` | NO | `now()` | Last modification time |

**Constraints**:
- `uq_users_email_role` -- UNIQUE(`email`, `role`)
- `ix_users_email` -- B-tree index on `email`
- `ix_users_role` -- B-tree index on `role`

## Table: `user_contacts`

Source: `db/models.py:42-72`, migration `alembic/versions/0001_initial.py:54-82`

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | `UUID` | NO | `gen_random_uuid()` | Primary key |
| `user_id` | `UUID` | NO | -- | FK to `users.id`, CASCADE on delete |
| `channel` | `TEXT` | NO | -- | Contact channel type (`email`, `telegram`, `push`, etc.) |
| `contact_id` | `TEXT` | NO | -- | Channel-specific identifier (email address, Telegram chat ID, push token, etc.) |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation time |
| `updated_at` | `TIMESTAMPTZ` | NO | `now()` | Last modification time |

**Constraints**:
- `uq_user_contacts_user_id_channel` -- UNIQUE(`user_id`, `channel`) -- one contact_id per channel per user
- `ix_user_contacts_user_id` -- B-tree index on `user_id`
- FK `user_id -> users.id` with `ON DELETE CASCADE`

**Note**: No index on `channel` alone. Channel-based lookups across all users require a full table scan (see audit LOW finding).

## CRM Sync Upsert Logic

Source: `adapters/users_db.py:228-258`

The CRM sync performs per-user upserts:

```sql
INSERT INTO users (email, name, role, time_zone)
VALUES (:email, :name, :role, :time_zone)
ON CONFLICT (email, role)
DO UPDATE SET
    name = COALESCE(EXCLUDED.name, users.name),
    time_zone = COALESCE(EXCLUDED.time_zone, users.time_zone),
    updated_at = now()
```

After the user upsert, a SELECT retrieves the user's `id`, then contacts are upserted:

```sql
INSERT INTO user_contacts (user_id, channel, contact_id)
VALUES (:user_id, :channel, :contact_id)
ON CONFLICT (user_id, channel)
DO UPDATE SET contact_id = EXCLUDED.contact_id, updated_at = now()
```

An `email` contact is always auto-created/updated alongside any explicit contacts.

**Semantics**:
- `COALESCE` means CRM-sent NULL values do NOT clear existing name/time_zone fields.
- Each user is committed independently (no transaction wrapping the full sync batch).
- Contacts are upserted row-by-row within the same implicit transaction as the parent user.

## Migration Chain

| Revision | Date | Description | Source |
|----------|------|-------------|--------|
| `0001` | 2026-04-07 | Initial schema: `users` and `user_contacts` tables with constraints and indexes | `alembic/versions/0001_initial.py` |
| `0002` | 2026-04-07 | Add `name` column (nullable TEXT) to `users` | `alembic/versions/0002_add_user_name.py` |
| `0003` | 2026-04-13 | Rename role value `volunteer` to `organizer` (data migration) | `alembic/versions/0003_rename_volunteer_to_organizer.py` |

Current head: `0003`

Migration commands:
```bash
alembic upgrade head     # apply all
alembic downgrade -1     # revert last
```
