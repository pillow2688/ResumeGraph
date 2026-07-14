import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { loginAdmin } from "../api/auth";
import { ApiError } from "../api/client";

function getLoginErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return "用户名或密码不正确，请重新输入。";
    }
    if (error.status === 429) {
      return "登录尝试过于频繁，请稍后再试。";
    }
    if (error.status === 422) {
      return "登录信息格式有误，请检查后重试。";
    }
    if (error.status === 503) {
      return "登录服务暂时不可用，请稍后重试。";
    }
    if (error.status === 0) {
      return "无法连接服务器，请检查网络后重试。";
    }
  }

  return "暂时无法登录，请稍后重试。";
}

function readRouteMessage(state: unknown): string | null {
  if (
    typeof state === "object" &&
    state !== null &&
    "message" in state &&
    typeof state.message === "string"
  ) {
    return state.message;
  }
  return null;
}

export function AdminLogin() {
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(
    readRouteMessage(location.state),
  );
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setErrorMessage(null);
    setIsSubmitting(true);

    try {
      await loginAdmin({ username: username.trim(), password });
      navigate("/admin/projects", { replace: true });
    } catch (error) {
      setErrorMessage(getLoginErrorMessage(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="relative grid min-h-screen place-items-center overflow-hidden bg-slate-950 px-5 py-12 text-slate-950">
      <div
        aria-hidden="true"
        className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(8,145,178,0.34),transparent_38%),radial-gradient(circle_at_bottom_right,rgba(14,116,144,0.22),transparent_38%)]"
      />
      <div className="relative grid w-full max-w-5xl overflow-hidden rounded-[2rem] border border-white/10 bg-white shadow-2xl lg:grid-cols-[1.05fr_0.95fr]">
        <section className="hidden bg-slate-900 p-12 text-white lg:flex lg:flex-col lg:justify-between">
          <div>
            <div className="grid size-12 place-items-center rounded-2xl bg-cyan-400 font-bold text-slate-950">
              RG
            </div>
            <h1 className="mt-10 max-w-sm text-4xl font-semibold leading-tight tracking-tight">
              Manage the facts behind your portfolio.
            </h1>
            <p className="mt-5 max-w-md text-base leading-7 text-slate-300">
              维护经过授权、可审查的项目资料，为后续知识发布与招聘者问答奠定基础。
            </p>
          </div>
          <p className="text-xs uppercase tracking-[0.22em] text-slate-500">
            ResumeGraph · Administrator
          </p>
        </section>

        <section className="p-7 sm:p-12 lg:p-14">
          <div className="lg:hidden">
            <div className="grid size-11 place-items-center rounded-xl bg-slate-950 text-sm font-bold text-white">
              RG
            </div>
          </div>
          <p className="mt-8 text-sm font-semibold text-cyan-700 lg:mt-0">管理员入口</p>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">
            登录 ResumeGraph
          </h2>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            使用独立的管理员凭据进入项目管理后台。
          </p>

          {errorMessage ? (
            <div
              className="mt-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"
              role="alert"
            >
              {errorMessage}
            </div>
          ) : null}

          <form className="mt-8 space-y-5" onSubmit={handleSubmit}>
            <label className="block text-sm font-medium text-slate-800">
              用户名
              <input
                autoComplete="username"
                autoFocus
                className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 outline-none transition placeholder:text-slate-400 focus:border-cyan-700 focus:ring-4 focus:ring-cyan-100"
                onChange={(event) => setUsername(event.target.value)}
                required
                value={username}
              />
            </label>
            <label className="block text-sm font-medium text-slate-800">
              密码
              <input
                autoComplete="current-password"
                className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 outline-none transition placeholder:text-slate-400 focus:border-cyan-700 focus:ring-4 focus:ring-cyan-100"
                onChange={(event) => setPassword(event.target.value)}
                required
                type="password"
                value={password}
              />
            </label>
            <button
              className="w-full rounded-xl bg-slate-950 px-5 py-3.5 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-950 disabled:cursor-not-allowed disabled:opacity-60"
              disabled={isSubmitting}
              type="submit"
            >
              {isSubmitting ? "正在登录…" : "登录管理后台"}
            </button>
          </form>

          <p className="mt-6 text-xs leading-5 text-slate-500">
            会话由后端 HttpOnly Cookie 管理；本页面不会读取或保存 Session Token。
          </p>
        </section>
      </div>
    </main>
  );
}
