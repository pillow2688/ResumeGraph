import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest

from app.repositories.knowledge_document import (
    DocumentVersionRecord,
    DuplicateDocumentVersionRepositoryError,
    KnowledgeDocumentRecord,
    KnowledgeDocumentRepositoryUnavailableError,
)
from app.services.knowledge_document import (
    DocumentNotFoundError,
    DocumentVersionNotFoundError,
    DuplicateDocumentVersionError,
    InvalidDocumentRequestError,
    InvalidMarkdownContentError,
    InvalidMarkdownEncodingError,
    KnowledgeDocumentService,
    KnowledgeDocumentUnavailableError,
    MarkdownTooLargeError,
    ProjectNotFoundError,
    UnsupportedMarkdownFileError,
)

NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)


def make_version(
    *,
    document_id: UUID,
    version_number: int = 1,
    content: str = "# ResumeGraph\n",
    source_type: str = "pasted_markdown",
    original_filename: str | None = None,
) -> DocumentVersionRecord:
    return DocumentVersionRecord(
        id=uuid4(),
        document_id=document_id,
        version_number=version_number,
        source_type=source_type,
        original_filename=original_filename,
        raw_content=content,
        content_hash=sha256(content.encode()).hexdigest(),
        status="draft",
        created_at=NOW + timedelta(seconds=version_number),
        content_size_bytes=len(content.encode()),
    )


def make_document(
    *,
    project_id: UUID | None = None,
    project_name: str = "ResumeGraph",
    title: str = "Architecture",
) -> KnowledgeDocumentRecord:
    document_id = uuid4()
    version = make_version(document_id=document_id)
    return KnowledgeDocumentRecord(
        id=document_id,
        project_id=project_id or uuid4(),
        project_name=project_name,
        title=title,
        created_at=NOW,
        updated_at=NOW,
        version_count=1,
        latest_version=version,
    )


class FakeKnowledgeDocumentRepository:
    def __init__(self) -> None:
        self.projects: dict[UUID, str] = {}
        self.documents: dict[UUID, KnowledgeDocumentRecord] = {}
        self.versions: dict[UUID, list[DocumentVersionRecord]] = {}
        self.unavailable = False
        self.last_create: dict[str, object] | None = None

    def _check(self) -> None:
        if self.unavailable:
            raise KnowledgeDocumentRepositoryUnavailableError

    async def create_document(self, **kwargs: object) -> KnowledgeDocumentRecord | None:
        self._check()
        project_id = kwargs["project_id"]
        assert isinstance(project_id, UUID)
        project_name = self.projects.get(project_id)
        if project_name is None:
            return None
        self.last_create = kwargs
        document_id = uuid4()
        version = make_version(
            document_id=document_id,
            content=str(kwargs["raw_content"]),
            source_type=str(kwargs["source_type"]),
            original_filename=kwargs["original_filename"],
        )
        version = replace(version, content_hash=str(kwargs["content_hash"]))
        document = KnowledgeDocumentRecord(
            id=document_id,
            project_id=project_id,
            project_name=project_name,
            title=str(kwargs["title"]),
            created_at=NOW,
            updated_at=NOW,
            version_count=1,
            latest_version=version,
        )
        self.documents[document.id] = document
        self.versions[document.id] = [version]
        return document

    async def list_documents(self, project_id: UUID) -> list[KnowledgeDocumentRecord] | None:
        self._check()
        if project_id not in self.projects:
            return None
        return sorted(
            (item for item in self.documents.values() if item.project_id == project_id),
            key=lambda item: (item.updated_at, str(item.id)),
            reverse=True,
        )

    async def get_document(self, document_id: UUID) -> KnowledgeDocumentRecord | None:
        self._check()
        return self.documents.get(document_id)

    async def update_document_title(
        self, document_id: UUID, *, title: str
    ) -> KnowledgeDocumentRecord | None:
        self._check()
        document = self.documents.get(document_id)
        if document is None:
            return None
        updated = replace(
            document,
            title=title,
            updated_at=document.updated_at + timedelta(seconds=1),
        )
        self.documents[document_id] = updated
        return updated

    async def create_version(
        self,
        document_id: UUID,
        **kwargs: object,
    ) -> DocumentVersionRecord | None:
        self._check()
        document = self.documents.get(document_id)
        if document is None:
            return None
        versions = self.versions[document_id]
        if any(item.content_hash == kwargs["content_hash"] for item in versions):
            raise DuplicateDocumentVersionRepositoryError
        version = make_version(
            document_id=document_id,
            version_number=len(versions) + 1,
            content=str(kwargs["raw_content"]),
            source_type=str(kwargs["source_type"]),
            original_filename=kwargs["original_filename"],
        )
        version = replace(version, content_hash=str(kwargs["content_hash"]))
        versions.append(version)
        self.documents[document_id] = replace(
            document,
            version_count=len(versions),
            latest_version=version,
            updated_at=document.updated_at + timedelta(seconds=1),
        )
        return version

    async def list_versions(self, document_id: UUID) -> list[DocumentVersionRecord] | None:
        self._check()
        if document_id not in self.documents:
            return None
        return list(reversed(self.versions[document_id]))

    async def get_version(self, version_id: UUID) -> DocumentVersionRecord | None:
        self._check()
        return next(
            (
                version
                for versions in self.versions.values()
                for version in versions
                if version.id == version_id
            ),
            None,
        )


