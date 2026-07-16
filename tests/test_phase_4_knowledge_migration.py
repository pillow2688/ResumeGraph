from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from sqlalchemy import Column


class MigrationOperationsRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def execute(self, statement: object) -> None:
        self.calls.append(("execute", str(statement), ()))

    def add_column(self, table_name: str, column: Column) -> None:
        self.calls.append(("add_column", column.name, (table_name, column)))

    def drop_column(self, table_name: str, column_name: str) -> None:
        self.calls.append(("drop_column", column_name, (table_name,)))

    def create_check_constraint(self, name: str, table_name: str, condition: str) -> None:
        self.calls.append(("create_check_constraint", name, (table_name, condition)))

    def drop_constraint(self, name: str, table_name: str, *, type_: str) -> None:
        self.calls.append(("drop_constraint", name, (table_name, type_)))


def load_migration() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "b4f8a1c2d3e5_phase_4_technical_knowledge.py"
    )
    spec = spec_from_file_location("phase_4_technical_knowledge", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase_4_migration_adds_controlled_scope_and_knowledge_status() -> None:
    migration = load_migration()
    recorder = MigrationOperationsRecorder()
    migration.op = recorder

    migration.upgrade()

    assert migration.down_revision == "e1b7c9d4a2f6"
    added = {name: payload for action, name, payload in recorder.calls if action == "add_column"}
    status_column = added["knowledge_status"][1]
    assert status_column.nullable is False
    assert status_column.server_default is not None

    dropped_checks = {
        name for action, name, _payload in recorder.calls if action == "drop_constraint"
    }
    assert {
        "ck_knowledge_documents_scope_valid",
        "ck_knowledge_documents_scope_project",
    }.issubset(dropped_checks)

    checks = {
        name: payload[1]
        for action, name, payload in recorder.calls
        if action == "create_check_constraint"
    }
    assert "technical" in checks["ck_knowledge_documents_scope_valid"]
    assert "general_knowledge" in checks["ck_knowledge_documents_knowledge_status_valid"]
    assert "project_id IS NULL" in checks["ck_knowledge_documents_scope_project"]
    assert "planned" in checks["ck_knowledge_documents_scope_knowledge_status"]

    sql = "\n".join(name for action, name, _payload in recorder.calls if action == "execute")
    assert "UPDATE knowledge_documents" in sql
    assert "knowledge_status = 'implemented'" in sql


def test_phase_4_migration_downgrade_restores_phase_3_shape_safely() -> None:
    migration = load_migration()
    recorder = MigrationOperationsRecorder()
    migration.op = recorder

    migration.downgrade()

    sql = "\n".join(name for action, name, _payload in recorder.calls if action == "execute")
    assert "RAISE EXCEPTION" in sql
    assert "document_scope = 'technical'" in sql
    assert "knowledge_status = 'planned'" in sql
    assert "DELETE FROM knowledge_documents" not in sql
    assert "document_scope IN ('profile', 'project')" in "\n".join(
        payload[1]
        for action, _name, payload in recorder.calls
        if action == "create_check_constraint"
    )
    assert ("drop_column", "knowledge_status") in {
        (action, name) for action, name, _payload in recorder.calls
    }
