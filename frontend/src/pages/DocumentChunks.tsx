import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  getEmbeddingConfig,
  listDocumentChunks,
  updateDocumentChunk,
} from "../api/knowledgeDocuments";
import { Layout } from "../components/Layout";
import type { DocumentChunk, EmbeddingConfig } from "../types/knowledgeDocument";

function chunksErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return "该文档版本或 Chunk 不存在。";
    }
    if (error.status === 409) {
      return "当前版本状态不允许修改 Chunk，请刷新后重试。";
    }
    if (error.status === 503 || error.status === 0) {
      return "Chunk 服务暂时不可用，请稍后重试。";
    }
  }
  return "Chunk 操作失败，请稍后重试。";
}

function issueLabel(issue: Record<string, unknown>): string {
  const code = issue.code;
  return typeof code === "string" ? code : "quality_warning";
}

function metadataText(chunk: DocumentChunk, key: string): string | null {
  const value = chunk.extracted_metadata?.[key];
  if (typeof value === "string") {
    return value;
  }
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) {
    return value.join("、");
  }
  return null;
}

function isAbnormal(chunk: DocumentChunk): boolean {
  return chunk.auto_indexable === false || (chunk.quality_issues?.length ?? 0) > 0;
}

export function DocumentChunks() {
  const { versionId = "" } = useParams();
  const navigate = useNavigate();
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [embeddingConfig, setEmbeddingConfig] = useState<EmbeddingConfig | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [updatingChunkId, setUpdatingChunkId] = useState<string | null>(null);
  const [abnormalOnly, setAbnormalOnly] = useState(false);

  useEffect(() => {
    let active = true;
    async function load(): Promise<void> {
      try {
        const [loadedChunks, loadedConfig] = await Promise.all([
          listDocumentChunks(versionId),
          getEmbeddingConfig(),
        ]);
        if (active) {
          setChunks(loadedChunks);
          setEmbeddingConfig(loadedConfig);
        }
      } catch (error) {
        if (!active) {
          return;
        }
        if (error instanceof ApiError && error.status === 401) {
          navigate("/admin/login", { replace: true });
          return;
        }
        setLoadError(chunksErrorMessage(error));
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
  }, [navigate, versionId]);

  const visibleChunks = useMemo(
    () => (abnormalOnly ? chunks.filter(isAbnormal) : chunks),
    [abnormalOnly, chunks],
  );

  async function toggleChunk(chunk: DocumentChunk): Promise<void> {
    setUpdatingChunkId(chunk.id);
    setActionError(null);
    try {
      const updated = await updateDocumentChunk(chunk.id, { enabled: !chunk.enabled });
      setChunks((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setActionError(chunksErrorMessage(error));
    } finally {
      setUpdatingChunkId(null);
    }
  }

  return (
    <Layout>
      <section>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">文档 Chunk</h1>
            <p className="mt-3 text-sm text-slate-600">
              共 {chunks.length} 个 Chunk，其中 {chunks.filter(isAbnormal).length} 个有警告。
            </p>
          </div>
          <button
            aria-pressed={abnormalOnly}
            className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold"
            onClick={() => setAbnormalOnly((current) => !current)}
            type="button"
          >
            {abnormalOnly ? "查看全部 Chunk" : "只看异常 Chunk"}
          </button>
        </div>

        {embeddingConfig ? (
          <div className="mt-5 rounded-2xl border border-cyan-200 bg-cyan-50 px-5 py-4 text-sm text-cyan-950">
            <p className="font-semibold">
              {embeddingConfig.provider_name} · {embeddingConfig.model} · {embeddingConfig.dimensions} 维
            </p>
            <p className="mt-1 text-xs text-cyan-800">
              批大小 {embeddingConfig.batch_size} · 超时 {embeddingConfig.timeout_seconds} 秒 ·
              最多重试 {embeddingConfig.max_retries} 次
            </p>
          </div>
        ) : null}

        {actionError ? (
          <div className="mt-5 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900" role="alert">
            {actionError}
          </div>
        ) : null}

        {isLoading ? (
          <p className="mt-8 text-sm text-slate-600">正在加载 Chunk…</p>
        ) : loadError ? (
          <div className="mt-8 rounded-2xl border border-rose-200 bg-rose-50 p-6 text-rose-900" role="alert">
            {loadError}
          </div>
        ) : visibleChunks.length === 0 ? (
          <p className="mt-8 rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-600">
            {abnormalOnly ? "没有异常 Chunk。" : "该版本尚无 Chunk。"}
          </p>
        ) : (
          <div className="mt-8 space-y-5">
            {visibleChunks.map((chunk) => {
              const issues = chunk.quality_issues ?? [];
              const knowledgeType = metadataText(chunk, "knowledge_type");
              const topics = metadataText(chunk, "topics");
              const technologies = metadataText(chunk, "technologies");
              return (
                <article
                  className={`rounded-2xl border bg-white p-5 shadow-sm sm:p-6 ${
                    isAbnormal(chunk) ? "border-amber-300" : "border-slate-200"
                  }`}
                  key={chunk.id}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h2 className="font-semibold">Chunk {chunk.chunk_index}</h2>
                      <p className="mt-1 text-sm text-slate-500">
                        {chunk.heading_path.length > 0
                          ? chunk.heading_path.join(" / ")
                          : "无标题路径"}
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-slate-500">{chunk.character_count} 字符</span>
                      <button
                        aria-label={`${chunk.enabled ? "禁用" : "启用"} Chunk ${chunk.chunk_index}`}
                        className={`rounded-lg px-3 py-2 text-xs font-semibold text-white ${
                          chunk.enabled ? "bg-slate-700" : "bg-cyan-700"
                        }`}
                        disabled={updatingChunkId === chunk.id}
                        onClick={() => void toggleChunk(chunk)}
                        type="button"
                      >
                        {chunk.enabled ? "已启用" : "已禁用"}
                      </button>
                    </div>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2 text-xs">
                    <span className="rounded-full bg-slate-100 px-3 py-1.5">
                      自动建议：{chunk.auto_indexable == null ? "未检查" : chunk.auto_indexable ? "可索引" : "不索引"}
                    </span>
                    {issues.map((issue, index) => (
                      <span className="rounded-full bg-amber-100 px-3 py-1.5 text-amber-900" key={`${issueLabel(issue)}-${index}`}>
                        {issueLabel(issue)}
                      </span>
                    ))}
                    {knowledgeType ? <span className="rounded-full bg-cyan-100 px-3 py-1.5 text-cyan-900">{knowledgeType}</span> : null}
                  </div>
                  {chunk.quality_reason ? <p className="mt-3 text-sm text-slate-700">{chunk.quality_reason}</p> : null}
                  {topics || technologies ? (
                    <p className="mt-2 text-xs text-slate-500">
                      {topics ? `主题：${topics}` : ""}{topics && technologies ? " · " : ""}{technologies ? `技术：${technologies}` : ""}
                    </p>
                  ) : null}
                  <pre
                    className="mt-4 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-slate-950 p-5 font-mono text-sm leading-6 text-slate-100"
                    data-testid={`chunk-content-${chunk.chunk_index}`}
                  >
                    {chunk.content}
                  </pre>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </Layout>
  );
}
