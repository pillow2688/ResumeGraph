import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  createAccessGrant,
  listAccessGrants,
  revokeAccessGrant,
} from "../api/accessGrants";
import { ApiError } from "../api/client";
import { listProjects } from "../api/projects";
import { AccessGrantCard } from "../components/AccessGrantCard";
import { AccessGrantForm } from "../components/AccessGrantForm";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Layout } from "../components/Layout";
import { OneTimeTokenDialog } from "../components/OneTimeTokenDialog";
import type { AccessGrant, AccessGrantCreateRequest } from "../types/accessGrant";
import type { Project } from "../types/project";

function grantErrorMessage(error: unknown, action: "load" | "create" | "revoke"): string {
  if (error instanceof ApiError) {
    if (error.status === 422) {
      return "授权信息或项目选择有误，请检查后重试。";
    }
    if (error.status === 409) {
      return "当前授权状态已变化，请刷新后重试。";
    }
    if (error.status === 503 || error.status === 0) {
      return "授权服务暂时不可用，请稍后重试。";
    }
  }
  const labels = { load: "加载访问授权", create: "创建访问授权", revoke: "撤销访问授权" };
  return `${labels[action]}失败，请稍后重试。`;
}

export function AccessGrants() {
  const navigate = useNavigate();
  const [grants, setGrants] = useState<AccessGrant[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [grantToRevoke, setGrantToRevoke] = useState<AccessGrant | null>(null);
  const [isRevoking, setIsRevoking] = useState(false);
  const [oneTimeToken, setOneTimeToken] = useState<string | null>(null);

  useEffect(() => {
    let isActive = true;
    async function loadData(): Promise<void> {
      try {
        const [loadedGrants, loadedProjects] = await Promise.all([
          listAccessGrants(),
          listProjects(),
        ]);
        if (isActive) {
          setGrants(loadedGrants);
          setProjects(loadedProjects);
        }
      } catch (error) {
        if (!isActive) {
          return;
        }
        if (error instanceof ApiError && error.status === 401) {
          navigate("/admin/login", { replace: true });
          return;
        }
        setLoadError(grantErrorMessage(error, "load"));
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }
    void loadData();
    return () => {
      isActive = false;
    };
  }, [navigate]);

  async function handleCreate(payload: AccessGrantCreateRequest): Promise<void> {
    setIsSaving(true);
    setActionError(null);
    setNotice(null);
    try {
      const result = await createAccessGrant(payload);
      setGrants((current) => [result.grant, ...current]);
      setIsFormOpen(false);
      setOneTimeToken(result.access_token);
      setNotice("访问授权已创建");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setActionError(grantErrorMessage(error, "create"));
    } finally {
      setIsSaving(false);
    }
  }

  async function handleRevoke(): Promise<void> {
    if (!grantToRevoke) {
      return;
    }
    setIsRevoking(true);
    setActionError(null);
    setNotice(null);
    try {
      const revoked = await revokeAccessGrant(grantToRevoke.id);
      setGrants((current) =>
        current.map((grant) => (grant.id === revoked.id ? revoked : grant)),
      );
      setGrantToRevoke(null);
      setNotice("授权已撤销");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setActionError(grantErrorMessage(error, "revoke"));
      setGrantToRevoke(null);
    } finally {
      setIsRevoking(false);
    }
  }

  return (
    <Layout>
      <section className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-cyan-700">管理员工作台</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">访问授权</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
            为面试官创建有期限、有请求上限且限定项目范围的访问码。
          </p>
        </div>
        <button
          className="rounded-xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          disabled={isLoading || projects.length === 0}
          onClick={() => setIsFormOpen(true)}
          type="button"
        >
          创建访问授权
        </button>
      </section>

      {!isLoading && !loadError && projects.length === 0 ? (
        <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900" role="status">
          请先创建至少一个项目
        </div>
      ) : null}
      {notice ? (
        <div className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800" role="status">
          {notice}
        </div>
      ) : null}
      {actionError ? (
        <div className="mt-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800" role="alert">
          {actionError}
        </div>
      ) : null}

      <section aria-busy={isLoading} aria-label="访问授权列表" className="mt-8">
        {isLoading ? (
          <div className="grid min-h-64 place-items-center rounded-2xl border border-dashed border-slate-300 bg-white">
            <p className="text-sm font-medium text-slate-600">正在加载访问授权…</p>
          </div>
        ) : loadError ? (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-6 py-10 text-center" role="alert">
            <h2 className="font-semibold text-rose-950">暂时无法显示访问授权</h2>
            <p className="mt-2 text-sm text-rose-800">{loadError}</p>
          </div>
        ) : grants.length === 0 ? (
          <div className="grid min-h-72 place-items-center rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center">
            <div>
              <h2 className="text-xl font-semibold">还没有访问授权</h2>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                创建授权后，访问码只会显示一次。
              </p>
            </div>
          </div>
        ) : (
          <div className="grid gap-5 lg:grid-cols-2">
            {grants.map((grant) => (
              <AccessGrantCard grant={grant} key={grant.id} onRevoke={setGrantToRevoke} />
            ))}
          </div>
        )}
      </section>

      {isFormOpen ? (
        <AccessGrantForm
          isSaving={isSaving}
          onCancel={() => setIsFormOpen(false)}
          onSubmit={handleCreate}
          projects={projects}
        />
      ) : null}
      {grantToRevoke ? (
        <ConfirmDialog
          busyLabel="正在撤销…"
          confirmLabel="确认撤销"
          description={`撤销“${grantToRevoke.name}”后，已建立的面试官会话也会立即失效。`}
          isConfirming={isRevoking}
          onCancel={() => setGrantToRevoke(null)}
          onConfirm={handleRevoke}
          title="确认撤销访问授权？"
        />
      ) : null}
      {oneTimeToken ? (
        <OneTimeTokenDialog
          accessToken={oneTimeToken}
          onClose={() => setOneTimeToken(null)}
        />
      ) : null}
    </Layout>
  );
}
