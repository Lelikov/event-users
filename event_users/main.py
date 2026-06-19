from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from logging import getLevelNamesMapping

import structlog
from dishka import make_async_container
from dishka.integrations.fastapi import FastapiProvider, setup_dishka
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from event_users.config import Settings, get_settings
from event_users.consumer import EmailChangeConsumer
from event_users.ioc import AppProvider
from event_users.logger import setup_logger
from event_users.metrics import HttpMetricsMiddleware
from event_users.routes import root_router
from event_users.telemetry import instrument_asyncpg, instrument_fastapi, setup_tracing


container = make_async_container(AppProvider(), FastapiProvider())
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    settings = await container.get(Settings)
    log_level = getLevelNamesMapping().get(settings.log_level)
    setup_logger(log_level=log_level, console_render=settings.debug)

    logger.info(
        "Starting event-users application",
        log_level=settings.log_level,
        debug=settings.debug,
    )
    email_consumer = None
    if settings.is_consumer_enabled:
        email_consumer = await container.get(EmailChangeConsumer)
        await email_consumer.start()
        logger.info("Email change consumer started")

    yield

    logger.info("Shutting down event-users application")
    if email_consumer is not None:
        await email_consumer.stop()
    await container.close()
    logger.info("Event-users application shutdown complete")


app = FastAPI(title="event-users", version="0.1.0", lifespan=lifespan)
setup_tracing()
instrument_fastapi(app)
instrument_asyncpg()
setup_dishka(container=container, app=app)
app.include_router(root_router)

# Auth is enforced per-router (require_admin on every /api/users route);
# /health is intentionally public.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(HttpMetricsMiddleware)
