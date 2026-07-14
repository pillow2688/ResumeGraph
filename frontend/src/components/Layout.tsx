import { useState, type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { logoutAdmin } from "../api/auth";

interface LayoutProps {
  children: ReactNode;
}

const navigation = [
  { label: "项目", to: "/admin/projects" },
  { label: "访问授权", to: "/admin/access-grants" },
];

export function Layout({ children }: LayoutProps) {
  const navigate = useNavigate();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  async function handleLogout(): Promise<void> {
    setIsLoggingOut(true);
    setLogoutError(null);
    try {
      await logoutAdmin();
      navigate("/admin/login", { replace: true });
    } catch {
      setLogoutError("暂时无法退出登录，请稍后重试。");
    } finally {
      setIsLoggingOut(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950">
      <header className="border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <div className="flex items-center gap-3">
            <div
              aria-hidden="true"
              className="grid size-10 place-items-center rounded-xl bg-slate-950 text-sm font-bold text-white shadow-sm"
            >
              RG
            </div>
            <div>
              <p className="text-sm font-semibold tracking-tight">ResumeGraph</p>
              <p className="text-xs text-slate-500">Admin Console</p>
            </div>
          </div>
          <nav
            aria-label="管理员导航"
            className="flex items-center gap-1 rounded-xl bg-slate-100 p-1"
          >
            {navigation.map((item) => (
              <NavLink
                className={({ isActive }) =>
                  `rounded-lg px-3 py-2 text-sm font-semibold transition ${
                    isActive
                      ? "bg-white text-slate-950 shadow-sm"
                      : "text-slate-600 hover:text-slate-950"
                  }`
                }
                key={item.to}
                to={item.to}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <button
            className="rounded-xl border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            disabled={isLoggingOut}
            onClick={() => void handleLogout()}
            type="button"
          >
            {isLoggingOut ? "正在退出…" : "退出登录"}
          </button>
        </div>
      </header>
      {logoutError ? (
        <div className="mx-auto mt-5 max-w-6xl px-5 sm:px-8">
          <div
            className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"
            role="alert"
          >
            {logoutError}
          </div>
        </div>
      ) : null}
      <main className="mx-auto max-w-6xl px-5 py-8 sm:px-8 sm:py-12">{children}</main>
    </div>
  );
}