def make_service(
    repository: FakeKnowledgeDocumentRepository, *, limit: int = 1024, timeout: float = 1
) -> KnowledgeDocumentService:
    return KnowledgeDocumentService(
        repository,
        markdown_max_bytes=limit,
        dependency_timeout_seconds=timeout,
    )


def test_pasted_markdown_creates_document_and_v1_with_hash() -> None:
    repository = FakeKnowledgeDocumentRepository()
    project_id = uuid4()
    repository.projects[project_id] = "ResumeGraph"
    service = make_service(repository)

    created = asyncio.run(
        service.create_document_from_paste(
            project_id,
            title="  Design notes  ",
            content="\ufeff# Design\n\nText",
        )
    )

    assert created.title == "Design notes"
    assert created.version_count == 1
    assert created.latest_version is not None
    assert created.latest_version.version_number == 1
    assert created.latest_version.source_type == "pasted_markdown"
    assert created.latest_version.original_filename is None
    assert created.latest_version.content_size_bytes == len(b"# Design\n\nText")
    assert repository.last_create == {
        "project_id": project_id,
        "title": "Design notes",
        "source_type": "pasted_markdown",
        "original_filename": None,
        "raw_content": "# Design\n\nText",
        "content_hash": sha256(b"# Design\n\nText").hexdigest(),
    }


def test_document_summary_exposes_current_published_version_and_published_status() -> None:
    repository = FakeKnowledgeDocumentRepository()
    project_id = uuid4()
    repository.projects[project_id] = "ResumeGraph"
    document = make_document(project_id=project_id)
    assert document.latest_version is not None
    published_id = document.latest_version.id
    document = replace(
        document,
        current_published_version_id=published_id,
        latest_version=replace(document.latest_version, status="published"),
    )
    repository.documents[document.id] = document
    repository.versions[document.id] = [document.latest_version]

    summary = asyncio.run(make_service(repository).get_document(document.id))

    assert summary.current_published_version_id == published_id
    assert summary.latest_version is not None
    assert summary.latest_version.status == "published"


def test_uploaded_markdown_uses_utf8_bom_and_safe_basename() -> None:
    repository = FakeKnowledgeDocumentRepository()
    project_id = uuid4()
    repository.projects[project_id] = "ResumeGraph"
    service = make_service(repository)

    created = asyncio.run(
        service.create_document_from_upload(
            project_id,
            title="Upload",
            filename=r"C:\\fake\\notes.md",
            content=b"\xef\xbb\xbf# Uploaded",
        )
    )

    assert created.latest_version is not None
    assert created.latest_version.source_type == "markdown_file"
    assert created.latest_version.original_filename == "notes.md"
    assert repository.last_create is not None
    assert repository.last_create["raw_content"] == "# Uploaded"


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
def test_service_rejects_invalid_title(title: str) -> None:
    service = make_service(FakeKnowledgeDocumentRepository())

    with pytest.raises(InvalidDocumentRequestError):
        asyncio.run(service.create_document_from_paste(uuid4(), title=title, content="# Valid"))


@pytest.mark.parametrize("content", ["", "  \n\t", "# bad\x00content"])
def test_service_rejects_empty_or_nul_markdown(content: str) -> None:
    service = make_service(FakeKnowledgeDocumentRepository())

    with pytest.raises(InvalidMarkdownContentError):
        asyncio.run(service.create_document_from_paste(uuid4(), title="Title", content=content))


