# event-users

Микросервис управления пользователями. Предоставляет REST API для создания, обновления и получения пользователей, а
также периодически синхронизирует их из внешней CRM.

## Возможности

- CRUD-операции над пользователями (email, name, role, time_zone)
- Хранение способов связи с пользователем (telegram, push и т.д.) в отдельной таблице
- List-эндпоинт с поиском по email и фильтрацией по роли
- Фоновая синхронизация пользователей из внешней CRM раз в 60 минут:
    - HTTP-запрос с Bearer-аутентификацией
    - Расшифровка ответа (AES-256-CBC)
    - Upsert по уникальной паре `(email, role)`

## Стек

| Компонент     | Библиотека                              |
|---------------|-----------------------------------------|
| Web-фреймворк | FastAPI                                 |
| DI-контейнер  | Dishka                                  |
| База данных   | PostgreSQL (SQLAlchemy async + asyncpg) |
| Миграции      | Alembic                                 |
| Логирование   | structlog + ujson                       |
| HTTP-клиент   | httpx                                   |
| Шифрование    | cryptography (AES-256-CBC)              |
| Конфигурация  | pydantic-settings                       |

## Быстрый старт

### Локально

```bash
# 1. Установить зависимости
uv sync

# 2. Создать .env из примера и заполнить переменные
cp .env.example .env

# 3. Применить миграции
alembic upgrade head

# 4. Запустить сервер
uvicorn event_users.main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker Compose

```bash
cp .env.example .env
# Заполнить .env

docker-compose up --build
```

Сервис будет доступен на `http://localhost:8000`.

## Конфигурация

Все параметры задаются через `.env` (или переменные окружения):

| Переменная                  | Описание                                   | Пример                                                      |
|-----------------------------|--------------------------------------------|-------------------------------------------------------------|
| `POSTGRES_DSN`              | Строка подключения к PostgreSQL            | `postgresql+asyncpg://user:pass@localhost:5432/event_users` |
| `CRM_API_URL`               | Базовый URL внешней CRM                    | `https://crm.example.com`                                   |
| `CRM_API_TOKEN`             | Bearer-токен для авторизации в CRM         | `secret-token`                                              |
| `CRM_ENCRYPTION_KEY`        | AES-256 ключ в hex (64 символа = 32 байта) | `0000...0000`                                               |
| `CRM_SYNC_INTERVAL_SECONDS` | Интервал синхронизации в секундах          | `300`                                                       |
| `DEBUG`                     | Включить консольный вывод логов с цветами  | `false`                                                     |
| `LOG_LEVEL`                 | Уровень логирования                        | `INFO`                                                      |
| `API_BEARER_TOKEN`          | Bearer-токен для доступа к API             | `dev-token`                                                 |

## API

Интерактивная документация: `http://localhost:8000/docs`

### Эндпоинты

#### Пользователи

| Метод  | Путь                                     | Описание                            |
|--------|------------------------------------------|-------------------------------------|
| `POST` | `/api/users`                             | Создать пользователя                |
| `GET`  | `/api/users`                             | Список пользователей                |
| `GET`  | `/api/users/id/{id}`                     | Получить пользователя по UUID       |
| `PUT`  | `/api/users/id/{id}`                     | Обновить пользователя               |
| `GET`  | `/api/users/roles/{role}/emails/{email}` | Получить пользователя по email+role |
| `GET`  | `/health`                                | Health check                        |

#### Фильтрация и поиск (`GET /api/users`)

| Параметр | Тип                     | Описание                                    |
|----------|-------------------------|---------------------------------------------|
| `email`  | `string`                | Поиск по подстроке email (case-insensitive) |
| `role`   | `client` \| `volunteer` | Фильтр по роли                              |
| `limit`  | `integer`               | Количество записей (1–500, по умолчанию 50) |
| `offset` | `integer`               | Смещение (по умолчанию 0)                   |

### Примеры запросов

**Создать пользователя:**

