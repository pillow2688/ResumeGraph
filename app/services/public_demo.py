from typing import Protocol
from uuid import UUID

from app.repositories.public_demo import (
    PublicDemoRecord,
    PublicDemoRepositoryUnavailableError,
)
from app.schemas.access_grant import AccessGrantMetadata
from app.schemas.public_demo import PublicDemoAdminResponse, PublicDemoStatusResponse
from app.services.access_grant import (
    AccessControlUnavailableError,
    AccessGrantNotFoundError,
    InvalidAccessGrantError,
    RecruiterExchangeResult,
)

PUBLIC_DEMO_UNAVAILABLE_MESSAGE = "AI Interview 尚未开放"


class PublicDemoRepositoryBackend(Protocol):
    async def get(self) -> PublicDemoRecord | None: ...

    async def upsert(
        self,
        *,
        candidate_name: str,
        default_access_grant_id: UUID,
        enabled: bool,
    ) -> PublicDemoRecord: ...


class AccessGrantServiceBackend(Protocol):
    async def get_grant(self, grant_id: UUID) -> AccessGrantMetadata: ...

    async def validate_grant_for_session(self, grant_id: UUID) -> AccessGrantMetadata: ...

    async def create_session_from_grant(self, grant_id: UUID) -> RecruiterExchangeResult: ...


class PublicDemoUnavailableError(Exception):
    pass


class InvalidPublicDemoConfigError(Exception):
    pass


class PublicDemoServiceUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Public Demo is temporarily unavailable.")


def _unavailable_status() -> PublicDemoStatusResponse:
    return PublicDemoStatusResponse(
        available=False,
        message=PUBLIC_DEMO_UNAVAILABLE_MESSAGE,
    )


def _to_admin_response(
    record: PublicDemoRecord,
    grant: AccessGrantMetadata | None,
) -> PublicDemoAdminResponse:
    return PublicDemoAdminResponse(
        configured=True,
        candidate_name=record.candidate_name,
        default_access_grant_id=record.default_access_grant_id,
        default_access_grant=grant,
        enabled=record.enabled,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class PublicDemoService:
    def __init__(
        self,
        repository: PublicDemoRepositoryBackend,
        access_grant_service: AccessGrantServiceBackend,
    ) -> None:
        self._repository = repository
        self._access_grant_service = access_grant_service

    async def get_public_status(self) -> PublicDemoStatusResponse:
        record = await self._get_config()
        if record is None or not record.enabled:
            return _unavailable_status()
        try:
            await self._access_grant_service.validate_grant_for_session(
                record.default_access_grant_id
            )
        except (AccessGrantNotFoundError, InvalidAccessGrantError):
            return _unavailable_status()
        except AccessControlUnavailableError as error:
            raise PublicDemoServiceUnavailableError from error
        return PublicDemoStatusResponse(
            available=True,
            candidate_name=record.candidate_name,
        )

    async def create_public_session(self) -> RecruiterExchangeResult:
        record = await self._get_config()
        if record is None or not record.enabled:
            raise PublicDemoUnavailableError
        try:
            return await self._access_grant_service.create_session_from_grant(
                record.default_access_grant_id
            )
        except (AccessGrantNotFoundError, InvalidAccessGrantError) as error:
            raise PublicDemoUnavailableError from error
        except AccessControlUnavailableError as error:
            raise PublicDemoServiceUnavailableError from error

    async def get_admin_config(self) -> PublicDemoAdminResponse:
        record = await self._get_config()
        if record is None:
            return PublicDemoAdminResponse(configured=False)
        try:
            grant = await self._access_grant_service.get_grant(record.default_access_grant_id)
        except AccessGrantNotFoundError:
            grant = None
        except AccessControlUnavailableError as error:
            raise PublicDemoServiceUnavailableError from error
        return _to_admin_response(record, grant)

    async def update_config(
        self,
        *,
        candidate_name: str,
        default_access_grant_id: UUID,
        enabled: bool,
    ) -> PublicDemoAdminResponse:
        normalized_name = candidate_name.strip()
        if not normalized_name or len(normalized_name) > 200:
            raise InvalidPublicDemoConfigError
        try:
            if enabled:
                grant = await self._access_grant_service.validate_grant_for_session(
                    default_access_grant_id
                )
            else:
                grant = await self._access_grant_service.get_grant(default_access_grant_id)
        except (AccessGrantNotFoundError, InvalidAccessGrantError) as error:
            raise InvalidPublicDemoConfigError from error
        except AccessControlUnavailableError as error:
            raise PublicDemoServiceUnavailableError from error

        try:
            record = await self._repository.upsert(
                candidate_name=normalized_name,
                default_access_grant_id=default_access_grant_id,
                enabled=enabled,
            )
        except PublicDemoRepositoryUnavailableError as error:
            raise PublicDemoServiceUnavailableError from error
        return _to_admin_response(record, grant)

    async def _get_config(self) -> PublicDemoRecord | None:
        try:
            return await self._repository.get()
        except PublicDemoRepositoryUnavailableError as error:
            raise PublicDemoServiceUnavailableError from error
