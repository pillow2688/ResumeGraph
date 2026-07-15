import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { askInterviewQuestion } from "../api/interview";
import { getRecruiterSession, logoutRecruiter } from "../api/recruiterAccess";
import type { RecruiterSession } from "../types/accessGrant";
import type { InterviewAskResponse } from "../types/interview";

interface InterviewTurn {
  id: number;
  question: string;
  response: InterviewAskResponse;
}

function requestErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429 || error.code === "request_quota_exhausted") {
      return "当前访问授权的请求次数已用完。";
    }
    if (error.status === 403 || error.code === "project_scope_forbidden") {
      return "所选项目不在当前访问授权范围内，请重新选择。";
    }
  }
  return "AI 面试服务暂时不可用，请稍后重试。";
}

export function Interview() {
  const navigate = useNavigate();
  const [session, setSession] = useState<RecruiterSession | null>(null);
  const [selectedProjectIds, setSelectedProjectIds] = useState<string[]>([]);
  const [remainingRequests, setRemainingRequests] = useState(0);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<InterviewTurn[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let isActive = true;
    async function loadSession(): Promise<void> {
      try {
        const currentSession = await getRecruiterSession();
        if (!isActive) {
          return;
        }
        setSession(currentSession);
        setSelectedProjectIds(currentSession.allowed_projects.map((project) => project.id));
        setRemainingRequests(currentSession.remaining_requests);
      } catch (error) {
        if (!isActive) {
          return;
        }
        if (error instanceof ApiError && error.status === 401) {
          navigate("/access", { replace: true });
          return;
        }
        setErrorMessage("暂时无法加载当前访问授权，请稍后重试。");
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

  function toggleProject(projectId: string): void {
    setSelectedProjectIds((current) =>
      current.includes(projectId)
        ? current.filter((value) => value !== projectId)
        : [...current, projectId],
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedQuestion = question.trim();
    if (
      !session ||
      !normalizedQuestion ||
      selectedProjectIds.length === 0 ||
      remainingRequests <= 0 ||
      isSubmitting
    ) {
      return;
    }
    const selected = new Set(selectedProjectIds);
    const projectIds = session.allowed_projects
      .filter((project) => selected.has(project.id))
      .map((project) => project.id);

    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      const response = await askInterviewQuestion({
        question: normalizedQuestion,
        project_ids: projectIds,
      });
      setTurns((current) => [
        ...current,
        { id: current.length + 1, question: normalizedQuestion, response },
      ]);
      setRemainingRequests(response.remaining_requests);
      setQuestion("");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/access", { replace: true });
        return;
      }
      if (
        error instanceof ApiError &&
        (error.status === 429 || error.code === "request_quota_exhausted")
      ) {
        setRemainingRequests(0);
      }
      setErrorMessage(requestErrorMessage(error));
    } finally {
      setIsSubmitting(false);
    }
  }

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
    <main className="min-h-screen bg-slate-950 text-slate-950">
      <header className="border-b border-white/10 bg-slate-950 text-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-4 sm:px-8">
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-xl bg-cyan-400 text-sm font-black text-slate-950">
              RG
            </div>
            <div>
              <p className="text-sm font-semibold">ResumeGraph</p>
              <p className="text-xs text-slate-400">Single-turn RAG Interview</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Link
              className="rounded-xl border border-white/20 px-3 py-2 text-sm font-semibold hover:bg-white/10"
              to="/portfolio"
            >
              返回 Portfolio
            </Link>
            <button
              className="rounded-xl border border-white/20 px-3 py-2 text-sm font-semibold hover:bg-white/10 disabled:opacity-50"
              disabled={isLoggingOut || !session}
              onClick={() => void handleLogout()}
              type="button"
            >
              {isLoggingOut ? "正在退出…" : "退出访问"}
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-6xl gap-6 px-5 py-8 sm:px-8 lg:grid-cols-[19rem_minmax(0,1fr)] lg:py-10">
        <aside className="space-y-5">
          <section className="rounded-3xl bg-white p-6 shadow-xl">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-cyan-700">
              当前 Access Grant
            </p>
            <p className="mt-3 text-lg font-semibold">
              {session?.grant_name ?? "正在验证授权…"}
            </p>
            <p className="mt-3 inline-flex rounded-full bg-cyan-50 px-3 py-1 text-sm font-semibold text-cyan-900">
              剩余 {remainingRequests} 次
            </p>
          </section>

          <section className="rounded-3xl bg-white p-6 shadow-xl">
            <h2 className="font-semibold">授权项目</h2>
            <p className="mt-1 text-xs leading-5 text-slate-500">默认检索全部，可按问题缩小范围。</p>
            <div className="mt-4 space-y-3">
              {session?.allowed_projects.map((project) => (
                <label
                  className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 p-3 text-sm hover:border-cyan-400"
                  key={project.id}
                >
                  <input
                    checked={selectedProjectIds.includes(project.id)}
                    className="mt-0.5 size-4 accent-cyan-700"
                    disabled={isSubmitting}
                    onChange={() => toggleProject(project.id)}
                    type="checkbox"
                  />
                  <span>{project.name}</span>
                </label>
              ))}
            </div>
          </section>
        </aside>

        <section className="rounded-[2rem] bg-slate-50 p-5 shadow-2xl sm:p-8">
          <p className="text-sm font-semibold text-cyan-700">Recruiter Q&amp;A</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">AI 面试助手</h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
            这是我的 AI 面试助手，回答基于我授权发布的简历与项目资料生成，正式结论以本人面试回答为准。
          </p>

          {errorMessage ? (
            <div
              className="mt-5 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"
              role="alert"
            >
              {errorMessage}
            </div>
          ) : null}

          {isLoading ? (
            <div className="mt-7 rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-600">
              正在验证 Recruiter Session…
            </div>
          ) : (
            <>
              <form className="mt-7 rounded-2xl border border-slate-200 bg-white p-4" onSubmit={handleSubmit}>
                <label className="block text-sm font-semibold text-slate-800" htmlFor="interview-question">
                  面试问题
                </label>
                <textarea
                  className="mt-3 min-h-28 w-full resize-y rounded-xl border border-slate-300 px-4 py-3 text-sm leading-6 outline-none focus:border-cyan-700 focus:ring-4 focus:ring-cyan-100"
                  disabled={isSubmitting || remainingRequests <= 0}
                  id="interview-question"
                  maxLength={2000}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="例如：为什么你在 ResumeGraph 中使用 Redis？"
                  value={question}
                />
                <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                  <span className="text-xs text-slate-500">单次问题不会携带页面中的历史问答。</span>
                  <button
                    className="rounded-xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={
                      isSubmitting ||
                      !question.trim() ||
                      selectedProjectIds.length === 0 ||
                      remainingRequests <= 0
                    }
                    type="submit"
                  >
                    {isSubmitting ? "正在生成回答…" : "发送问题"}
                  </button>
                </div>
              </form>

              <div className="mt-6 space-y-5" aria-live="polite">
                {turns.map((turn) => (
                  <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" key={turn.id}>
                    <p className="text-xs font-bold uppercase tracking-wide text-slate-400">问题</p>
                    <h2 className="mt-2 font-semibold">{turn.question}</h2>
                    <div
                      className={
                        turn.response.status === "insufficient_evidence"
                          ? "mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4"
                          : "mt-4 rounded-xl bg-slate-950 p-4 text-white"
                      }
                    >
                      {turn.response.status === "insufficient_evidence" ? (
                        <p className="mb-2 text-xs font-bold text-amber-800">证据不足</p>
                      ) : null}
                      <p className="text-sm leading-7">{turn.response.answer}</p>
                    </div>
                    {turn.response.citations.length > 0 ? (
                      <div className="mt-4 grid gap-3 sm:grid-cols-2">
                        {turn.response.citations.map((citation) => (
                          <section
                            className="rounded-xl border border-cyan-100 bg-cyan-50 p-4"
                            key={citation.citation_handle}
                          >
                            <p className="text-xs font-bold text-cyan-800">
                              {citation.document_scope === "profile"
                                ? "候选人 Profile"
                                : citation.project_name}
                            </p>
                            <p className="mt-1 text-sm font-semibold">
                              {citation.document_title} · v{citation.version_number}
                            </p>
                            {citation.heading_path.length > 0 ? (
                              <p className="mt-2 text-xs text-slate-600">
                                {citation.heading_path.join(" / ")}
                              </p>
                            ) : null}
                          </section>
                        ))}
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
