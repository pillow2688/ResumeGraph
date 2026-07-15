import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { listDocumentChunks } from "../api/knowledgeDocuments";
import { Layout } from "../components/Layout";
import type { DocumentChunk } from "../types/knowledgeDocument";

function chunksErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return "该文档版本不存在。";
    }
    if (error.status === 503 || error.status === 0) {
      return "Chunk 服务暂时不可用，请稍后重试。";
    }
  }
  return "Chunk 加载失败，请稍后重试。";
}

export function DocumentChunks() {
  const { versionId = "" } = useParams();
  const navigate = useNavigate();
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load(): Promise<void> {
      try {
        const loaded = await listDocumentChunks(versionId);
        if (active) {
          setChunks(loaded);
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

  return (
    <Layout>
      <section>
        <h1 className="text-3xl font-semibold tracking-tight">文档 Chunk</h1>
        <p className="mt-3 text-sm text-slate-600">只读查看，共 {chunks.length} 个 Chunk。</p>

        {isLoading ? (
          <p className="mt-8 text-sm text-slate-600">正在加载 Chunk…</p>
        ) : loadError ? (
          <div
            className="mt-8 rounded-2xl border border-rose-200 bg-rose-50 p-6 text-rose-900"
            role="alert"
          >
            {loadError}
          </div>
        ) : chunks.length === 0 ? (
          <p className="mt-8 rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-600">
            该版本尚无 Chunk。
          </p>
        ) : (
          <div className="mt-8 space-y-5">
            {chunks.map((chunk) => (
              <article
                className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
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
                  <span className="text-xs text-slate-500">
                    {chunk.character_count} 字符
                  </span>
                </div>
                <pre
                  className="mt-4 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-slate-950 p-5 font-mono text-sm leading-6 text-slate-100"
                  data-testid={`chunk-content-${chunk.chunk_index}`}
                >
                  {chunk.content}
                </pre>
              </article>
            ))}
          </div>
        )}
      </section>
    </Layout>
  );
}
