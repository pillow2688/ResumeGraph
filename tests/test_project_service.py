import asyncio
import importlib
import importlib.util
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.repositories.project import (
    ProjectDeleteOutcome,
    ProjectRecord,
    ProjectRepositoryUnavailableError,
)

NOW = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)


def load_project_schema_module():
    name = "app.schemas.project"
    assert importlib.util.find_spec(name) is not None, f"{name} must exist"
    return importlib.import_module(name)


def load_project_service_module():
    name = "app.services.project"
    assert importlib.util.find_spec(name) is not None, f"{name} must exist"
    return importlib.import_module(name)


def make_record(
    *,
    project_id: UUID | None = None,
    name: str = "ResumeGraph",
    description: str = "Fictional description",
    created_at: datetime = NOW,
    updated_at: datetime = NOW,
) -> ProjectRecord:
    return ProjectRecord(
        id=project_id or uuid4(),
        name=name,
        description=description,
        created_at=created_at,
        updated_at=updated_at,
    )


class FakeProjectRepository:
    def __init__(self, records: list[ProjectRecord] | None = None) -> None:
        self.records = {record.id: record for record in records or []}
        self.in_use: set[UUID] = set()
        self.unavailable = False
        self.create_count = 0
        self.last_update: dict[str, object] | None = None

    def _check(self) -> None:
        if self.unavailable:
            raise ProjectRepositoryUnavailableError

    async def create(self, *, name: str, description: str) -> ProjectRecord:
        self._check()
        self.create_count += 1
        timestamp = NOW.replace(second=self.create_count)
        record = make_record(
            name=name,
            description=description,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.records[record.id] = record
        return record

    async def list(self) -> list[ProjectRecord]:
        self._check()
        return sorted(
            self.records.values(),
            key=lambda record: (record.created_at, str(record.id)),
            reverse=True,
        )

    async def get_by_id(self, project_id: UUID) -> ProjectRecord | None:
        self._check()
        return self.records.get(project_id)

    async def update(
        self,
        project_id: UUID,
        *,
        name: str | None,
        description: str | None,
    ) -> ProjectRecord | None:
        self._check()
        self.last_update = {"name": name, "description": description}
        record = self.records.get(project_id)
        if record is None:
            return None
        next_name = record.name if name is None else name
        next_description = record.description if description is None else description
        if next_name == record.name and next_description == record.description:
            return record
        updated = replace(
            record,
            name=next_name,
            description=next_description,
            updated_at=record.updated_at.replace(second=record.updated_at.second + 1),
        )
        self.records[project_id] = updated
        return updated

    async def delete(self, project_id: UUID) -> ProjectDeleteOutcome:
        self._check()
        if project_id not in self.records:
            return ProjectDeleteOutcome.NOT_FOUND
        if project_id in self.in_use:
            return ProjectDeleteOutcome.IN_USE
        self.records.pop(project_id)
        return ProjectDeleteOutcome.DELETED


def test_project_create_schema_normalizes_fields_and_defaults_description() -> None:
    schemas = load_project_schema_module()

    request = schemas.ProjectCreateRequest(name="  ResumeGraph  ")

    assert request.name == "ResumeGraph"
    assert request.description == ""


def test_project_create_schema_normalizes_description() -> None:
    schemas = load_project_schema_module()

    request = schemas.ProjectCreateRequest(
        name="ResumeGraph",
        description="  Fictional project description  ",
    )

    assert request.description == "Fictional project description"


@pytest.mark.parametrize(
    "name",
    ["", "   ", "x" * 201, None],
)
def test_project_create_schema_rejects_invalid_name(name: object) -> None:
    schemas = load_project_schema_module()

    with pytest.raises(ValidationError):
        schemas.ProjectCreateRequest(name=name)


@pytest.mark.parametrize("description", ["x" * 5001, None])
def test_project_create_schema_rejects_invalid_description(description: object) -> None:
    schemas = load_project_schema_module()

    with pytest.raises(ValidationError):
        schemas.ProjectCreateRequest(name="ResumeGraph", description=description)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"name": "  Renamed  "}, {"name": "Renamed", "description": None}),
        ({"description": "  Updated  "}, {"name": None, "description": "Updated"}),
        ({"description": "   "}, {"name": None, "description": ""}),
        (
            {"name": "  Renamed  ", "description": "  Updated  "},
            {"name": "Renamed", "description": "Updated"},
        ),
    ],
)
def test_project_update_schema_supports_normalized_partial_updates(
    payload: dict[str, object],
    expected: dict[str, str | None],
) -> None:
    schemas = load_project_schema_module()

    request = schemas.ProjectUpdateRequest(**payload)

    assert request.model_dump() == expected
    assert request.model_fields_set == set(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": None},
        {"name": "   "},
        {"name": "x" * 201},
        {"description": None},
        {"description": "x" * 5001},
    ],
)
def test_project_update_schema_rejects_invalid_payload(payload: dict[str, object]) -> None:
    schemas = load_project_schema_module()

    with pytest.raises(ValidationError):
        schemas.ProjectUpdateRequest(**payload)


