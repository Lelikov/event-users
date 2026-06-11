# Build context MUST be the monorepo root (event-schemas is a relative path dependency):
#   docker build -f event-users/Dockerfile .
ARG BASE_IMAGE="python:3.14.0"

FROM ${BASE_IMAGE} AS base

ENV APP_PATH="/app/event-users"
ENV PATH="${APP_PATH}/.venv/bin:${PATH}"

WORKDIR ${APP_PATH}

FROM base AS deps

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir --upgrade uv==0.11.3

# Mirror the monorepo layout so the ../event-schemas editable path in uv.lock resolves.
COPY event-schemas /app/event-schemas
COPY event-users/pyproject.toml event-users/uv.lock ${APP_PATH}/
RUN uv sync --frozen --no-install-project --no-dev

FROM deps AS development

COPY event-users/alembic.ini ${APP_PATH}/
COPY event-users/alembic ${APP_PATH}/alembic
COPY event-users/event_users ${APP_PATH}/event_users
COPY event-users/uvicorn_config.json ${APP_PATH}/
COPY event-users/entrypoint.sh ${APP_PATH}/entrypoint.sh
RUN chmod +x ${APP_PATH}/entrypoint.sh

EXPOSE 8888

ENTRYPOINT ["./entrypoint.sh"]
