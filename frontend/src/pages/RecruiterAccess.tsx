import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { exchangeAccessToken } from "../api/recruiterAccess";

function accessErrorMessage(error: unknown): string {
  if (error instanceof ApiError && (error.status === 503 || error.status === 0)) {
    return "访问服务暂时不可用，请稍后重试。";
  }
  return "访问码无效或已失效。";
}

export function RecruiterAccess() {
  const navigate = useNavigate();
  const [accessToken, setAccessToken] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedToken = accessToken.trim();
    if (!normalizedToken) {
      return;
    }
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      await exchangeAccessToken({ access_token: normalizedToken });
      setAccessToken("");
      navigate("/portfolio", { replace: true });
    } catch (error) {
      setErrorMessage(accessErrorMessage(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="relative grid min-h-screen place-items-center overflow-hidden bg-slate-950 px-5 py-12">
      <div
        aria-hidden="true"
        className="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(6,182,212,0.28),transparent_42%)]"
      />
      <section className="relative w-full max-w-lg rounded-[2rem] border border-white/10 bg-white p-7 shadow-2xl sm:p-12">
        <div className="grid size-12 place-items-center rounded-2xl bg-slate-950 font-bold text-white">RG</div>
        <p className="mt-8 text-sm font-semibold text-cyan-700">面试官访问入口</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">查看授权项目</h1>
        <p className="mt-3 text-sm leading-6 text-slate-600">
          输入管理员提供的一次性访问码。验证成功后，会话由安全 Cookie 管理。
        </p>

        {errorMessage ? (
          <div className="mt-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800" role="alert">
            {errorMessage}
          </div>
        ) : null}

        <form className="mt-8 space-y-5" onSubmit={handleSubmit}>
          <label className="block text-sm font-medium text-slate-800">
            访问码
            <input
              autoComplete="off"
              autoFocus
              className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 outline-none focus:border-cyan-700 focus:ring-4 focus:ring-cyan-100"
              onChange={(event) => setAccessToken(event.target.value)}
              required
              type="password"
              value={accessToken}
            />
          </label>
          <button
            className="w-full rounded-xl bg-slate-950 px-5 py-3.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
            disabled={isSubmitting || !accessToken.trim()}
            type="submit"
          >
            {isSubmitting ? "正在验证…" : "查看授权项目"}
          </button>
        </form>
      </section>
    </main>
  );
}

