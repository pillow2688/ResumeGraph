import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  createPublicDemoSession,
  getPublicDemoStatus,
} from "../api/publicDemo";
import type { PublicDemoStatus } from "../types/publicDemo";

const questionTopics = [
  "我的项目经历",
  "ResumeGraph 如何实现",
  "RAG 系统设计",
  "Agent 架构",
  "技术方向",
];

const technologyLabels = ["LangGraph", "RAG", "pgvector", "Multi-Agent"];

export function LandingPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<PublicDemoStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isStarting, setIsStarting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load(): Promise<void> {
      try {
        const loaded = await getPublicDemoStatus();
        if (active) setStatus(loaded);
      } catch {
        if (active) setErrorMessage("AI Interview 暂时无法加载，请稍后再试。");
      } finally {
        if (active) setIsLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, []);

  async function startInterview(): Promise<void> {
    if (!status?.available || isStarting) return;
    setIsStarting(true);
    setErrorMessage(null);
    try {
      const session = await createPublicDemoSession();
      navigate(session.redirect_url);
    } catch {
      setErrorMessage("AI Interview 尚未开放，请稍后再试。");
      setIsStarting(false);
    }
  }

  return (
    <main className="min-h-screen bg-white text-neutral-950">
      <header className="border-b border-black/5 bg-white/90 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4 sm:px-8">
          <Link className="flex items-center gap-3" to="/" aria-label="ResumeGraph 首页">
            <span className="grid size-9 place-items-center rounded-xl bg-neutral-950 text-xs font-semibold text-white">
              RG
            </span>
            <span>
              <span className="block text-sm font-semibold tracking-tight">ResumeGraph</span>
              <span className="block text-[11px] text-neutral-500">AI Interview Assistant</span>
            </span>
          </Link>
          <Link
            className="rounded-full px-3 py-2 text-xs font-medium text-neutral-500 transition hover:bg-neutral-100 hover:text-neutral-950"
            to="/admin"
          >
            Admin
          </Link>
        </div>
      </header>

      <section className="mx-auto flex min-h-[calc(100vh-70px)] max-w-6xl flex-col justify-center px-5 py-20 sm:px-8 sm:py-28">
        <div className="mx-auto max-w-4xl text-center">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-neutral-500">
            AI Interview Assistant
          </p>
          <h1 className="mt-6 text-5xl font-semibold tracking-[-0.055em] text-balance sm:text-7xl lg:text-8xl">
            ResumeGraph AI Interview
          </h1>
          <div className="mx-auto mt-7 max-w-2xl text-base leading-8 text-neutral-600 sm:text-lg">
            {status?.available ? (
              <>
                <p className="font-medium text-neutral-900">你好，我是{status.candidate_name}。</p>
                <p>这是我的 AI 面试助手。你可以从公开资料出发，了解我的经历、项目与技术思考。</p>
              </>
            ) : (
              <p>基于 LangGraph + RAG 的智能面试助手。</p>
            )}
          </div>

          <div className="mt-9 flex flex-col items-center gap-3">
            <button
              className="inline-flex min-w-44 items-center justify-center rounded-full bg-neutral-950 px-7 py-3.5 text-sm font-semibold text-white shadow-[0_8px_24px_rgba(0,0,0,0.12)] transition hover:bg-neutral-800 disabled:cursor-default disabled:bg-neutral-300 disabled:shadow-none"
              disabled={isLoading || !status?.available || isStarting}
              onClick={() => void startInterview()}
              type="button"
            >
              {isStarting ? "Preparing Interview…" : "Start Interview"}
            </button>
            {isLoading ? <p className="text-xs text-neutral-400">正在检查公开访问…</p> : null}
            {!isLoading && status && !status.available ? (
              <p className="text-sm text-neutral-500" role="status">{status.message}</p>
            ) : null}
            {errorMessage ? (
              <p className="text-sm text-neutral-600" role="alert">{errorMessage}</p>
            ) : null}
          </div>
        </div>

        <div className="mx-auto mt-20 grid w-full max-w-5xl gap-5 lg:grid-cols-[1.35fr_0.65fr]">
          <section className="rounded-3xl border border-black/5 bg-neutral-50 p-7 sm:p-10">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-neutral-500">You can ask</p>
            <ul className="mt-6 grid gap-3 sm:grid-cols-2">
              {questionTopics.map((topic) => (
                <li className="rounded-2xl border border-black/5 bg-white px-5 py-4 text-sm font-medium text-neutral-700" key={topic}>
                  {topic}
                </li>
              ))}
            </ul>
          </section>
          <section className="rounded-3xl border border-black/5 bg-neutral-950 p-7 text-white sm:p-10">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-neutral-400">Built with</p>
            <div className="mt-6 flex flex-wrap gap-2">
              {technologyLabels.map((label) => (
                <span className="rounded-full border border-white/15 px-3 py-2 text-xs text-neutral-200" key={label}>
                  {label}
                </span>
              ))}
            </div>
            <p className="mt-8 text-sm leading-6 text-neutral-400">
              回答基于已发布资料与受控引用，不替代候选人本人面试。
            </p>
          </section>
        </div>
      </section>
    </main>
  );
}