```bash
curl -X POST http://localhost:8000/api/users \
  -H 'Authorization: Bearer dev-token' \
  -H 'Content-Type: application/json' \
  -d '{
    "email": "user@example.com",
    "name": "Ivan Ivanov",
    "role": "client",
    "time_zone": "Europe/Moscow",
    "contacts": [
      {"channel": "telegram", "contact_id": "123456789"},
      {"channel": "push", "contact_id": "fcm-token-abc"}
    ]
  }'
```

**Ответ:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "name": "Ivan Ivanov",
  "role": "client",
  "time_zone": "Europe/Moscow",
  "contacts": [
    {
      "id": "661f9511-f3ac-52e5-b827-557766551111",
      "user_id": "550e8400-e29b-41d4-a716-446655440000",
      "channel": "telegram",
      "contact_id": "123456789",
      "created_at": "2026-04-07T12:00:00Z",
      "updated_at": "2026-04-07T12:00:00Z"
    }
  ],
  "created_at": "2026-04-07T12:00:00Z",
  "updated_at": "2026-04-07T12:00:00Z"
}
```

**Поиск и фильтрация:**

```bash
# Поиск по email + фильтр по роли
curl -H 'Authorization: Bearer dev-token' 'http://localhost:8000/api/users?email=example&role=client&limit=20&offset=0'
```

**Обновить пользователя:**

```bash
curl -X PUT http://localhost:8000/api/users/id/550e8400-e29b-41d4-a716-446655440000 \
  -H 'Authorization: Bearer dev-token' \
  -H 'Content-Type: application/json' \
  -d '{"time_zone": "Asia/Yekaterinburg"}'
```

**Получить по email+role:**

```bash
curl -H 'Authorization: Bearer dev-token' \
  'http://localhost:8000/api/users/roles/client/emails/user@example.com'
```

## Схема базы данных

```
users
├── id          UUID  PK  default: gen_random_uuid()
├── email       TEXT  NOT NULL
├── name        TEXT  NULL
├── role        TEXT  NOT NULL          -- 'client' | 'volunteer'
├── time_zone   TEXT  NULL
├── created_at  TIMESTAMPTZ  NOT NULL
└── updated_at  TIMESTAMPTZ  NOT NULL
    UNIQUE (email, role)

user_contacts
├── id          UUID  PK  default: gen_random_uuid()
├── user_id     UUID  FK → users.id  ON DELETE CASCADE
├── channel     TEXT  NOT NULL          -- 'telegram' | 'push' | ...
├── contact_id  TEXT  NOT NULL          -- chat_id, device token, ...
├── created_at  TIMESTAMPTZ  NOT NULL
└── updated_at  TIMESTAMPTZ  NOT NULL
    UNIQUE (user_id, channel)
```

## CRM-синхронизация

Сервис ожидает от CRM ответ следующего формата:

```json
{
  "encrypted_data": "<base64-encoded ciphertext>",
  "iv": "<base64-encoded IV (16 bytes)>"
}
```

Расшифрованный plaintext — JSON-массив пользователей:

```json
[
  {
    "email": "user@example.com",
    "name": "Ivan Ivanov",
    "role": "client",
    "time_zone": "Europe/Moscow",
    "contacts": [
      {
        "channel": "telegram",
        "contact_id": "123456789"
      },
      {
        "channel": "push",
        "contact_id": "fcm-token-abc"
      }
    ]
  },
  {
    "email": "vol@example.com",
    "name": null,
    "role": "volunteer",
    "time_zone": null,
    "contacts": []
  }
]
```

Алгоритм: **AES-256-CBC** с **PKCS7**-паддингом. Ключ задаётся через `CRM_ENCRYPTION_KEY` в виде hex-строки (64
символа).

## Миграции

```bash
# Создать новую миграцию (autogenerate из моделей)
alembic revision --autogenerate -m "add some field"

# Применить все миграции
alembic upgrade head

# Откатить последнюю миграцию
alembic downgrade -1

# Посмотреть текущий revision
alembic current
```

## Разработка

```bash
# Линтинг и форматирование
ruff check --fix .
ruff format .

# Pre-commit хуки
pre-commit install
pre-commit run --all-files
```
