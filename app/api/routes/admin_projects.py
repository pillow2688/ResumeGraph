from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.dependencies.admin_auth import get_current_admin
from app.core.exceptions import (
    InvalidProjectRequestResponseError,
    ProjectInUseResponseError,
    ProjectNotFoundResponseError,
    ProjectUnavailableResponseError,
)
from app.schemas.admin_auth import AdminPrincipal
from app.schemas.error import ErrorResponse
from app.schemas.project import ProjectCreateRequest, ProjectResponse, ProjectUpdateRequest
from app.services.project import (
    InvalidProjectRequestError,
    ProjectInUseError,
    ProjectNotFoundError,
    ProjectService,
    ProjectUnavailableError,
)

router = APIRouter(prefix="/api/v1/admin/projects", tags=["admin-projects"])

PROJECT_ERROR_RESPONSES = {
    401: {"description": "Administrator authentication required", "model": ErrorResponse},
    422: {"description": "Invalid project request", "model": ErrorResponse},
    503: {"description": "Project persistence unavailable", "model": ErrorResponse},
}


def _service(request: Request) -> ProjectService:
    return cast(ProjectService, request.app.state.project_service)


def _raise_service_error(error: Exception) -> None:
    if isinstance(error, InvalidProjectRequestError):
        raise InvalidProjectRequestResponseError from error
    if isinstance(error, ProjectNotFoundError):
        raise ProjectNotFoundResponseError from error
    if isinstance(error, ProjectInUseError):
        raise ProjectInUseResponseError from error
    if isinstance(error, ProjectUnavailableError):
        raise ProjectUnavailableResponseError from error
    raise error


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    responses=PROJECT_ERROR_RESPONSES,
)
async def create_project(
    payload: ProjectCreateRequest,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> ProjectResponse:
    try:
        return await _service(request).create_project(
            name=payload.name,
            description=payload.description,
        )
    except (
        InvalidProjectRequestError,
        ProjectUnavailableError,
    ) as error:
        _raise_service_error(error)


@router.get(
    "",
    response_model=list[ProjectResponse],
    responses=PROJECT_ERROR_RESPONSES,
)
async def list_projects(
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> list[ProjectResponse]:
    try:
        return await _service(request).list_projects()
    except ProjectUnavailableError as error:
        _raise_service_error(error)


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    responses={
        **PROJECT_ERROR_RESPONSES,
        404: {"description": "Project not found", "model": ErrorResponse},
    },
)
async def get_project(
    project_id: UUID,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> ProjectResponse:
    try:
        return await _service(request).get_project(project_id)
    except (ProjectNotFoundError, ProjectUnavailableError) as error:
        _raise_service_error(error)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    responses={
        **PROJECT_ERROR_RESPONSES,
        404: {"description": "Project not found", "model": ErrorResponse},
    },
)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdateRequest,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> ProjectResponse:
    try:
        return await _service(request).update_project(
            project_id,
            name=payload.name,
            description=payload.description,
        )
    except (
        InvalidProjectRequestError,
        ProjectNotFoundError,
        ProjectUnavailableError,
    ) as error:
        _raise_service_error(error)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        401: {"description": "Administrator authentication required", "model": ErrorResponse},
        404: {"description": "Project not found", "model": ErrorResponse},
        409: {"description": "Project is in use", "model": ErrorResponse},
        503: {"description": "Project persistence unavailable", "model": ErrorResponse},
    },
)
async def delete_project(
    project_id: UUID,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> Response:
    try:
        await _service(request).delete_project(project_id)
    except (ProjectNotFoundError, ProjectInUseError, ProjectUnavailableError) as error:
        _raise_service_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
