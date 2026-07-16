import { useState, type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { logoutAdmin } from "../api/auth";

interface LayoutProps {
  children: ReactNode;
}

const navigation = [
  { label: "项目", to: "/admin/projects" },
  { label: "Profile 资料", to: "/admin/profile-documents" },
  { label: "Technical 资料", to: "/admin/technical-documents" },
  { label: "访问授权", to: "/admin/access-grants" },
  { label: "Public Demo", to: "/admin/public-demo" },
  { label: "管理员", to: "/admin/users" },
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
    <div className="min-h-screen bg-neutral-50 text-neutral-950">
      <header className="sticky top-0 z-30 border-b border-black/5 bg-white/90 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <div className="flex items-center gap-3">
            <div
              aria-hidden="true"
              className="grid size-10 place-items-center rounded-2xl bg-neutral-950 text-sm font-bold text-white"
            >
              RG
            </div>
            <div>
              <p className="text-sm font-semibold tracking-tight">ResumeGraph</p>
              <p className="text-xs text-neutral-500">Admin Console</p>
            </div>
          </div>
          <nav
            aria-label="管理员导航"
            className="flex max-w-full items-center gap-1 overflow-x-auto rounded-2xl bg-neutral-100 p-1"
          >
            {navigation.map((item) => (
              <NavLink
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-xl px-3 py-2 text-sm font-semibold transition ${
                    isActive
                      ? "bg-white text-neutral-950 shadow-sm"
                      : "text-neutral-600 hover:text-neutral-950"
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
            className="rounded-xl border border-neutral-300 px-3 py-2 text-sm font-semibold text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
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
      <main className="mx-auto max-w-6xl px-5 py-10 sm:px-8 sm:py-14">{children}</main>
    </div>
  );
}
