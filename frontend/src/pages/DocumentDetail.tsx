import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  createPastedVersion,
  deleteDocumentVersion,
  getDocument,
  getDocumentVersion,
  listDocumentVersions,
  processDocumentVersion,
  publishDocumentVersion,
  startKnowledgeIndexing,
  unpublishDocument,
  updateDocumentTitle,
  uploadVersion,
} from "../api/knowledgeDocuments";
import { Layout } from "../components/Layout";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { MarkdownInputDialog } from "../components/MarkdownInputDialog";
import { documentStatusLabel } from "../components/DocumentWorkflowStatus";
import type {
  DocumentVersion,
  DocumentVersionSummary,
  KnowledgeDocument,
} from "../types/knowledgeDocument";

type DocumentAction = "load" | "save";

function detailErrorMessage(error: unknown, action: DocumentAction): string {
  if (error instanceof ApiError) {
    if (
      error.status === 404 &&
      (error.code === "document_not_found" ||
        error.code === "document_version_not_found")
    ) {
      return error.code === "document_not_found"
        ? "该知识文档不存在或已被删除。"
        : "该文档版本不存在。";
    }
    if (error.status === 409 && error.code === "duplicate_document_version") {
      return "该内容已存在于版本历史中，请提交不同内容。";
    }
    if (error.status === 413 || error.code === "markdown_too_large") {
      return "Markdown 内容不能超过 1 MiB。";
    }
    if (error.status === 415 || error.code === "unsupported_markdown_file") {
      return "只支持 .md 文件。";
    }
    if (
      error.status === 422 ||
      error.code === "invalid_markdown_encoding" ||
      error.code === "invalid_markdown_content"
    ) {
      return "Markdown 内容或编码无效，请检查后重试。";
    }
    if (error.status === 503 || error.status === 0) {
      return "文档服务暂时不可用，请稍后重试。";
    }
  }
  return action === "load"
    ? "加载文档失败，请稍后重试。"
    : "保存文档失败，请稍后重试。";
}

function sourceLabel(version: DocumentVersionSummary): string {
  return version.source_type === "markdown_file"
    ? version.original_filename ?? ".md 文件"
    : "粘贴 Markdown";
}

const DELETABLE_VERSION_STATUSES = new Set([
  "draft",
  "indexing_failed",
  "ready_to_publish",
  "superseded",
]);

