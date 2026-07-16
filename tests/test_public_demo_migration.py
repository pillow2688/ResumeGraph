from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from sqlalchemy import CheckConstraint, Column, ForeignKeyConstraint


class MigrationOperationsRecorder:
    def __init__(self) -> None:
        self.created: tuple[str, tuple[object, ...]] | None = None
        self.dropped: list[str] = []

    def create_table(self, table_name: str, *elements: object) -> None:
        self.created = (table_name, elements)

    def drop_table(self, table_name: str) -> None:
        self.dropped.append(table_name)


def load_migration() -> ModuleType:
    path = (
        Path(__file__).parents[1] / "alembic" / "versions" / "c7d9e2f4a6b8_phase_4_5_public_demo.py"
    )
    spec = spec_from_file_location("phase_4_5_public_demo", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase_4_5_migration_creates_only_the_singleton_public_demo_table() -> None:
    migration = load_migration()
    recorder = MigrationOperationsRecorder()
    migration.op = recorder

    migration.upgrade()

    assert migration.down_revision == "b4f8a1c2d3e5"
    assert recorder.created is not None
    table_name, elements = recorder.created
    assert table_name == "public_demo_config"
    columns = {element.name: element for element in elements if isinstance(element, Column)}
    assert set(columns) == {
        "id",
        "candidate_name",
        "default_access_grant_id",
        "enabled",
        "created_at",
        "updated_at",
    }
    assert str(columns["id"].server_default.arg) == "1"
    assert columns["default_access_grant_id"].nullable is False
    checks = {str(element.sqltext) for element in elements if isinstance(element, CheckConstraint)}
    assert checks == {"id = 1"}
    foreign_keys = [element for element in elements if isinstance(element, ForeignKeyConstraint)]
    assert len(foreign_keys) == 1
    assert list(foreign_keys[0].elements)[0].target_fullname == "access_grants.id"


def test_phase_4_5_migration_downgrade_only_removes_the_new_table() -> None:
    migration = load_migration()
    recorder = MigrationOperationsRecorder()
    migration.op = recorder

    migration.downgrade()

    assert recorder.dropped == ["public_demo_config"]
    assert recorder.created is None
