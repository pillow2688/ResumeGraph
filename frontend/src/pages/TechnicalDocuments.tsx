import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  createPastedTechnicalDocument,
  listTechnicalDocuments,
  uploadTechnicalDocument,
} from "../api/knowledgeDocuments";
import { Layout } from "../components/Layout";
import { MarkdownInputDialog } from "../components/MarkdownInputDialog";
import {
  documentActionLabel,
  documentStatusLabel,
} from "../components/DocumentWorkflowStatus";
import type { KnowledgeDocumentSummary } from "../types/knowledgeDocument";

function technicalErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 413 || error.code === "markdown_too_large") {
      return "Markdown 内容不能超过 1 MiB。";
    }
    if (error.status === 415 || error.code === "unsupported_markdown_file") {
      return "只支持 UTF-8 编码的 .md 文件。";
    }
    if (error.status === 422) {
      return "Technical 资料标题、身份或 Markdown 内容无效。";
    }
  }
  return "Technical 资料服务暂时不可用，请稍后重试。";
}

export function TechnicalDocuments() {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load(): Promise<void> {
      try {
        const loaded = await listTechnicalDocuments();
        if (active) setDocuments(loaded);
      } catch (loadError) {
        if (!active) return;
        if (loadError instanceof ApiError && loadError.status === 401) {
          navigate("/admin/login", { replace: true });
          return;
        }
        setError(technicalErrorMessage(loadError));
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
    setError(null);
    try {
      const created = await createPastedTechnicalDocument({
        title,
        content,
        knowledge_status: "general_knowledge",
      });
      navigate(`/admin/documents/${created.id}`);
    } catch (createError) {
      setError(technicalErrorMessage(createError));
    } finally {
      setIsSaving(false);
    }
  }

  async function createFromUpload(title: string, file: File): Promise<void> {
    setIsSaving(true);
    setError(null);
    try {
      const created = await uploadTechnicalDocument(title, file);
      navigate(`/admin/documents/${created.id}`);
    } catch (createError) {
      setError(technicalErrorMessage(createError));
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Layout>
      <section className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-cyan-800">面试技术知识外挂</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
            Technical 技术资料
          </h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
            保存 Redis、RAG、Embedding、LangGraph 等通用技术原理。Technical
            资料不绑定项目，也不能证明项目已经实现某项机制；发布仍经过现有处理、Chunk
            审核、索引与发布流程。
          </p>
        </div>
        <button
          className="rounded-xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white"
          onClick={() => setIsCreating(true)}
          type="button"
        >
          新增 Technical 资料
        </button>
      </section>

      {error ? (
        <div
          className="mt-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900"
          role="alert"
        >
          {error}
        </div>
      ) : null}

      <section aria-busy={isLoading} aria-label="Technical 资料列表" className="mt-8">
        {isLoading ? (
          <p className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-600">
            正在加载 Technical 资料…
          </p>
        ) : documents.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center">
            <h2 className="text-xl font-semibold">还没有 Technical 资料</h2>
            <p className="mt-2 text-sm text-slate-600">
              管理员可上传经过核对的通用技术原理 Markdown。
            </p>
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {documents.map((document) => (
              <article
                className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
                key={document.id}
              >
                <span className="rounded-full bg-violet-50 px-2.5 py-1 text-xs font-semibold text-violet-800">
                  通用技术原理
                </span>
                <Link
                  className="mt-4 block text-xl font-semibold hover:text-cyan-800"
                  to={`/admin/documents/${document.id}`}
                >
                  {document.title}
                </Link>
                <p className="mt-2 text-sm text-slate-600">
                  {document.version_count} 个版本 · {documentStatusLabel(document.latest_version?.status)}
                </p>
                <Link
                  className="mt-5 inline-flex rounded-xl bg-slate-950 px-3 py-2 text-sm font-semibold text-white"
                  to={`/admin/documents/${document.id}`}
                >
                  {documentActionLabel(document.latest_version?.status)}
                </Link>
              </article>
            ))}
          </div>
        )}
      </section>

      {isCreating ? (
        <MarkdownInputDialog
          busy={isSaving}
          classificationHelp="Technical 资料只能用于解释通用原理，项目是否落地必须由 Project 已实现资料证明。"
          classificationOptions={[
            { value: "general_knowledge", label: "Technical 通用技术原理" },
          ]}
          error={error}
          heading="新增 Technical 资料"
          includeTitle
          onCancel={() => setIsCreating(false)}
          onPaste={createFromPaste}
          onUpload={createFromUpload}
          pasteSubmitLabel="保存 Technical 资料"
          uploadSubmitLabel="上传 Technical 资料"
        />
      ) : null}
    </Layout>
  );
}
