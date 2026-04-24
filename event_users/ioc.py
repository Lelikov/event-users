from collections.abc import AsyncGenerator

import structlog
from dishka import Provider, Scope, provide
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from event_users.adapters.cache_notifier import CacheNotifier
from event_users.adapters.sql import SqlExecutor
from event_users.adapters.users_db import UsersDBAdapter
from event_users.config import Settings
from event_users.controllers.users import UsersController
from event_users.crm.client import CrmClient
from event_users.crm.sync import CrmSyncRunner
from event_users.interfaces.cache_notifier import ICacheNotifier
from event_users.interfaces.sql import ISqlExecutor, ISqlExecutorFactory
from event_users.interfaces.users import IUsersController, IUsersDBAdapter


logger = structlog.get_logger(__name__)


class AppProvider(Provider):
    @provide(scope=Scope.APP)
    def provide_settings(self) -> Settings:
        settings = Settings()
        logger.info(
            "Settings initialized",
            debug=settings.debug,
            log_level=settings.log_level,
        )
        return settings

    @provide(scope=Scope.APP)
    async def provide_db_engine(self, settings: Settings) -> AsyncGenerator[AsyncEngine]:
        engine = create_async_engine(
            str(settings.postgres_dsn),
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )
        try:
            yield engine
        finally:
            await engine.dispose()

    @provide(scope=Scope.APP)
    def provide_sessionmaker(self, engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(
            bind=engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @provide(scope=Scope.REQUEST)
    async def provide_session(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> AsyncGenerator[AsyncSession]:
        async with sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @provide(scope=Scope.REQUEST)
    def provide_sql_executor(self, session: AsyncSession) -> ISqlExecutor:
        return SqlExecutor(session)

    @provide(scope=Scope.REQUEST)
    def provide_users_db_adapter(self, sql_executor: ISqlExecutor) -> IUsersDBAdapter:
        return UsersDBAdapter(sql_executor)

    @provide(scope=Scope.REQUEST)
    def provide_users_controller(self, db_adapter: IUsersDBAdapter) -> IUsersController:
        return UsersController(db_adapter)

    @provide(scope=Scope.APP)
    def provide_sql_executor_factory(self) -> ISqlExecutorFactory:
        def factory(session: AsyncSession) -> ISqlExecutor:
            return SqlExecutor(session)

        return factory

    @provide(scope=Scope.APP)
    def provide_crm_client(self, settings: Settings) -> CrmClient:
        logger.info("Providing CrmClient", crm_url=settings.crm_api_url)
        return CrmClient(api_url=settings.crm_api_url, api_token=settings.crm_api_token)

    @provide(scope=Scope.APP)
    def provide_crm_sync_runner(
        self,
        settings: Settings,
        crm_client: CrmClient,
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> CrmSyncRunner:
        encryption_key = bytes.fromhex(settings.crm_encryption_key)
        logger.info("Providing CrmSyncRunner", interval=settings.crm_sync_interval_seconds)
        return CrmSyncRunner(
            crm_client=crm_client,
            sessionmaker=sessionmaker,
            encryption_key=encryption_key,
            interval=settings.crm_sync_interval_seconds,
        )

    # ========== event-admin cache invalidation ==========

    @provide(scope=Scope.APP)
    async def provide_cache_notifier(self, settings: Settings) -> AsyncGenerator[ICacheNotifier]:
        async with AsyncClient(base_url=settings.event_admin_url, timeout=10) as client:
            yield CacheNotifier(http_client=client, token=settings.event_admin_cache_token)
