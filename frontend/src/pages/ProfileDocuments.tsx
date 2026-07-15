import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  createPastedProfileDocument,
  listProfileDocuments,
  permanentlyDeleteDocument,
  unpublishDocument,
  uploadProfileDocument,
} from "../api/knowledgeDocuments";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Layout } from "../components/Layout";
import { MarkdownInputDialog } from "../components/MarkdownInputDialog";
import {
  documentActionLabel,
  documentStatusLabel,
} from "../components/DocumentWorkflowStatus";
import type { KnowledgeDocumentSummary } from "../types/knowledgeDocument";

function profileErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409 && error.code === "active_document_job") {
      return "文档仍有处理或索引任务运行，当前不能删除。";
    }
    if (error.status === 409 && error.code === "document_confirmation_mismatch") {
      return "确认标题不匹配，未执行永久删除。";
    }
    if (error.status === 413 || error.code === "markdown_too_large") {
      return "Markdown 内容不能超过 1 MiB。";
    }
    if (error.status === 415 || error.code === "unsupported_markdown_file") {
      return "只支持 .md 文件。";
    }
    if (error.status === 422) {
      return "Profile 资料标题或 Markdown 内容无效。";
    }
    if (error.status === 503 || error.status === 0) {
      return "Profile 资料服务暂时不可用，请稍后重试。";
    }
  }
  return "Profile 资料操作失败，请稍后重试。";
}

interface PermanentDeleteDialogProps {
  document: KnowledgeDocumentSummary;
  isDeleting: boolean;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
  confirmation: string;
  setConfirmation: (value: string) => void;
}

