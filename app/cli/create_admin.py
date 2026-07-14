import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from getpass import getpass
from typing import Protocol, TextIO

from app.core.config import Settings
from app.infrastructure.database import Database
from app.repositories.admin_user import AdminUserRepository
from app.services.admin_auth import (
    AdminAccountService,
    AdminAuthUnavailableError,
    AdminUsernameExistsError,
    InvalidAdminUsernameError,
)


class DatabaseFactory(Protocol):
    def __call__(self, url: str, *, timeout_seconds: float) -> Database: ...


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the initial ResumeGraph administrator.")
    parser.add_argument("--username", required=True, help="Administrator username")
    return parser.parse_args(argv)


async def run_create_admin(
    username: str,
    *,
    settings: Settings | None = None,
    password_reader: Callable[[str], str] = getpass,
    database_factory: DatabaseFactory = Database,
    repository_factory: Callable[[Database], AdminUserRepository] = AdminUserRepository,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output = stdout or sys.stdout
    error_output = stderr or sys.stderr
    application_settings = settings or Settings()
    database = database_factory(
        application_settings.database_url.get_secret_value(),
        timeout_seconds=application_settings.dependency_timeout_seconds,
    )
    try:
        password = password_reader("Password: ")
        confirmed_password = password_reader("Confirm password: ")
        if password != confirmed_password:
            print("Administrator passwords do not match.", file=error_output)
            return 1

        service = AdminAccountService(
            repository_factory(database),
            dependency_timeout_seconds=application_settings.dependency_timeout_seconds,
        )
        try:
            principal = await service.create_admin(username, password)
        except AdminUsernameExistsError:
            print("Administrator username already exists.", file=error_output)
            return 1
        except InvalidAdminUsernameError:
            print("Administrator username is invalid.", file=error_output)
            return 1
        except ValueError as error:
            print(str(error), file=error_output)
            return 1
        except AdminAuthUnavailableError:
            print("Administrator persistence is unavailable.", file=error_output)
            return 1

        print(
            f"Created administrator '{principal.username}' with id {principal.id}.",
            file=output,
        )
        return 0
    finally:
        await database.close()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    return asyncio.run(run_create_admin(arguments.username))


if __name__ == "__main__":
    raise SystemExit(main())
