import uuid
from typing import Annotated, Literal

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, HTTPException, Query, status

from event_users.auth import verify_bearer_token
from event_users.errors import ConflictError
from event_users.interfaces.users import IUsersController
from event_users.schemas.users import (
    CreateUserRequest,
    ListUsersParams,
    ListUsersResponse,
    UpdateUserRequest,
    UserResponse,
)


logger = structlog.get_logger(__name__)

root_router = APIRouter(route_class=DishkaRoute, dependencies=[Depends(verify_bearer_token)])
users_router = APIRouter(prefix="/api/users", tags=["users"], route_class=DishkaRoute)


@users_router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    controller: FromDishka[IUsersController],
) -> UserResponse:
    try:
        dto = await controller.create_user(body.to_dto())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return UserResponse.from_dto(dto)


@users_router.put("/id/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    controller: FromDishka[IUsersController],
) -> UserResponse:
    try:
        dto = await controller.update_user(user_id, body.to_dto())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    if dto is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found")
    return UserResponse.from_dto(dto)


@users_router.get("/roles/{role}/emails/{email}", response_model=UserResponse)
async def get_user_by_email_role(
    controller: FromDishka[IUsersController],
    role: Literal["client", "organizer"],
    email: str,
) -> UserResponse:
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


health_router = APIRouter(tags=["health"])


@health_router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


root_router.include_router(users_router)
root_router.include_router(health_router)
