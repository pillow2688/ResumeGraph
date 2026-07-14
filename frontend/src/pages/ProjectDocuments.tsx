import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  createPastedDocument,
  listProjectDocuments,
  uploadDocument,
} from "../api/knowledgeDocuments";
import { getProject } from "../api/projects";
import { Layout } from "../components/Layout";
import { MarkdownInputDialog } from "../components/MarkdownInputDialog";
import type { KnowledgeDocumentSummary } from "../types/knowledgeDocument";
import type { Project } from "../types/project";

function documentErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404 && error.code === "project_not_found") {
      return "该项目不存在或已被删除。";
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
  return "知识文档请求失败，请稍后重试。";
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "更新时间未知";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function ProjectDocuments() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load(): Promise<void> {
      try {
        const [loadedProject, loadedDocuments] = await Promise.all([
          getProject(projectId),
          listProjectDocuments(projectId),
        ]);
        if (active) {
          setProject(loadedProject);
          setDocuments(loadedDocuments);
        }
      } catch (error) {
        if (!active) {
          return;
        }
        if (error instanceof ApiError && error.status === 401) {
          navigate("/admin/login", { replace: true });
          return;
        }
        setLoadError(documentErrorMessage(error));
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
  }, [navigate, projectId]);

  async function createFromPaste(title: string, content: string): Promise<void> {
    setIsSaving(true);
    setFormError(null);
    try {
      const created = await createPastedDocument(projectId, { title, content });
      setDocuments((current) => [created, ...current]);
      navigate(`/admin/documents/${created.id}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setFormError(documentErrorMessage(error));
    } finally {
      setIsSaving(false);
    }
  }

  async function createFromUpload(title: string, file: File): Promise<void> {
    setIsSaving(true);
    setFormError(null);
    try {
      const created = await uploadDocument(projectId, title, file);
      setDocuments((current) => [created, ...current]);
      navigate(`/admin/documents/${created.id}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setFormError(documentErrorMessage(error));
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Layout>
      <section className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <Link className="text-sm font-semibold text-cyan-700 hover:text-cyan-900" to="/admin/projects">
            ← 返回项目列表
          </Link>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
            {project ? `${project.name} 知识文档` : "项目知识文档"}
          </h1>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            接收并保存 Markdown 草稿；处理、审核与发布不在当前阶段。
          </p>
        </div>
        <button
          className="rounded-xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50"
          disabled={isLoading || Boolean(loadError)}
          onClick={() => {
            setFormError(null);
            setIsCreating(true);
          }}
          type="button"
        >
          创建知识文档
        </button>
      </section>

      <section aria-busy={isLoading} aria-label="知识文档列表" className="mt-8">
        {isLoading ? (
          <div className="grid min-h-64 place-items-center rounded-2xl border border-dashed border-slate-300 bg-white">
            <p className="text-sm font-medium text-slate-600">正在加载知识文档…</p>
          </div>
        ) : loadError ? (
          <div
            className="rounded-2xl border border-rose-200 bg-rose-50 px-6 py-10 text-center text-rose-900"
            role="alert"
          >
            <h2 className="font-semibold">无法显示知识文档</h2>
            <p className="mt-2 text-sm">{loadError}</p>
          </div>
        ) : documents.length === 0 ? (
          <div className="grid min-h-72 place-items-center rounded-2xl border border-dashed border-slate-300 bg-white px-6 text-center">
            <div>
              <h2 className="text-xl font-semibold">还没有知识文档</h2>
              <p className="mt-2 text-sm text-slate-600">粘贴 Markdown 或上传 UTF-8 编码的 .md 文件。</p>
            </div>
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {documents.map((item) => (
              <article className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm" key={item.id}>
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <Link
                      className="text-xl font-semibold text-slate-950 hover:text-cyan-800"
                      to={`/admin/documents/${item.id}`}
                    >
                      {item.title}
                    </Link>
                    <p className="mt-2 text-sm text-slate-600">
                      {item.version_count} 个版本
                      {item.latest_version ? ` · 最新 v${item.latest_version.version_number}` : ""}
                    </p>
                  </div>
                  <span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800">
                    {item.latest_version?.status ?? "暂无版本"}
                  </span>
                </div>
                <p className="mt-5 border-t border-slate-100 pt-4 text-xs text-slate-500">
                  更新于 {formatDate(item.updated_at)}
                </p>
              </article>
            ))}
          </div>
        )}
      </section>

      {isCreating ? (
        <MarkdownInputDialog
          busy={isSaving}
          error={formError}
          heading="创建知识文档"
          includeTitle
          onCancel={() => setIsCreating(false)}
          onPaste={createFromPaste}
          onUpload={createFromUpload}
          pasteSubmitLabel="保存文档"
          uploadSubmitLabel="上传并保存"
        />
      ) : null}
    </Layout>
  );
}
