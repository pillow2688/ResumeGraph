import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { createAdminUser, deleteAdminUser, listAdminUsers } from "../api/adminUsers";
import { getCurrentAdmin } from "../api/auth";
import { ApiError } from "../api/client";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Layout } from "../components/Layout";
import type { Admin } from "../types/auth";

function safeError(error: unknown, action: "load" | "create" | "delete"): string {
  if (error instanceof ApiError) {
    if (error.code === "admin_username_exists") {
      return "用户名已存在，请使用其他用户名。";
    }
    if (error.code === "cannot_delete_current_admin") {
      return "不能删除当前登录账号。";
    }
    if (error.code === "cannot_delete_last_admin") {
      return "系统必须至少保留一个管理员。";
    }
    if (error.status === 422) {
      return "用户名或密码不符合要求，请检查后重试。";
    }
    if (error.status === 503 || error.status === 0) {
      return "管理员服务暂时不可用，请稍后重试。";
    }
  }
  const label = { load: "加载管理员", create: "新增管理员", delete: "删除管理员" };
  return `${label[action]}失败，请稍后重试。`;
}

export function AdminUsers() {
  const navigate = useNavigate();
  const [currentAdmin, setCurrentAdmin] = useState<Admin | null>(null);
  const [admins, setAdmins] = useState<Admin[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [adminToDelete, setAdminToDelete] = useState<Admin | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load(): Promise<void> {
      try {
        const [me, loadedAdmins] = await Promise.all([getCurrentAdmin(), listAdminUsers()]);
        if (active) {
          setCurrentAdmin(me);
          setAdmins(loadedAdmins);
        }
      } catch (loadError) {
        if (!active) return;
        if (loadError instanceof ApiError && loadError.status === 401) {
          navigate("/admin/login", { replace: true });
          return;
        }
        setError(safeError(loadError, "load"));
      } finally {
        if (active) setIsLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [navigate]);

  async function handleCreate(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setIsSaving(true);
    setError(null);
    setNotice(null);
    try {
      const created = await createAdminUser({ username, password });
      setAdmins((current) => [...current, created].sort((a, b) => a.username.localeCompare(b.username)));
      setUsername("");
      setPassword("");
      setIsFormOpen(false);
      setNotice("管理员已新增。请通过安全渠道单独告知其初始密码。");
    } catch (createError) {
      if (createError instanceof ApiError && createError.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setError(safeError(createError, "create"));
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDelete(): Promise<void> {
    if (!adminToDelete) return;
    setIsDeleting(true);
    setError(null);
    setNotice(null);
    try {
      await deleteAdminUser(adminToDelete.id);
      setAdmins((current) => current.filter((admin) => admin.id !== adminToDelete.id));
      setNotice(`管理员“${adminToDelete.username}”已删除，其旧会话将立即失效。`);
      setAdminToDelete(null);
    } catch (deleteError) {
      if (deleteError instanceof ApiError && deleteError.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setError(safeError(deleteError, "delete"));
      setAdminToDelete(null);
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <Layout>
      <section className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-cyan-700">管理员工作台</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">管理员账号</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
            新增或删除后台管理员。当前账号不能删除自己，系统也不会允许删除最后一个管理员。
          </p>
        </div>
        <button
          className="rounded-xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50"
          disabled={isLoading}
          onClick={() => setIsFormOpen(true)}
          type="button"
        >
          新增管理员
        </button>
      </section>

      {notice ? <div className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800" role="status">{notice}</div> : null}
      {error ? <div className="mt-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800" role="alert">{error}</div> : null}

      <section aria-busy={isLoading} className="mt-8 grid gap-4" aria-label="管理员列表">
        {isLoading ? <p className="rounded-2xl border bg-white px-6 py-10 text-center text-sm text-slate-600">正在加载管理员…</p> : admins.map((admin) => {
          const isCurrent = admin.id === currentAdmin?.id;
          return (
            <article className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm" data-testid={`admin-${admin.id}`} key={admin.id}>
              <div>
                <p className="font-semibold text-slate-950">{admin.username}</p>
                {isCurrent ? <p className="mt-1 text-xs font-medium text-cyan-700">当前登录账号</p> : null}
              </div>
              <button
                className="rounded-xl border border-rose-200 px-3 py-2 text-sm font-semibold text-rose-700 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={isCurrent}
                onClick={() => setAdminToDelete(admin)}
                type="button"
              >
                删除
              </button>
            </article>
          );
        })}
      </section>

      {isFormOpen ? (
        <div className="fixed inset-0 z-40 grid place-items-center bg-slate-950/50 p-4" role="presentation">
          <form aria-label="新增管理员" className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl" onSubmit={(event) => void handleCreate(event)}>
            <h2 className="text-xl font-semibold">新增管理员</h2>
            <label className="mt-5 block text-sm font-semibold" htmlFor="admin-username">用户名</label>
            <input autoComplete="off" className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2" id="admin-username" maxLength={100} onChange={(event) => setUsername(event.target.value)} required value={username} />
            <label className="mt-4 block text-sm font-semibold" htmlFor="admin-password">初始密码</label>
            <input autoComplete="new-password" className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2" id="admin-password" maxLength={128} minLength={12} onChange={(event) => setPassword(event.target.value)} required type="password" value={password} />
            <p className="mt-2 text-xs text-slate-500">密码长度 12–128 个字符，提交后不会在页面保存或再次显示。</p>
            <div className="mt-6 flex justify-end gap-3">
              <button className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold" disabled={isSaving} onClick={() => { setIsFormOpen(false); setPassword(""); }} type="button">取消</button>
              <button className="rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={isSaving} type="submit">{isSaving ? "正在新增…" : "确认新增"}</button>
            </div>
          </form>
        </div>
      ) : null}

      {adminToDelete ? (
        <ConfirmDialog
          busyLabel="正在删除…"
          confirmLabel="确认删除"
          description={`删除“${adminToDelete.username}”后，该账号的旧登录会话将立即失效。`}
          isConfirming={isDeleting}
          onCancel={() => setAdminToDelete(null)}
          onConfirm={handleDelete}
          title="确认删除管理员？"
        />
      ) : null}
    </Layout>
  );
}
