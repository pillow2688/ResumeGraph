from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from sqlalchemy import CheckConstraint, Column, ForeignKeyConstraint, MetaData, Table


class MigrationOperationsRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def create_table(self, name: str, *elements: object) -> None:
        Table(name, MetaData(), *elements)
        self.calls.append(("create_table", name, elements))

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

    def drop_table(self, name: str) -> None:
        self.calls.append(("drop_table", name, ()))

    def execute(self, statement: object) -> None:
        self.calls.append(("execute", str(statement), ()))

    def drop_constraint(self, name: str, table_name: str, *, type_: str) -> None:
        self.calls.append(("drop_constraint", name, (table_name, type_)))

    def create_check_constraint(self, name: str, table_name: str, condition: str) -> None:
        self.calls.append(("create_check_constraint", name, (table_name, condition)))


def load_migration() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "f3a9c2d8e4b1_create_phase_2_3_ingestion.py"
    )
    spec = spec_from_file_location("phase_2_3_migration", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase_2_3_migration_extends_status_and_creates_exact_tables() -> None:
    migration = load_migration()
    recorder = MigrationOperationsRecorder()
    migration.op = recorder

    migration.upgrade()

    assert migration.down_revision == "d7f6a2b4c8e1"
    assert recorder.calls[:2] == [
        (
            "drop_constraint",
            "ck_document_versions_status_draft",
            ("document_versions", "check"),
        ),
        (
            "create_check_constraint",
            "ck_document_versions_status_valid",
            (
                "document_versions",
                "status IN ('draft', 'processing', 'ready_for_review')",
            ),
        ),
    ]

    tables = {
        name: elements for action, name, elements in recorder.calls if action == "create_table"
    }
    assert set(tables) == {"ingestion_jobs", "document_chunks"}
    job_columns = {item.name: item for item in tables["ingestion_jobs"] if isinstance(item, Column)}
    chunk_columns = {
        item.name: item for item in tables["document_chunks"] if isinstance(item, Column)
    }
    assert set(job_columns) == {
        "id",
        "document_version_id",
        "status",
        "stage",
        "progress",
        "error_message",
        "created_at",
        "started_at",
        "finished_at",
    }
    assert set(chunk_columns) == {
        "id",
        "document_version_id",
        "chunk_index",
        "heading_path",
        "content",
        "content_hash",
        "character_count",
        "enabled",
        "created_at",
    }
    assert job_columns["started_at"].nullable is True
    assert job_columns["finished_at"].nullable is True
    assert chunk_columns["enabled"].server_default is not None

    job_checks = {
        str(item.sqltext) for item in tables["ingestion_jobs"] if isinstance(item, CheckConstraint)
    }
    assert job_checks == {
        "status IN ('pending', 'processing', 'completed', 'failed')",
        "stage IN ('reading', 'cleaning', 'chunking', 'saving')",
        "progress >= 0 AND progress <= 100",
    }
    chunk_checks = {
        str(item.sqltext) for item in tables["document_chunks"] if isinstance(item, CheckConstraint)
    }
    assert chunk_checks == {"chunk_index >= 0", "character_count >= 0"}
    for table_name in ("ingestion_jobs", "document_chunks"):
        foreign_keys = [
            item for item in tables[table_name] if isinstance(item, ForeignKeyConstraint)
        ]
        assert len(foreign_keys) == 1
        assert foreign_keys[0].ondelete == "CASCADE"

    active_index = next(
        call for call in recorder.calls if call[1] == "uq_ingestion_jobs_active_version"
    )
    assert active_index[2][2] is True
    assert str(active_index[2][3]["postgresql_where"]) == ("status IN ('pending', 'processing')")


def test_phase_2_3_migration_downgrade_removes_dependents_and_restores_draft() -> None:
    migration = load_migration()
    recorder = MigrationOperationsRecorder()
    migration.op = recorder

    migration.downgrade()

    drop_tables = [call[1] for call in recorder.calls if call[0] == "drop_table"]
    assert drop_tables == ["document_chunks", "ingestion_jobs"]
    assert recorder.calls[-2:] == [
        (
            "drop_constraint",
            "ck_document_versions_status_valid",
            ("document_versions", "check"),
        ),
        (
            "create_check_constraint",
            "ck_document_versions_status_draft",
            ("document_versions", "status = 'draft'"),
        ),
    ]
