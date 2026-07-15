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

    def alter_column(self, table_name: str, column_name: str, **kwargs: object) -> None:
        self.calls.append(("alter_column", column_name, (table_name, kwargs)))

    def create_check_constraint(self, name: str, table_name: str, condition: str) -> None:
        self.calls.append(("create_check_constraint", name, (table_name, condition)))

    def drop_constraint(self, name: str, table_name: str, *, type_: str) -> None:
        self.calls.append(("drop_constraint", name, (table_name, type_)))

    def create_foreign_key(
        self,
        name: str,
        source_table: str,
        referent_table: str,
        local_cols: list[str],
        remote_cols: list[str],
        **kwargs: object,
    ) -> None:
        self.calls.append(
            (
                "create_foreign_key",
                name,
                (source_table, referent_table, tuple(local_cols), tuple(remote_cols), kwargs),
            )
        )

    def create_index(
        self,
        name: str,
        table_name: str,
        columns: list[str],
        *,
        unique: bool,
        **kwargs: object,
    ) -> None:
        self.calls.append(("create_index", name, (table_name, tuple(columns), unique, kwargs)))

    def drop_index(self, name: str, *, table_name: str) -> None:
        self.calls.append(("drop_index", name, (table_name,)))


def load_migration() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "e1b7c9d4a2f6_phase_2_lifecycle_patch.py"
    )
    spec = spec_from_file_location("phase_2_lifecycle_patch", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lifecycle_migration_adds_scope_disable_reason_indexes_and_cascade() -> None:
    migration = load_migration()
    recorder = MigrationOperationsRecorder()
    migration.op = recorder

    migration.upgrade()

    assert migration.down_revision == "c8e4f1a7b2d9"
    added = {name: payload for action, name, payload in recorder.calls if action == "add_column"}
    assert set(added) == {"document_scope", "disabled_reason"}
    document_scope = added["document_scope"][1]
    assert document_scope.nullable is False
    assert document_scope.server_default is not None
    disabled_reason = added["disabled_reason"][1]
    assert disabled_reason.nullable is True

    upgrade_project_alter = next(
        payload
        for action, name, payload in recorder.calls
        if action == "alter_column" and name == "project_id"
    )
    assert upgrade_project_alter[0] == "knowledge_documents"
    assert isinstance(upgrade_project_alter[1]["existing_type"], migration.sa.Uuid)
    assert upgrade_project_alter[1]["nullable"] is True
    checks = {
        name: payload
        for action, name, payload in recorder.calls
        if action == "create_check_constraint"
    }
    assert "document_scope = 'profile'" in checks["ck_knowledge_documents_scope_project"][1]
    assert "administrator" in checks["ck_document_chunks_disabled_reason_valid"][1]
    assert "enabled IS TRUE" in checks["ck_document_chunks_enabled_reason_consistent"][1]

    indexes = {
        name: payload for action, name, payload in recorder.calls if action == "create_index"
    }
    assert indexes["ix_knowledge_documents_scope_published"][:3] == (
        "knowledge_documents",
        ("document_scope", "current_published_version_id"),
        False,
    )
    assert indexes["ix_document_chunks_deduplication"][:3] == (
        "document_chunks",
        ("content_hash", "enabled", "disabled_reason"),
        False,
    )

    cascade_fk = next(
        payload
        for action, name, payload in recorder.calls
        if action == "create_foreign_key"
        and name == "fk_document_versions_document_id_knowledge_documents"
    )
    assert cascade_fk[-1] == {"ondelete": "CASCADE"}
    sql = "\n".join(name for action, name, _payload in recorder.calls if action == "execute")
    assert "UPDATE knowledge_documents" in sql
    assert "exact_duplicate" in sql
    assert "hard_block" in sql


def test_lifecycle_migration_downgrade_restores_project_only_shape_safely() -> None:
    migration = load_migration()
    recorder = MigrationOperationsRecorder()
    migration.op = recorder

    migration.downgrade()

    sql = "\n".join(name for action, name, _payload in recorder.calls if action == "execute")
    assert "DELETE FROM knowledge_documents WHERE document_scope = 'profile'" in sql
    assert "DELETE FROM document_chunks" not in sql
    downgrade_project_alter = next(
        payload
        for action, name, payload in recorder.calls
        if action == "alter_column" and name == "project_id"
    )
    assert downgrade_project_alter[0] == "knowledge_documents"
    assert isinstance(downgrade_project_alter[1]["existing_type"], migration.sa.Uuid)
    assert downgrade_project_alter[1]["nullable"] is False
    dropped = {(action, name) for action, name, _payload in recorder.calls}
    assert ("drop_column", "document_scope") in dropped
    assert ("drop_column", "disabled_reason") in dropped
