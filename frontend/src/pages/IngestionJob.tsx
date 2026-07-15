import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { getIngestionJob } from "../api/knowledgeDocuments";
import { Layout } from "../components/Layout";
import type {
  IngestionJob as IngestionJobRecord,
  IngestionJobStage,
} from "../types/knowledgeDocument";

const stageLabels: Record<IngestionJobStage, string> = {
  reading: "读取",
  cleaning: "清洗",
  chunking: "切分",
  rule_check: "规则检查",
  llm_quality_check: "DeepSeek 判断",
  embedding: "向量生成",
  saving: "保存",
};

function jobErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return "该文档处理任务不存在。";
    }
    if (error.status === 503 || error.status === 0) {
      return "文档处理服务暂时不可用，请稍后重试。";
    }
  }
  return "任务状态加载失败，请稍后重试。";
}

export function IngestionJob() {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<IngestionJobRecord | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;

    async function load(): Promise<void> {
      try {
        const loaded = await getIngestionJob(jobId);
        if (!active) {
          return;
        }
        setJob(loaded);
        setLoadError(null);
        if (loaded.status === "pending" || loaded.status === "processing") {
          timer = window.setTimeout(() => void load(), 1_000);
        }
      } catch (error) {
        if (!active) {
          return;
        }
        if (error instanceof ApiError && error.status === 401) {
          navigate("/admin/login", { replace: true });
          return;
        }
        setLoadError(jobErrorMessage(error));
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    }

    void load();
    return () => {
      active = false;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [jobId, navigate, refreshKey]);

  return (
    <Layout>
      <section className="mx-auto max-w-3xl">
        <Link className="text-sm font-semibold text-cyan-700" to="/admin/projects">
          ← 返回项目
        </Link>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">
          {job?.job_type === "knowledge_indexing" ? "知识索引任务" : "文档处理任务"}
        </h1>

        {isLoading ? (
          <p className="mt-8 text-sm text-slate-600">正在加载任务状态…</p>
        ) : loadError ? (
          <div
            className="mt-8 rounded-2xl border border-rose-200 bg-rose-50 p-6 text-rose-900"
            role="alert"
          >
            <p>{loadError}</p>
            <button
              className="mt-4 rounded-xl border border-rose-300 bg-white px-4 py-2 text-sm font-semibold"
              onClick={() => {
                setLoadError(null);
                setIsLoading(true);
                setRefreshKey((current) => current + 1);
              }}
              type="button"
            >
              重试
            </button>
          </div>
        ) : job ? (
          <div className="mt-8 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
            <p className="text-sm text-slate-500">文档</p>
            <p className="mt-1 text-lg font-semibold">
              {job.document_title} · v{job.version_number}
            </p>

            <dl className="mt-7 grid gap-5 sm:grid-cols-3">
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  状态
                </dt>
                <dd className="mt-2 font-mono text-sm font-semibold">{job.status}</dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  当前阶段
                </dt>
                <dd className="mt-2 text-sm font-semibold">{stageLabels[job.stage]}</dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  进度
                </dt>
                <dd className="mt-2 text-sm font-semibold">{job.progress}%</dd>
              </div>
            </dl>

            <div
              aria-label={`处理进度 ${job.progress}%`}
              className="mt-6 h-2 overflow-hidden rounded-full bg-slate-200"
              role="progressbar"
              aria-valuemax={100}
              aria-valuemin={0}
              aria-valuenow={job.progress}
            >
              <div
                className="h-full rounded-full bg-cyan-600 transition-all"
                style={{ width: `${job.progress}%` }}
              />
            </div>

            {job.status === "failed" ? (
              <div
                className="mt-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900"
                role="alert"
              >
                {job.error_message ?? "文档处理失败，请重新创建任务。"}
              </div>
            ) : null}

            {job.status === "completed" ? (
              <Link
                className="mt-6 inline-flex rounded-xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white"
                to={`/admin/document-versions/${job.document_version_id}/chunks`}
              >
                查看 Chunk
              </Link>
            ) : null}
          </div>
        ) : null}
      </section>
    </Layout>
  );
}