function PermanentDeleteDialog({
  document,
  isDeleting,
  onCancel,
  onConfirm,
  confirmation,
  setConfirmation,
}: PermanentDeleteDialogProps) {
  const matches = confirmation === document.title;
  return (
    <div
      aria-labelledby="permanent-delete-title"
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-center bg-slate-950/55 p-4 backdrop-blur-sm"
      role="alertdialog"
    >
      <div className="w-full max-w-lg rounded-3xl bg-white p-6 shadow-2xl sm:p-8">
        <div className="grid size-12 place-items-center rounded-full bg-rose-100 text-xl font-bold text-rose-800">!</div>
        <h2 className="mt-5 text-xl font-semibold" id="permanent-delete-title">
          永久删除全部资料？
        </h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          此操作会级联删除全部 Version、Chunk、Embedding 和处理任务，无法撤销。
        </p>
        <label className="mt-5 block text-sm font-medium text-slate-800">
          输入文档标题以确认
          <input
            autoFocus
            className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3"
            disabled={isDeleting}
            onChange={(event) => setConfirmation(event.target.value)}
            placeholder={document.title}
            value={confirmation}
          />
        </label>
        <div className="mt-7 flex justify-end gap-3">
          <button className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold" disabled={isDeleting} onClick={onCancel} type="button">
            取消
          </button>
          <button className="rounded-xl bg-rose-800 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50" disabled={isDeleting || !matches} onClick={() => void onConfirm()} type="button">
            {isDeleting ? "正在永久删除…" : "永久删除全部数据"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function ProfileDocuments() {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [offlineTarget, setOfflineTarget] = useState<KnowledgeDocumentSummary | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeDocumentSummary | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [isMutating, setIsMutating] = useState(false);

  useEffect(() => {
    let active = true;
    async function load(): Promise<void> {
      try {
        const loaded = await listProfileDocuments();
        if (active) setDocuments(loaded);
      } catch (error) {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          navigate("/admin/login", { replace: true });
          return;
        }
        setActionError(profileErrorMessage(error));
      } finally {
        if (active) setIsLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [navigate]);

  async function createFromPaste(title: string, content: string): Promise<void> {
    setIsSaving(true);
    setActionError(null);
    try {
      const created = await createPastedProfileDocument({ title, content });
      navigate(`/admin/documents/${created.id}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setActionError(profileErrorMessage(error));
    } finally {
      setIsSaving(false);
    }
  }

  async function createFromUpload(title: string, file: File): Promise<void> {
    setIsSaving(true);
    setActionError(null);
    try {
      const created = await uploadProfileDocument(title, file);
      navigate(`/admin/documents/${created.id}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setActionError(profileErrorMessage(error));
    } finally {
      setIsSaving(false);
    }
  }

  async function takeOffline(): Promise<void> {
    if (!offlineTarget) return;
    setIsMutating(true);
    setActionError(null);
    try {
      await unpublishDocument(offlineTarget.id);
      setDocuments((current) =>
        current.map((item) =>
          item.id === offlineTarget.id
            ? { ...item, current_published_version_id: null, current_published_version_number: null }
            : item,
        ),
      );
      setOfflineTarget(null);
    } catch (error) {
      setActionError(profileErrorMessage(error));
    } finally {
      setIsMutating(false);
    }
  }

  async function permanentlyDelete(): Promise<void> {
    if (!deleteTarget || confirmation !== deleteTarget.title) return;
    setIsMutating(true);
    setActionError(null);
    try {
      await permanentlyDeleteDocument(deleteTarget.id, confirmation);
      setDocuments((current) => current.filter((item) => item.id !== deleteTarget.id));
      setDeleteTarget(null);
      setConfirmation("");
    } catch (error) {
      setActionError(profileErrorMessage(error));
    } finally {
      setIsMutating(false);
    }
  }

  return (
    <Layout>
      <section className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-cyan-800">候选人全局知识范围</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Profile 全局资料</h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
            管理简历、教育背景、技能与获奖资料。发布后，所有有效面试官授权默认可检索这些全局资料；项目资料仍按 Access Grant 过滤。
          </p>
        </div>
        <button className="rounded-xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white" onClick={() => setIsCreating(true)} type="button">
          新增 Profile 资料
        </button>
      </section>

      {actionError ? <div className="mt-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900" role="alert">{actionError}</div> : null}

      <section aria-busy={isLoading} aria-label="Profile 资料列表" className="mt-8">
        {isLoading ? (
          <p className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-600">正在加载 Profile 资料…</p>
        ) : documents.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center">
            <h2 className="text-xl font-semibold">还没有 Profile 资料</h2>
            <p className="mt-2 text-sm text-slate-600">可粘贴 Markdown 或上传 UTF-8 编码的 .md 文件。</p>
          </div>
        ) : (
          <div className="space-y-5">
            {documents.map((item) => (
              <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6" key={item.id}>
                <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <Link className="text-xl font-semibold text-slate-950 hover:text-cyan-800" to={`/admin/documents/${item.id}`}>
                      {item.title}
                    </Link>
                    <p className="mt-2 text-sm text-slate-600">
                      {item.version_count} 个版本 · {item.current_published_version_id
                        ? `当前发布 v${item.current_published_version_number ?? "?"}`
                        : "当前未发布"}
                    </p>
                    <span className="mt-3 inline-flex rounded-full bg-cyan-50 px-2.5 py-1 text-xs font-semibold text-cyan-800">
                      {documentStatusLabel(item.latest_version?.status)}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Link className="rounded-xl bg-slate-950 px-3 py-2 text-sm font-semibold text-white" to={`/admin/documents/${item.id}`}>{documentActionLabel(item.latest_version?.status)}</Link>
                    {item.current_published_version_id ? (
                      <button aria-label={`下线 ${item.title}`} className="rounded-xl border border-amber-300 px-3 py-2 text-sm font-semibold text-amber-900" onClick={() => setOfflineTarget(item)} type="button">下线</button>
                    ) : null}
                    <button aria-label={`永久删除 ${item.title}`} className="rounded-xl border border-rose-300 px-3 py-2 text-sm font-semibold text-rose-800" onClick={() => { setConfirmation(""); setDeleteTarget(item); }} type="button">永久删除</button>
                  </div>
                </div>
                <dl className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-5">
                  {[
                    ["Chunk 总数", item.current_chunk_count ?? 0],
                    ["Enabled", item.current_enabled_chunk_count ?? 0],
                    ["精确重复", item.current_exact_duplicate_count ?? 0],
                    ["Hard Block", item.current_hard_block_count ?? 0],
                    ["Embedding", item.current_embedding_count ?? 0],
                  ].map(([label, value]) => (
                    <div className="rounded-xl bg-slate-50 px-4 py-3" key={label}>
                      <dt className="text-xs font-medium text-slate-500">{label}</dt>
                      <dd className="mt-1 text-lg font-semibold text-slate-950">{value}</dd>
                    </div>
                  ))}
                </dl>
              </article>
            ))}
          </div>
        )}
      </section>

      {isCreating ? <MarkdownInputDialog busy={isSaving} error={actionError} heading="新增 Profile 资料" includeTitle onCancel={() => setIsCreating(false)} onPaste={createFromPaste} onUpload={createFromUpload} pasteSubmitLabel="保存 Profile 资料" uploadSubmitLabel="上传 Profile 资料" /> : null}
      {offlineTarget ? <ConfirmDialog busyLabel="正在下线…" confirmLabel="确认下线" description="下线只会清空当前发布指针，保留全部版本、Chunk、Embedding 和任务记录。" isConfirming={isMutating} onCancel={() => setOfflineTarget(null)} onConfirm={takeOffline} title={`下线“${offlineTarget.title}”？`} /> : null}
      {deleteTarget ? <PermanentDeleteDialog confirmation={confirmation} document={deleteTarget} isDeleting={isMutating} onCancel={() => { setDeleteTarget(null); setConfirmation(""); }} onConfirm={permanentlyDelete} setConfirmation={setConfirmation} /> : null}
    </Layout>
  );
}
