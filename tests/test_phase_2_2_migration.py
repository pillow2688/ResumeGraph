from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    MetaData,
    Table,
    UniqueConstraint,
)


class MigrationOperationsRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[object, ...]]] = []

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
    ) -> None:
        self.calls.append(("create_index", name, (table_name, tuple(columns), unique)))

    def drop_index(self, name: str, *, table_name: str) -> None:
        self.calls.append(("drop_index", name, (table_name,)))

    def drop_table(self, name: str) -> None:
        self.calls.append(("drop_table", name, ()))


def load_phase_2_2_migration() -> ModuleType:
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "d7f6a2b4c8e1_create_phase_2_2_document_models.py"
    )
    spec = spec_from_file_location("phase_2_2_migration", migration_path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase_2_2_migration_creates_exact_document_tables_and_constraints() -> None:
    migration = load_phase_2_2_migration()
    recorder = MigrationOperationsRecorder()
    migration.op = recorder

    migration.upgrade()

    assert migration.down_revision == "a5b170c969c4"
    table_calls = [call for call in recorder.calls if call[0] == "create_table"]
    assert [call[1] for call in table_calls] == ["knowledge_documents", "document_versions"]

    tables = {name: elements for _, name, elements in table_calls}
    document_columns = {
        element.name: element
        for element in tables["knowledge_documents"]
        if isinstance(element, Column)
    }
    version_columns = {
        element.name: element
        for element in tables["document_versions"]
        if isinstance(element, Column)
    }
    assert set(document_columns) == {"id", "project_id", "title", "created_at", "updated_at"}
    assert set(version_columns) == {
        "id",
        "document_id",
        "version_number",
        "source_type",
        "original_filename",
        "raw_content",
        "content_hash",
        "status",
        "created_at",
    }

    document_foreign_keys = [
        element
        for element in tables["knowledge_documents"]
        if isinstance(element, ForeignKeyConstraint)
    ]
    version_foreign_keys = [
        element
        for element in tables["document_versions"]
        if isinstance(element, ForeignKeyConstraint)
    ]
    assert len(document_foreign_keys) == 1
    assert document_foreign_keys[0].ondelete is None
    assert len(version_foreign_keys) == 1
    assert version_foreign_keys[0].ondelete is None

    unique_constraints = {
        tuple(column.name for column in element.columns)
        for element in tables["document_versions"]
        if isinstance(element, UniqueConstraint)
    }
    assert unique_constraints == {
        ("document_id", "version_number"),
        ("document_id", "content_hash"),
    }
    check_constraints = {
        str(element.sqltext)
        for element in tables["document_versions"]
        if isinstance(element, CheckConstraint)
    }
    assert check_constraints == {
        "version_number > 0",
        "source_type IN ('pasted_markdown', 'markdown_file')",
        "status = 'draft'",
    }
    assert not ({"normalized_content", "processed_at", "embedding"} & version_columns.keys())

    indexes = [call for call in recorder.calls if call[0] == "create_index"]
    assert indexes == [
        (
            "create_index",
            "ix_knowledge_documents_project_id",
            ("knowledge_documents", ("project_id",), False),
        ),
        (
            "create_index",
            "ix_document_versions_document_id",
            ("document_versions", ("document_id",), False),
        ),
    ]


def test_phase_2_2_migration_downgrade_drops_dependents_first() -> None:
    migration = load_phase_2_2_migration()
    recorder = MigrationOperationsRecorder()
    migration.op = recorder

    migration.downgrade()

    assert recorder.calls == [
        ("drop_index", "ix_document_versions_document_id", ("document_versions",)),
        ("drop_table", "document_versions", ()),
        ("drop_index", "ix_knowledge_documents_project_id", ("knowledge_documents",)),
        ("drop_table", "knowledge_documents", ()),
    ]
