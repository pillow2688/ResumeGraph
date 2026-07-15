from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from sqlalchemy import CheckConstraint, Column, ForeignKeyConstraint, MetaData, Table


class MigrationOperationsRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def execute(self, statement: object) -> None:
        self.calls.append(("execute", str(statement), ()))

    def add_column(self, table_name: str, column: Column) -> None:
        self.calls.append(("add_column", column.name, (table_name, column)))

    def drop_column(self, table_name: str, column_name: str) -> None:
        self.calls.append(("drop_column", column_name, (table_name,)))

    def create_table(self, name: str, *elements: object) -> None:
        Table(name, MetaData(), *elements)
        self.calls.append(("create_table", name, elements))

    def drop_table(self, name: str) -> None:
        self.calls.append(("drop_table", name, ()))

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

    def drop_constraint(self, name: str, table_name: str, *, type_: str) -> None:
        self.calls.append(("drop_constraint", name, (table_name, type_)))

    def create_check_constraint(self, name: str, table_name: str, condition: str) -> None:
        self.calls.append(("create_check_constraint", name, (table_name, condition)))


def load_migration() -> ModuleType:
    path = (
        Path(__file__).parents[1] / "alembic" / "versions" / "c8e4f1a7b2d9_create_phase_2_4_mvp.py"
    )
    spec = spec_from_file_location("phase_2_4_mvp_migration", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase_2_4_migration_is_minimal_and_enables_pgvector() -> None:
    migration = load_migration()
    recorder = MigrationOperationsRecorder()
    migration.op = recorder

    migration.upgrade()

    assert migration.down_revision == "f3a9c2d8e4b1"
    assert recorder.calls[0] == ("execute", "CREATE EXTENSION IF NOT EXISTS vector", ())
    added = {name: payload for action, name, payload in recorder.calls if action == "add_column"}
    assert set(added) == {
        "job_type",
        "auto_indexable",
        "quality_issues",
        "extracted_metadata",
        "quality_checked_at",
        "quality_model",
        "quality_reason",
        "current_published_version_id",
    }

    table_elements = next(
        payload
        for action, name, payload in recorder.calls
        if action == "create_table" and name == "chunk_embeddings"
    )
    columns = {item.name: item for item in table_elements if isinstance(item, Column)}
    assert set(columns) == {
        "id",
        "chunk_id",
        "embedding",
        "provider_name",
        "model_name",
        "dimensions",
        "content_hash",
        "created_at",
    }
    assert columns["embedding"].type.__class__.__name__ == "VECTOR"
    foreign_keys = [item for item in table_elements if isinstance(item, ForeignKeyConstraint)]
    assert len(foreign_keys) == 1 and foreign_keys[0].ondelete == "CASCADE"
    unique_sets = {
        tuple(column.name for column in item.columns)
        for item in table_elements
        if item.__class__.__name__ == "UniqueConstraint"
    }
    assert ("chunk_id", "provider_name", "model_name", "dimensions") in unique_sets
    checks = {str(item.sqltext) for item in table_elements if isinstance(item, CheckConstraint)}
    assert checks == {"dimensions > 0"}

    check_calls = {
        name: payload
        for action, name, payload in recorder.calls
        if action == "create_check_constraint"
    }
    assert "knowledge_indexing" in check_calls["ck_ingestion_jobs_type_valid"][1]
    assert "rule_check" in check_calls["ck_ingestion_jobs_stage_valid"][1]
    assert "indexing_failed" in check_calls["ck_document_versions_status_valid"][1]
    assert "published" in check_calls["ck_document_versions_status_valid"][1]
    assert "superseded" in check_calls["ck_document_versions_status_valid"][1]


def test_phase_2_4_downgrade_removes_dependents_before_extension_and_columns() -> None:
    migration = load_migration()
    recorder = MigrationOperationsRecorder()
    migration.op = recorder

    migration.downgrade()

    actions = [call[:2] for call in recorder.calls]
    assert actions.index(("drop_table", "chunk_embeddings")) < actions.index(
        ("execute", "DROP EXTENSION IF EXISTS vector")
    )
    assert ("drop_column", "current_published_version_id") in actions
    assert ("drop_column", "auto_indexable") in actions
    executed_sql = [call[1] for call in recorder.calls if call[0] == "execute"]
    version_reset = next(sql for sql in executed_sql if "UPDATE document_versions" in sql)
    assert (
        "published" in version_reset
        and "superseded" in version_reset
        and "indexing_failed" in version_reset
    )
    indexing_cleanup = next(sql for sql in executed_sql if "knowledge_indexing" in sql)
    stage_reset = next(sql for sql in executed_sql if "UPDATE ingestion_jobs SET stage" in sql)
    assert "DELETE FROM ingestion_jobs" in indexing_cleanup
    assert "rule_check" in stage_reset and "embedding" in stage_reset
    drop_job_type = actions.index(("drop_column", "job_type"))
    assert (
        recorder.calls.index(next(call for call in recorder.calls if call[1] == indexing_cleanup))
        < drop_job_type
    )
    assert recorder.calls.index(
        next(call for call in recorder.calls if call[1] == stage_reset)
    ) < actions.index(("create_check_constraint", "ck_ingestion_jobs_stage_valid"))
