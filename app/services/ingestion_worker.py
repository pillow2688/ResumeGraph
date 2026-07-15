import asyncio
from collections.abc import Callable
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from app.ingestion.chunking import split_markdown
from app.ingestion.cleaning import CleanedMarkdown, EmptyMarkdownError, clean_markdown
from app.repositories.ingestion import ChunkToSave, IngestionWorkItem


class DocumentProcessingFailedError(Exception):
    pass


class IngestionWorkerRepositoryBackend(Protocol):
    async def begin_job(self, job_id: UUID) -> IngestionWorkItem | None: ...

    async def set_stage(self, job_id: UUID, *, stage: str, progress: int) -> bool: ...

    async def complete_job(self, job_id: UUID, *, chunks: list[ChunkToSave]) -> bool: ...

    async def fail_job(self, job_id: UUID, *, error_message: str) -> None: ...


class IngestionWorker:
    def __init__(
        self,
        repository: IngestionWorkerRepositoryBackend,
        *,
        chunk_max_characters: int,
        cleaner: Callable[[str], CleanedMarkdown] = clean_markdown,
    ) -> None:
        self._repository = repository
        self._chunk_max_characters = chunk_max_characters
        self._cleaner = cleaner

    async def run(self, job_id: UUID) -> None:
        item = await self._repository.begin_job(job_id)
        if item is None:
            return
        try:
            await self._repository.set_stage(job_id, stage="cleaning", progress=25)
            cleaned = self._cleaner(item.raw_content)
            await self._repository.set_stage(job_id, stage="chunking", progress=55)
            drafts = split_markdown(
                cleaned.content,
                max_characters=self._chunk_max_characters,
            )
            chunks = [
                ChunkToSave(
                    chunk_index=draft.chunk_index,
                    heading_path=draft.heading_path,
                    content=draft.content,
                    content_hash=sha256(draft.content.encode("utf-8")).hexdigest(),
                    character_count=len(draft.content),
                )
                for draft in drafts
            ]
            await self._repository.set_stage(job_id, stage="saving", progress=85)
            await self._repository.complete_job(job_id, chunks=chunks)
        except asyncio.CancelledError:
            await asyncio.shield(
                self._repository.fail_job(
                    job_id,
                    error_message="Document processing was interrupted.",
                )
            )
            raise
        except EmptyMarkdownError as error:
            await self._repository.fail_job(
                job_id,
                error_message="Document content is empty after deterministic cleaning.",
            )
            raise DocumentProcessingFailedError("Document processing failed.") from error
        except Exception:
            await self._repository.fail_job(
                job_id,
                error_message="Document processing failed.",
            )
            raise