def test_service_rejects_markdown_over_byte_limit() -> None:
    service = make_service(FakeKnowledgeDocumentRepository(), limit=5)

    with pytest.raises(MarkdownTooLargeError):
        asyncio.run(service.create_document_from_paste(uuid4(), title="Title", content="你好"))


@pytest.mark.parametrize("filename", ["notes.txt", "notes.md.exe", "", "x" * 256 + ".md"])
def test_service_rejects_unsupported_or_unsafe_markdown_filename(filename: str) -> None:
    service = make_service(FakeKnowledgeDocumentRepository())

    with pytest.raises(UnsupportedMarkdownFileError):
        asyncio.run(
            service.create_document_from_upload(
                uuid4(), title="Title", filename=filename, content=b"# valid"
            )
        )


def test_service_rejects_invalid_utf8_upload() -> None:
    service = make_service(FakeKnowledgeDocumentRepository())

    with pytest.raises(InvalidMarkdownEncodingError):
        asyncio.run(
            service.create_document_from_upload(
                uuid4(), title="Title", filename="notes.md", content=b"\xff\xfe"
            )
        )


def test_missing_project_and_documents_map_to_specific_errors() -> None:
    repository = FakeKnowledgeDocumentRepository()
    service = make_service(repository)

    with pytest.raises(ProjectNotFoundError):
        asyncio.run(service.create_document_from_paste(uuid4(), title="Title", content="# Valid"))
    with pytest.raises(ProjectNotFoundError):
        asyncio.run(service.list_documents(uuid4()))
    with pytest.raises(DocumentNotFoundError):
        asyncio.run(service.get_document(uuid4()))
    with pytest.raises(DocumentNotFoundError):
        asyncio.run(service.update_document_title(uuid4(), title="Renamed"))
    with pytest.raises(DocumentNotFoundError):
        asyncio.run(service.list_versions(uuid4()))
    with pytest.raises(DocumentVersionNotFoundError):
        asyncio.run(service.get_version(uuid4()))


def test_new_versions_increment_preserve_old_content_and_reject_duplicate() -> None:
    repository = FakeKnowledgeDocumentRepository()
    project_id = uuid4()
    repository.projects[project_id] = "ResumeGraph"
    service = make_service(repository)
    document = asyncio.run(
        service.create_document_from_paste(project_id, title="Title", content="# v1")
    )

    v2 = asyncio.run(service.create_version_from_paste(document.id, content="# v2"))

    assert v2.version_number == 2
    assert repository.versions[document.id][0].raw_content == "# v1"
    assert repository.versions[document.id][1].raw_content == "# v2"
    with pytest.raises(DuplicateDocumentVersionError):
        asyncio.run(service.create_version_from_paste(document.id, content="# v1"))


def test_list_responses_omit_raw_content_but_version_detail_includes_it() -> None:
    repository = FakeKnowledgeDocumentRepository()
    project_id = uuid4()
    repository.projects[project_id] = "ResumeGraph"
    service = make_service(repository)
    document = asyncio.run(
        service.create_document_from_paste(project_id, title="Title", content="# v1")
    )

    documents = asyncio.run(service.list_documents(project_id))
    versions = asyncio.run(service.list_versions(document.id))
    detail = asyncio.run(service.get_version(repository.versions[document.id][0].id))

    assert "raw_content" not in documents[0].model_dump()
    assert "raw_content" not in versions[0].model_dump()
    assert detail.raw_content == "# v1"
    assert detail.document_id == document.id


def test_repository_failure_and_timeout_are_sanitized() -> None:
    repository = FakeKnowledgeDocumentRepository()
    repository.unavailable = True
    service = make_service(repository)

    with pytest.raises(KnowledgeDocumentUnavailableError) as raised:
        asyncio.run(service.list_documents(uuid4()))
    assert "database" not in str(raised.value).lower()

    class HangingRepository(FakeKnowledgeDocumentRepository):
        async def list_documents(self, project_id: UUID) -> list[KnowledgeDocumentRecord] | None:
            await asyncio.Event().wait()
            return []

    with pytest.raises(KnowledgeDocumentUnavailableError):
        asyncio.run(make_service(HangingRepository(), timeout=0.01).list_documents(uuid4()))
