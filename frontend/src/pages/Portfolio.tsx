import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { getRecruiterSession, logoutRecruiter } from "../api/recruiterAccess";
import type { RecruiterSession } from "../types/accessGrant";

function formatExpiry(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "未知";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(date);
}

export function Portfolio() {
  const navigate = useNavigate();
  const [session, setSession] = useState<RecruiterSession | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let isActive = true;
    async function loadSession(): Promise<void> {
      try {
        const currentSession = await getRecruiterSession();
        if (isActive) {
          setSession(currentSession);
        }
      } catch (error) {
        if (!isActive) {
          return;
        }
        if (error instanceof ApiError && error.status === 401) {
          navigate("/access", { replace: true });
          return;
        }
        setErrorMessage("暂时无法加载授权项目，请稍后重试。");
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }
    void loadSession();
    return () => {
      isActive = false;
    };
  }, [navigate]);

  async function handleLogout(): Promise<void> {
    setIsLoggingOut(true);
    setErrorMessage(null);
    try {
      await logoutRecruiter();
      navigate("/access", { replace: true });
    } catch {
      setErrorMessage("暂时无法退出访问，请稍后重试。");
    } finally {
      setIsLoggingOut(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-xl bg-slate-950 text-sm font-bold text-white">RG</div>
            <div>
              <p className="text-sm font-semibold">ResumeGraph Portfolio</p>
              <p className="text-xs text-slate-500">Authorized Portfolio</p>
            </div>
          </div>
          <button
            className="rounded-xl border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            disabled={isLoggingOut || !session}
            onClick={() => void handleLogout()}
            type="button"
          >
            {isLoggingOut ? "正在退出…" : "退出访问"}
          </button>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-5 py-10 sm:px-8 sm:py-14">
        {errorMessage ? (
          <div className="mb-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800" role="alert">
            {errorMessage}
          </div>
        ) : null}
        {isLoading ? (
          <div className="grid min-h-64 place-items-center rounded-2xl border border-dashed border-slate-300 bg-white">
            <p className="text-sm text-slate-600">正在验证访问授权…</p>
          </div>
        ) : session ? (
          <>
            <section className="rounded-3xl bg-slate-950 p-7 text-white shadow-xl sm:p-10">
              <p className="text-sm font-semibold text-cyan-300">当前访问授权</p>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">{session.grant_name}</h1>
              <dl className="mt-7 grid gap-4 sm:grid-cols-2">
                <div className="rounded-2xl bg-white/10 p-4">
                  <dt className="text-xs uppercase tracking-wide text-slate-400">有效期至</dt>
                  <dd className="mt-2 text-lg font-semibold">{formatExpiry(session.expires_at)}</dd>
                </div>
                <div className="rounded-2xl bg-white/10 p-4">
                  <dt className="text-xs uppercase tracking-wide text-slate-400">剩余请求次数</dt>
                  <dd className="mt-2 text-lg font-semibold">{session.remaining_requests}</dd>
                </div>
              </dl>
            </section>

            <section className="mt-8">
              <p className="text-sm font-semibold text-cyan-700">授权范围</p>
              <h2 className="mt-2 text-2xl font-semibold tracking-tight">可查看项目</h2>
              {session.allowed_projects.length === 0 ? (
                <div className="mt-5 rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-600">
                  当前授权没有可查看的项目。
                </div>
              ) : (
                <div className="mt-5 grid gap-4 sm:grid-cols-2">
                  {session.allowed_projects.map((project) => (
                    <article className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm" key={project.id}>
                      <div className="grid size-11 place-items-center rounded-xl bg-cyan-50 text-lg font-semibold text-cyan-800">
                        {project.name.slice(0, 1).toUpperCase()}
                      </div>
                      <h3 className="mt-4 text-xl font-semibold">{project.name}</h3>
                    </article>
                  ))}
                </div>
              )}
            </section>
          </>
        ) : null}
      </div>
    </main>
  );
}
