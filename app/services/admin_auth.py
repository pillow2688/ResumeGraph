import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.core.security import (
    MAX_ADMIN_PASSWORD_LENGTH,
    MIN_ADMIN_PASSWORD_LENGTH,
    generate_session_token,
    hash_password,
    normalize_admin_username,
    verify_password,
)
from app.infrastructure.admin_session import AdminSessionData
from app.infrastructure.health import DependencyUnavailableError
from app.models import AdminUser
from app.repositories.admin_user import (
    AdminRepositoryUnavailableError,
    DuplicateAdminUsernameError,
)
from app.schemas.admin_auth import AdminPrincipal

DUMMY_ADMIN_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$Qsz3xWoYqCXaR5WcDncfjw$"
    "iBaicGpw3Y/c31UZdU4o3HX6p/65Sb7ZIK1+CgONuxI"
)


class AdminRepository(Protocol):
    async def get_by_username(self, username: str) -> AdminUser | None: ...

    async def get_by_id(self, admin_id: UUID) -> AdminUser | None: ...

    async def create(self, *, username: str, password_hash: str) -> AdminUser: ...


class AdminSessionBackend(Protocol):
    async def create(
        self,
        *,
        session_token: str,
        admin_id: UUID,
        username: str,
        ttl_seconds: int,
    ) -> AdminSessionData: ...

    async def read(self, session_token: str) -> AdminSessionData | None: ...

    async def delete(self, session_token: str) -> None: ...


class AdminLoginLimiter(Protocol):
    async def is_limited(self, username: str, client_host: str) -> bool: ...

    async def record_failure(self, username: str, client_host: str) -> int: ...

    async def clear(self, username: str, client_host: str) -> None: ...


class InvalidCredentialsError(Exception):
    pass


class AdminLoginRateLimitedError(Exception):
    pass


class InvalidAdminSessionError(Exception):
    pass


class AdminUsernameExistsError(Exception):
    pass


class InvalidAdminUsernameError(Exception):
    pass


class AdminAuthUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Administrator authentication is temporarily unavailable.")


async def _await_dependency[T](awaitable: Awaitable[T], timeout_seconds: float) -> T:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as error:
        raise AdminAuthUnavailableError from error


@dataclass(frozen=True)
class AdminLoginResult:
    principal: AdminPrincipal
    session_token: str


class AdminAccountService:
    def __init__(
        self,
        repository: AdminRepository,
        *,
        dependency_timeout_seconds: float = 3.0,
    ) -> None:
        self._repository = repository
        self._dependency_timeout_seconds = dependency_timeout_seconds

    async def create_admin(self, username: str, password: str) -> AdminPrincipal:
        normalized_username = normalize_admin_username(username)
        if not normalized_username or len(normalized_username) > 100:
            raise InvalidAdminUsernameError
        try:
            existing_admin = await _await_dependency(
                self._repository.get_by_username(normalized_username),
                self._dependency_timeout_seconds,
            )
        except AdminRepositoryUnavailableError as error:
            raise AdminAuthUnavailableError from error
        if existing_admin is not None:
            raise AdminUsernameExistsError

        password_hash = await asyncio.to_thread(hash_password, password)
        try:
            admin = await _await_dependency(
                self._repository.create(
                    username=normalized_username,
                    password_hash=password_hash,
                ),
                self._dependency_timeout_seconds,
            )
        except DuplicateAdminUsernameError as error:
            raise AdminUsernameExistsError from error
        except AdminRepositoryUnavailableError as error:
            raise AdminAuthUnavailableError from error
        return AdminPrincipal(id=admin.id, username=admin.username)


class AdminAuthService:
    def __init__(
        self,
        repository: AdminRepository,
        session_store: AdminSessionBackend,
        login_limiter: AdminLoginLimiter,
        *,
        session_ttl_seconds: int,
        login_max_failures: int,
        dependency_timeout_seconds: float = 3.0,
    ) -> None:
        self._repository = repository
        self._session_store = session_store
        self._login_limiter = login_limiter
        self._session_ttl_seconds = session_ttl_seconds
        self._login_max_failures = login_max_failures
        self._dependency_timeout_seconds = dependency_timeout_seconds

    async def create_admin(self, username: str, password: str) -> AdminPrincipal:
        return await AdminAccountService(
            self._repository,
            dependency_timeout_seconds=self._dependency_timeout_seconds,
        ).create_admin(username, password)

    async def login(
        self,
        username: str,
        password: str,
        client_host: str,
    ) -> AdminLoginResult:
        normalized_username = normalize_admin_username(username)
        try:
            if await _await_dependency(
                self._login_limiter.is_limited(normalized_username, client_host),
                self._dependency_timeout_seconds,
            ):
                raise AdminLoginRateLimitedError
            admin = await _await_dependency(
                self._repository.get_by_username(normalized_username),
                self._dependency_timeout_seconds,
            )
        except (DependencyUnavailableError, AdminRepositoryUnavailableError) as error:
            raise AdminAuthUnavailableError from error

        password_length_is_valid = (
            MIN_ADMIN_PASSWORD_LENGTH <= len(password) <= MAX_ADMIN_PASSWORD_LENGTH
        )
        credentials_can_match = admin is not None and password_length_is_valid
        password_hash = admin.password_hash if credentials_can_match else DUMMY_ADMIN_PASSWORD_HASH
        hash_matches = await asyncio.to_thread(
            verify_password,
            password,
            password_hash,
        )
        password_is_valid = credentials_can_match and hash_matches
        if not password_is_valid:
            try:
                failure_count = await _await_dependency(
                    self._login_limiter.record_failure(
                        normalized_username,
                        client_host,
                    ),
                    self._dependency_timeout_seconds,
                )
            except DependencyUnavailableError as error:
                raise AdminAuthUnavailableError from error
            if failure_count >= self._login_max_failures:
                raise AdminLoginRateLimitedError
            raise InvalidCredentialsError

        session_token = generate_session_token()
        try:
            await _await_dependency(
                self._login_limiter.clear(normalized_username, client_host),
                self._dependency_timeout_seconds,
            )
            await _await_dependency(
                self._session_store.create(
                    session_token=session_token,
                    admin_id=admin.id,
                    username=admin.username,
                    ttl_seconds=self._session_ttl_seconds,
                ),
                self._dependency_timeout_seconds,
            )
        except DependencyUnavailableError as error:
            raise AdminAuthUnavailableError from error
        return AdminLoginResult(
            principal=AdminPrincipal(id=admin.id, username=admin.username),
            session_token=session_token,
        )

    async def get_current_admin(self, session_token: str) -> AdminPrincipal:
        try:
            session = await _await_dependency(
                self._session_store.read(session_token),
                self._dependency_timeout_seconds,
            )
            if session is None:
                raise InvalidAdminSessionError
            admin = await _await_dependency(
                self._repository.get_by_id(session.admin_id),
                self._dependency_timeout_seconds,
            )
        except (DependencyUnavailableError, AdminRepositoryUnavailableError) as error:
            raise AdminAuthUnavailableError from error
        if admin is None:
            raise InvalidAdminSessionError
        return AdminPrincipal(id=admin.id, username=admin.username)

    async def logout(self, session_token: str) -> None:
        try:
            await _await_dependency(
                self._session_store.delete(session_token),
                self._dependency_timeout_seconds,
            )
        except DependencyUnavailableError as error:
            raise AdminAuthUnavailableError from error