def test_project_response_contains_only_public_fields() -> None:
    schemas = load_project_schema_module()
    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)

    response = schemas.ProjectResponse(
        id=uuid4(),
        name="ResumeGraph",
        description="Fictional description",
        created_at=now,
        updated_at=now,
    )

    assert set(response.model_dump()) == {
        "id",
        "name",
        "description",
        "created_at",
        "updated_at",
    }


def make_service(repository: FakeProjectRepository, *, timeout: float = 1.0):
    services = load_project_service_module()
    return services.ProjectService(repository, dependency_timeout_seconds=timeout)


def test_service_creates_normalized_project_and_returns_safe_response() -> None:
    repository = FakeProjectRepository()
    service = make_service(repository)

    project = asyncio.run(
        service.create_project(
            name="  ResumeGraph  ",
            description="  Fictional description  ",
        )
    )

    assert project.name == "ResumeGraph"
    assert project.description == "Fictional description"
    assert set(project.model_dump()) == {
        "id",
        "name",
        "description",
        "created_at",
        "updated_at",
    }


@pytest.mark.parametrize(
    ("name", "description"),
    [
        ("   ", "description"),
        ("x" * 201, "description"),
        ("ResumeGraph", "x" * 5001),
    ],
)
def test_service_rejects_invalid_create_values(name: str, description: str) -> None:
    services = load_project_service_module()
    service = make_service(FakeProjectRepository())

    with pytest.raises(services.InvalidProjectRequestError):
        asyncio.run(service.create_project(name=name, description=description))


def test_service_lists_and_gets_projects_in_repository_order() -> None:
    first = make_record(name="First", created_at=NOW.replace(second=1))
    second = make_record(name="Second", created_at=NOW.replace(second=2))
    service = make_service(FakeProjectRepository([first, second]))

    listed = asyncio.run(service.list_projects())
    detail = asyncio.run(service.get_project(first.id))

    assert [project.id for project in listed] == [second.id, first.id]
    assert detail.id == first.id


def test_service_missing_detail_and_update_raise_project_not_found() -> None:
    services = load_project_service_module()
    service = make_service(FakeProjectRepository())
    missing_id = uuid4()

    with pytest.raises(services.ProjectNotFoundError):
        asyncio.run(service.get_project(missing_id))
    with pytest.raises(services.ProjectNotFoundError):
        asyncio.run(service.update_project(missing_id, name="Renamed", description=None))


def test_service_updates_partial_fields_and_noop_preserves_updated_at() -> None:
    original = make_record()
    repository = FakeProjectRepository([original])
    service = make_service(repository)

    renamed = asyncio.run(service.update_project(original.id, name="  Renamed  ", description=None))
    described = asyncio.run(
        service.update_project(renamed.id, name=None, description="  Updated  ")
    )
    unchanged = asyncio.run(
        service.update_project(
            described.id,
            name=described.name,
            description=described.description,
        )
    )

    assert renamed.name == "Renamed"
    assert renamed.description == original.description
    assert described.description == "Updated"
    assert unchanged.updated_at == described.updated_at


@pytest.mark.parametrize(
    ("name", "description"),
    [
        (None, None),
        ("   ", None),
        ("x" * 201, None),
        (None, "x" * 5001),
    ],
)
def test_service_rejects_invalid_update_values(
    name: str | None,
    description: str | None,
) -> None:
    services = load_project_service_module()
    record = make_record()
    service = make_service(FakeProjectRepository([record]))

    with pytest.raises(services.InvalidProjectRequestError):
        asyncio.run(
            service.update_project(
                record.id,
                name=name,
                description=description,
            )
        )


def test_service_maps_delete_outcomes_without_modifying_in_use_project() -> None:
    services = load_project_service_module()
    in_use = make_record(name="In use")
    deletable = make_record(name="Deletable")
    repository = FakeProjectRepository([in_use, deletable])
    repository.in_use.add(in_use.id)
    service = make_service(repository)

    with pytest.raises(services.ProjectInUseError):
        asyncio.run(service.delete_project(in_use.id))
    assert in_use.id in repository.records

    asyncio.run(service.delete_project(deletable.id))
    assert deletable.id not in repository.records

    with pytest.raises(services.ProjectNotFoundError):
        asyncio.run(service.delete_project(uuid4()))


def test_service_translates_repository_failure_without_driver_details() -> None:
    services = load_project_service_module()
    repository = FakeProjectRepository()
    repository.unavailable = True
    service = make_service(repository)

    with pytest.raises(services.ProjectUnavailableError) as raised:
        asyncio.run(service.list_projects())

    assert "postgresql" not in str(raised.value).lower()
    assert "driver" not in str(raised.value).lower()


def test_service_times_out_hanging_repository_as_sanitized_unavailable() -> None:
    services = load_project_service_module()

    class HangingRepository(FakeProjectRepository):
        async def list(self) -> list[ProjectRecord]:
            await asyncio.Event().wait()
            return []

    service = make_service(HangingRepository(), timeout=0.01)

    with pytest.raises(services.ProjectUnavailableError) as raised:
        asyncio.run(service.list_projects())

    assert "timeout" not in str(raised.value).lower()
