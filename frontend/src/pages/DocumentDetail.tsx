import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  createPastedVersion,
  getDocument,
  getDocumentVersion,
  listDocumentVersions,
  processDocumentVersion,
  updateDocumentTitle,
  uploadVersion,
} from "../api/knowledgeDocuments";
import { Layout } from "../components/Layout";
import { MarkdownInputDialog } from "../components/MarkdownInputDialog";
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
              <Link
                className="text-sm font-semibold text-cyan-700 hover:text-cyan-900"
                to={`/admin/projects/${knowledgeDocument.project.id}/documents`}
              >
                ← 返回项目文档
              </Link>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
                {knowledgeDocument.title}
              </h1>
              <p className="mt-3 text-sm text-slate-600">
                所属项目：{knowledgeDocument.project.name}
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
                      {sourceLabel(version)} · {version.status} · {version.content_size_bytes} 字节
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
                    <Link
                      className="rounded-xl bg-cyan-700 px-4 py-2.5 text-sm font-semibold text-white"
                      to={`/admin/document-versions/${selectedVersion.id}/chunks`}
                    >
                      查看 Chunk
                    </Link>
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
        </>
      ) : null}
    </Layout>
  );
}