export function DocumentDetail() {
  const { documentId = "" } = useParams();
  const navigate = useNavigate();
  const [knowledgeDocument, setKnowledgeDocument] = useState<KnowledgeDocument | null>(null);
  const [versions, setVersions] = useState<DocumentVersionSummary[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<DocumentVersion | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isVersionLoading, setIsVersionLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [title, setTitle] = useState("");
  const [titleError, setTitleError] = useState<string | null>(null);
  const [isSavingTitle, setIsSavingTitle] = useState(false);
  const [isCreatingVersion, setIsCreatingVersion] = useState(false);
  const [isSavingVersion, setIsSavingVersion] = useState(false);
  const [isStartingProcessing, setIsStartingProcessing] = useState(false);
  const [isStartingIndexing, setIsStartingIndexing] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [isUnpublishing, setIsUnpublishing] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DocumentVersion | null>(null);
  const [isDeletingVersion, setIsDeletingVersion] = useState(false);

  useEffect(() => {
    let active = true;
    async function load(): Promise<void> {
      try {
        const [loadedDocument, loadedVersions] = await Promise.all([
          getDocument(documentId),
          listDocumentVersions(documentId),
        ]);
        const latest = loadedVersions[0]
          ? await getDocumentVersion(loadedVersions[0].id)
          : null;
        if (active) {
          setKnowledgeDocument(loadedDocument);
          setTitle(loadedDocument.title);
          setVersions(loadedVersions);
          setSelectedVersion(latest);
        }
      } catch (error) {
        if (!active) {
          return;
        }
        if (error instanceof ApiError && error.status === 401) {
          navigate("/admin/login", { replace: true });
          return;
        }
        setLoadError(detailErrorMessage(error, "load"));
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [documentId, navigate]);

  async function selectVersion(versionId: string): Promise<void> {
    setIsVersionLoading(true);
    setActionError(null);
    try {
      setSelectedVersion(await getDocumentVersion(versionId));
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setActionError(detailErrorMessage(error, "load"));
    } finally {
      setIsVersionLoading(false);
    }
  }

  async function saveTitle(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalized = title.trim();
    if (!normalized) {
      setTitleError("文档标题不能为空。");
      return;
    }
    setIsSavingTitle(true);
    setTitleError(null);
    try {
      const updated = await updateDocumentTitle(documentId, { title: normalized });
      setKnowledgeDocument(updated);
      setTitle(updated.title);
      setIsEditingTitle(false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setTitleError(
        error instanceof ApiError && error.status === 422
          ? "文档标题无效，请输入 1 到 200 个字符。"
          : detailErrorMessage(error, "save"),
      );
    } finally {
      setIsSavingTitle(false);
    }
  }

  async function finishVersionCreation(created: DocumentVersion): Promise<void> {
    setVersions((current) => [
      created,
      ...current.filter((version) => version.id !== created.id),
    ]);
    setSelectedVersion(created);
    setIsCreatingVersion(false);
    try {
      setVersions(await listDocumentVersions(documentId));
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setActionError("新版本已保存，但版本列表刷新失败，请稍后重新加载。");
    }
  }

  async function createVersionFromPaste(_title: string, content: string): Promise<void> {
    setIsSavingVersion(true);
    setActionError(null);
    try {
      const created = await createPastedVersion(documentId, { content });
      await finishVersionCreation(created);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setActionError(detailErrorMessage(error, "save"));
    } finally {
      setIsSavingVersion(false);
    }
  }

  async function createVersionFromUpload(_title: string, file: File): Promise<void> {
    setIsSavingVersion(true);
    setActionError(null);
    try {
      const created = await uploadVersion(documentId, file);
      await finishVersionCreation(created);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setActionError(detailErrorMessage(error, "save"));
    } finally {
      setIsSavingVersion(false);
    }
  }

  async function startProcessing(): Promise<void> {
    if (!selectedVersion || selectedVersion.status !== "draft") {
      return;
    }
    setIsStartingProcessing(true);
    setActionError(null);
    try {
      const created = await processDocumentVersion(selectedVersion.id);
      navigate(`/admin/jobs/${created.job_id}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setActionError(
        error instanceof ApiError && error.status === 409
          ? "该文档版本当前不能开始处理，请刷新后重试。"
          : "文档处理任务创建失败，请稍后重试。",
      );
    } finally {
      setIsStartingProcessing(false);
    }
  }

  async function startIndexing(): Promise<void> {
    if (
      !selectedVersion ||
      !["ready_for_review", "indexing_failed"].includes(selectedVersion.status)
    ) {
      return;
    }
    setIsStartingIndexing(true);
    setActionError(null);
    try {
      const created = await startKnowledgeIndexing(selectedVersion.id);
      navigate(`/admin/jobs/${created.job_id}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setActionError(
        error instanceof ApiError && error.status === 409
          ? "该版本当前不能启动知识索引，请刷新状态后重试。"
          : "知识索引任务创建失败，请稍后重试。",
      );
    } finally {
      setIsStartingIndexing(false);
    }
  }

  async function publishSelectedVersion(): Promise<void> {
    if (!selectedVersion || selectedVersion.status !== "ready_to_publish") {
      return;
    }
    setIsPublishing(true);
    setActionError(null);
    try {
      const state = await publishDocumentVersion(selectedVersion.id);
      const publishedId = state.current_published_version_id;
      setKnowledgeDocument((current) =>
        current
          ? {
              ...current,
              current_published_version_id: publishedId,
              current_published_version_number: selectedVersion.version_number,
            }
          : current,
      );
      setVersions((current) =>
        current.map((version) => ({
          ...version,
          status:
            version.id === publishedId
              ? "published"
              : version.id === knowledgeDocument?.current_published_version_id
                ? "superseded"
                : version.status,
        })),
      );
      setSelectedVersion((current) =>
        current?.id === publishedId ? { ...current, status: "published" } : current,
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setActionError(
        error instanceof ApiError && error.code === "publication_integrity_failed"
          ? "发布校验失败：启用的 Chunk 缺少当前配置对应的有效向量。"
          : "版本发布失败，请刷新后重试。",
      );
    } finally {
      setIsPublishing(false);
    }
  }

  async function takeDocumentOffline(): Promise<void> {
    if (!knowledgeDocument?.current_published_version_id) {
      return;
    }
    const currentId = knowledgeDocument.current_published_version_id;
    setIsUnpublishing(true);
    setActionError(null);
    try {
      await unpublishDocument(documentId);
      setKnowledgeDocument((current) =>
        current
          ? {
              ...current,
              current_published_version_id: null,
              current_published_version_number: null,
            }
          : current,
      );
      setVersions((current) =>
        current.map((version) =>
          version.id === currentId ? { ...version, status: "superseded" } : version,
        ),
      );
      setSelectedVersion((current) =>
        current?.id === currentId ? { ...current, status: "superseded" } : current,
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setActionError("文档下线失败，请稍后重试。");
    } finally {
      setIsUnpublishing(false);
    }
  }

  async function permanentlyDeleteSelectedVersion(): Promise<void> {
    if (!deleteTarget) {
      return;
    }
    setIsDeletingVersion(true);
    setActionError(null);
    try {
      await deleteDocumentVersion(deleteTarget.id);
      const remaining = versions.filter((version) => version.id !== deleteTarget.id);
      setVersions(remaining);
      if (selectedVersion?.id === deleteTarget.id) {
        const next = remaining[0];
        setSelectedVersion(next ? await getDocumentVersion(next.id) : null);
      }
      setDeleteTarget(null);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setActionError(
        error instanceof ApiError && error.code === "active_document_job"
          ? "该版本仍有处理或索引任务运行，当前不能删除。"
          : error instanceof ApiError && error.status === 409
            ? "该版本当前不能永久删除；当前发布版本必须先下线或切换。"
            : "版本删除失败，请刷新后重试。",
      );
      setDeleteTarget(null);
    } finally {
      setIsDeletingVersion(false);
    }
  }

  return (
    <Layout>
      {isLoading ? (
        <div className="grid min-h-72 place-items-center rounded-2xl border border-dashed border-slate-300 bg-white">
          <p className="text-sm font-medium text-slate-600">正在加载文档…</p>
        </div>
      ) : loadError ? (
        <div
          className="rounded-2xl border border-rose-200 bg-rose-50 px-6 py-10 text-center text-rose-900"
          role="alert"
        >
          <h1 className="text-xl font-semibold">无法显示知识文档</h1>
          <p className="mt-2 text-sm">{loadError}</p>
        </div>
      ) : knowledgeDocument ? (
        <>
          <section className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
            <div>
              {knowledgeDocument.document_scope === "profile" || !knowledgeDocument.project ? (
                <Link className="text-sm font-semibold text-cyan-700 hover:text-cyan-900" to="/admin/profile-documents">
                  ← 返回 Profile 资料
                </Link>
              ) : (
                <Link className="text-sm font-semibold text-cyan-700 hover:text-cyan-900" to={`/admin/projects/${knowledgeDocument.project.id}/documents`}>
                  ← 返回项目文档
                </Link>
              )}
              <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
                {knowledgeDocument.title}
              </h1>
              <p className="mt-3 text-sm text-slate-600">
                {knowledgeDocument.document_scope === "profile" || !knowledgeDocument.project
                  ? "Profile 全局资料"
                  : `所属项目：${knowledgeDocument.project.name}`}
              </p>
            </div>
            <div className="flex gap-3">
              <button
                className="rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-semibold"
                onClick={() => {
                  setTitle(knowledgeDocument.title);
                  setTitleError(null);
                  setIsEditingTitle(true);
                }}
                type="button"
              >
                修改标题
              </button>
              <button
                className="rounded-xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white"
                onClick={() => {
                  setActionError(null);
                  setIsCreatingVersion(true);
                }}
                type="button"
              >
                创建新版本
              </button>
            </div>
          </section>

          {actionError && !isCreatingVersion ? (
            <div
              className="mt-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"
              role="alert"
            >
              {actionError}
            </div>
          ) : null}

          <section className="mt-6 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white px-5 py-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">发布状态</p>
              <p className="mt-1 text-sm font-semibold">
                {knowledgeDocument.current_published_version_id
                  ? `当前发布：v${versions.find((version) => version.id === knowledgeDocument.current_published_version_id)?.version_number ?? "?"}`
                  : "当前未发布"}
              </p>
            </div>
            {knowledgeDocument.current_published_version_id ? (
              <button
                className="rounded-xl border border-rose-300 bg-white px-4 py-2.5 text-sm font-semibold text-rose-800 disabled:opacity-60"
                disabled={isUnpublishing}
                onClick={() => void takeDocumentOffline()}
                type="button"
              >
                {isUnpublishing ? "正在下线…" : "下线文档"}
              </button>
            ) : null}
          </section>

          {selectedVersion ? (
            <section className="mt-4 rounded-2xl border border-cyan-200 bg-cyan-50 px-5 py-4" aria-label="当前版本工作流">
              <p className="text-xs font-semibold uppercase tracking-wide text-cyan-800">当前版本工作流</p>
              <p className="mt-1 text-sm font-semibold text-slate-950">
                v{selectedVersion.version_number} · {documentStatusLabel(selectedVersion.status)}
              </p>
              <p className="mt-2 text-xs leading-5 text-slate-600">
                处理 → Chunk 审核 → 向量索引 → 发布。页面只会显示当前状态允许执行的下一步操作。
              </p>
            </section>
          ) : null}

          <div className="mt-8 grid gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
            <aside className="rounded-2xl border border-slate-200 bg-white p-4">
              <h2 className="px-2 text-sm font-semibold text-slate-950">
                版本历史（{versions.length}）
              </h2>
              <div className="mt-3 space-y-2">
                {versions.map((version) => (
                  <button
                    aria-label={`版本 v${version.version_number}`}
                    aria-pressed={selectedVersion?.id === version.id}
                    className={`w-full rounded-xl border p-3 text-left text-sm transition ${
                      selectedVersion?.id === version.id
                        ? "border-cyan-300 bg-cyan-50"
                        : "border-slate-200 hover:bg-slate-50"
                    }`}
                    key={version.id}
                    onClick={() => void selectVersion(version.id)}
                    type="button"
                  >
                    <span className="block font-semibold">版本 v{version.version_number}</span>
                    <span className="mt-1 block truncate text-xs text-slate-500">
                      {sourceLabel(version)} · {documentStatusLabel(version.status)} · {version.content_size_bytes} 字节
                    </span>
                  </button>
                ))}
              </div>
            </aside>

            <section className="min-w-0 rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <h2 className="font-semibold">
                  {selectedVersion ? `原始 Markdown · v${selectedVersion.version_number}` : "原始 Markdown"}
                </h2>
                <div className="flex items-center gap-3">
                  {isVersionLoading ? (
                    <span className="text-xs text-slate-500">正在加载…</span>
                  ) : null}
                  {selectedVersion?.status === "draft" ? (
                    <button
                      className="rounded-xl bg-cyan-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
                      disabled={isStartingProcessing}
                      onClick={() => void startProcessing()}
                      type="button"
                    >
                      {isStartingProcessing ? "正在创建任务…" : "开始处理"}
                    </button>
                  ) : null}
                  {selectedVersion?.status === "ready_for_review" ? (
                    <button
                      className="rounded-xl bg-cyan-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
                      disabled={isStartingIndexing}
                      onClick={() => void startIndexing()}
                      type="button"
                    >
                      {isStartingIndexing ? "正在创建任务…" : "审核后建立索引"}
                    </button>
                  ) : null}
                  {selectedVersion?.status === "indexing_failed" ? (
                    <button
                      className="rounded-xl bg-cyan-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
                      disabled={isStartingIndexing}
                      onClick={() => void startIndexing()}
                      type="button"
                    >
                      {isStartingIndexing ? "正在创建任务…" : "开始知识索引"}
                    </button>
                  ) : null}
                  {selectedVersion && ["ready_for_review", "indexing_failed", "ready_to_publish", "published", "superseded"].includes(selectedVersion.status) ? (
                    <Link
                      className="rounded-xl bg-cyan-700 px-4 py-2.5 text-sm font-semibold text-white"
                      to={`/admin/document-versions/${selectedVersion.id}/chunks`}
                    >
                      查看 Chunk
                    </Link>
                  ) : null}
                  {selectedVersion?.status === "ready_to_publish" ? (
                    <button
                      className="rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
                      disabled={isPublishing}
                      onClick={() => void publishSelectedVersion()}
                      type="button"
                    >
                      {isPublishing ? "正在发布…" : "发布此版本"}
                    </button>
                  ) : null}
                  {selectedVersion &&
                  DELETABLE_VERSION_STATUSES.has(selectedVersion.status) &&
                  selectedVersion.id !== knowledgeDocument.current_published_version_id ? (
                    <button
                      aria-label={`删除版本 v${selectedVersion.version_number}`}
                      className="rounded-xl border border-rose-300 px-4 py-2.5 text-sm font-semibold text-rose-800"
                      onClick={() => setDeleteTarget(selectedVersion)}
                      type="button"
                    >
                      删除版本
                    </button>
                  ) : null}
                </div>
              </div>
              {selectedVersion ? (
                <pre
                  className="mt-4 max-h-[38rem] overflow-auto whitespace-pre-wrap break-words rounded-xl bg-slate-950 p-5 font-mono text-sm leading-6 text-slate-100"
                  data-testid="markdown-preview"
                >
                  {selectedVersion.raw_content}
                </pre>
              ) : (
                <p className="mt-4 text-sm text-slate-500">暂无版本内容。</p>
              )}
            </section>
          </div>

          {isEditingTitle ? (
            <div
              aria-labelledby="edit-document-title-heading"
              aria-modal="true"
              className="fixed inset-0 z-40 grid place-items-center bg-slate-950/45 p-4"
              role="dialog"
            >
              <form className="w-full max-w-lg rounded-3xl bg-white p-6 shadow-2xl" onSubmit={(event) => void saveTitle(event)}>
                <h2 className="text-xl font-semibold" id="edit-document-title-heading">
                  修改文档标题
                </h2>
                <label className="mt-5 block text-sm font-medium">
                  文档标题
                  <input
                    autoFocus
                    className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3"
                    maxLength={200}
                    onChange={(event) => setTitle(event.target.value)}
                    required
                    value={title}
                  />
                </label>
                {titleError ? (
                  <div
                    className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"
                    role="alert"
                  >
                    {titleError}
                  </div>
                ) : null}
                <div className="mt-6 flex justify-end gap-3">
                  <button
                    className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold"
                    disabled={isSavingTitle}
                    onClick={() => {
                      setTitleError(null);
                      setIsEditingTitle(false);
                    }}
                    type="button"
                  >
                    取消
                  </button>
                  <button
                    className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-semibold text-white"
                    disabled={isSavingTitle}
                    type="submit"
                  >
                    {isSavingTitle ? "正在保存…" : "保存标题"}
                  </button>
                </div>
              </form>
            </div>
          ) : null}

          {isCreatingVersion ? (
            <MarkdownInputDialog
              busy={isSavingVersion}
              error={actionError}
              heading="创建新版本"
              includeTitle={false}
              onCancel={() => setIsCreatingVersion(false)}
              onPaste={createVersionFromPaste}
              onUpload={createVersionFromUpload}
              pasteSubmitLabel="保存新版本"
              uploadSubmitLabel="上传新版本"
            />
          ) : null}
          {deleteTarget ? (
            <ConfirmDialog
              busyLabel="正在删除版本…"
              confirmLabel="确认删除版本"
              description="该版本及其关联 Chunk、Embedding 和处理任务也会被永久删除，无法撤销。"
              isConfirming={isDeletingVersion}
              onCancel={() => setDeleteTarget(null)}
              onConfirm={permanentlyDeleteSelectedVersion}
              title={`永久删除版本 v${deleteTarget.version_number}？`}
            />
          ) : null}
        </>
      ) : null}
    </Layout>
  );
}
