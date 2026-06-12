import uuid
from typing import Annotated, Literal

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from event_users import metrics
from event_users.auth import TokenPayload, require_admin
from event_users.errors import ConflictError
from event_users.interfaces.cache_notifier import ICacheNotifier
from event_users.interfaces.changelog import IEmailChangelogDBAdapter
from event_users.interfaces.users import IUsersController
from event_users.schemas.changelog import EmailChangelogEntryResponse, EmailChangelogResponse
from event_users.schemas.users import (
    CreateUserRequest,
    GetUsersByIdsRequest,
    GetUsersByIdsResponse,
    ListUsersParams,
    ListUsersResponse,
    UpdateUserRequest,
    UserResponse,
)


logger = structlog.get_logger(__name__)

# Every /api/users route (reads included — they expose PII) requires the admin
# role; tokens are decoded once, in auth.verify_bearer_token.
root_router = APIRouter(route_class=DishkaRoute)
users_router = APIRouter(
    prefix="/api/users",
    tags=["users"],
    route_class=DishkaRoute,
    dependencies=[Depends(require_admin)],
)


@users_router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    body: CreateUserRequest,
    controller: FromDishka[IUsersController],
    notifier: FromDishka[ICacheNotifier],
    session: FromDishka[AsyncSession],
) -> UserResponse:
    try:
        dto = await controller.create_user(body.to_dto())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    # Commit BEFORE invalidating: otherwise event-admin can repopulate its
    # cache from the pre-change data while this transaction is still open.
    await session.commit()
    await notifier.invalidate()
    return UserResponse.from_dto(dto)


@users_router.patch(
    "/id/{user_id}",
    response_model=UserResponse,
)
async def update_user(
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    controller: FromDishka[IUsersController],
    notifier: FromDishka[ICacheNotifier],
    session: FromDishka[AsyncSession],
    admin: Annotated[TokenPayload, Depends(require_admin)],
) -> UserResponse:
    try:
        dto = await controller.update_user(user_id, body.to_dto(), changed_by=admin.sub)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    if dto is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found")
    # Commit BEFORE invalidating (same ordering as the consumer path).
    await session.commit()
    await notifier.invalidate()
    return UserResponse.from_dto(dto)


@users_router.post("/by-ids", response_model=GetUsersByIdsResponse)
async def get_users_by_ids(
    body: GetUsersByIdsRequest,
    controller: FromDishka[IUsersController],
) -> GetUsersByIdsResponse:
    if len(body.ids) > 200:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Maximum 200 IDs per request",
        )
    unique_ids = list(set(body.ids))
    items = await controller.get_users_by_ids(unique_ids)
    return GetUsersByIdsResponse(items=[UserResponse.from_dto(u) for u in items])


@users_router.get("/by-identity", response_model=UserResponse)
async def get_user_by_identity(
    controller: FromDishka[IUsersController],
    email: Annotated[str, Query(description="Exact email match")],
    role: Annotated[Literal["client", "organizer"], Query(description="User role")],
) -> UserResponse:
    """Exact-match lookup with the email in query params (not the URL path).

    Emails contain '+', '.' and '%', which decode inconsistently across
    proxies as path segments and end up in access logs.
    """
    dto = await controller.get_user_by_email_role(email=email, role=role)
    if dto is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with email={email!r} and role={role!r} not found",
        )
    return UserResponse.from_dto(dto)


@users_router.get("/id/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    controller: FromDishka[IUsersController],
) -> UserResponse:
    dto = await controller.get_user(user_id)
    if dto is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found")
    return UserResponse.from_dto(dto)


@users_router.get("", response_model=ListUsersResponse)
async def list_users(
    controller: FromDishka[IUsersController],
    email: Annotated[str | None, Query(description="Search by email (case-insensitive partial match)")] = None,
    role: Annotated[
        Literal["client", "organizer"] | None,
        Query(description="Filter by role: client or organizer"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ListUsersResponse:
    params = ListUsersParams(email=email, role=role, limit=limit, offset=offset)
    items, total = await controller.list_users(params.to_dto())
    return ListUsersResponse(
        items=[UserResponse.from_dto(u) for u in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@users_router.get("/{user_id}/email-changelog", response_model=EmailChangelogResponse)
async def get_email_changelog(
    user_id: uuid.UUID,
    changelog_adapter: FromDishka[IEmailChangelogDBAdapter],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EmailChangelogResponse:
    entries, total = await changelog_adapter.get_changelog(user_id, limit=limit, offset=offset)
    return EmailChangelogResponse(
        items=[EmailChangelogEntryResponse.from_dto(e) for e in entries],
        total=total,
    )


health_router = APIRouter(tags=["health"], route_class=DishkaRoute)

READY_CHECK_QUERY = "select 1"


@health_router.get("/health")
async def health() -> dict:
    """Liveness probe: the process is up and serving HTTP. No dependency calls."""
    return {"status": "ok"}


@health_router.get("/metrics")
async def metrics_endpoint() -> Response:
    """Prometheus exposition endpoint."""
    return metrics.metrics_response()


@health_router.get("/ready")
async def ready(engine: FromDishka[AsyncEngine]) -> JSONResponse:
    """Readiness probe: verifies PostgreSQL connectivity (the only critical dependency)."""
    database_ok = False
    try:
        async with engine.connect() as connection:
            await connection.execute(text(READY_CHECK_QUERY))
        database_ok = True
    except Exception:
        logger.exception("Readiness check failed: database unreachable")

    checks = {"database": database_ok}
    if not database_ok:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "checks": checks},
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ready", "checks": checks})


root_router.include_router(users_router)
root_router.include_router(health_router)
