import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { listAccessGrants } from "../api/accessGrants";
import { ApiError } from "../api/client";
import {
  getAdminPublicDemoConfig,
  updateAdminPublicDemoConfig,
} from "../api/publicDemo";
import { AdminCard } from "../components/AdminCard";
import { Layout } from "../components/Layout";
import type { AccessGrant } from "../types/accessGrant";

function grantState(grant: AccessGrant): { available: boolean; label: string } {
  if (grant.revoked_at) return { available: false, label: "Revoked" };
  if (new Date(grant.expires_at).getTime() <= Date.now()) {
    return { available: false, label: "Expired" };
  }
  if (grant.request_count >= grant.max_requests) {
    return { available: false, label: "Quota exhausted" };
  }
  if (grant.projects.length === 0) return { available: false, label: "No projects" };
  return { available: true, label: "Available" };
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未知";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function PublicDemoSetting() {
  const navigate = useNavigate();
  const [grants, setGrants] = useState<AccessGrant[]>([]);
  const [candidateName, setCandidateName] = useState("马腾飞");
  const [grantId, setGrantId] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selectedGrant = useMemo(
    () => grants.find((grant) => grant.id === grantId) ?? null,
    [grantId, grants],
  );
  const selectedGrantState = selectedGrant ? grantState(selectedGrant) : null;

  useEffect(() => {
    let active = true;
    async function load(): Promise<void> {
      try {
        const [config, loadedGrants] = await Promise.all([
          getAdminPublicDemoConfig(),
          listAccessGrants(),
        ]);
        if (!active) return;
        setGrants(loadedGrants);
        if (config.configured) {
          setCandidateName(config.candidate_name ?? "马腾飞");
          setGrantId(config.default_access_grant_id ?? "");
          setEnabled(config.enabled);
        } else {
          const firstAvailable = loadedGrants.find((grant) => grantState(grant).available);
          setGrantId(firstAvailable?.id ?? loadedGrants[0]?.id ?? "");
        }
      } catch (error) {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          navigate("/admin/login", { replace: true });
          return;
        }
        setErrorMessage("暂时无法加载 Public Demo 配置，请稍后重试。");
      } finally {
        if (active) setIsLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [navigate]);

  async function save(): Promise<void> {
    if (!candidateName.trim() || !grantId || isSaving) return;
    setIsSaving(true);
    setErrorMessage(null);
    setNotice(null);
    try {
      const saved = await updateAdminPublicDemoConfig({
        candidate_name: candidateName.trim(),
        default_access_grant_id: grantId,
        enabled,
      });
      setCandidateName(saved.candidate_name ?? candidateName.trim());
      setGrantId(saved.default_access_grant_id ?? grantId);
      setEnabled(saved.enabled);
      setNotice("Public Demo 配置已保存");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      if (error instanceof ApiError && error.status === 422) {
        setErrorMessage("当前 Grant 无法用于公开访问，请检查状态、有效期和额度。");
      } else {
        setErrorMessage("暂时无法保存 Public Demo 配置，请稍后重试。");
      }
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Layout>
      <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-neutral-500">Public Experience</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-[-0.04em] text-neutral-950">Public Demo</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-neutral-500">
            选择公开首页使用的现有 Access Grant。知识范围仍由 Grant 和发布状态共同决定。
          </p>
        </div>
        <span className={`w-fit rounded-full px-3 py-1.5 text-xs font-semibold ${enabled ? "bg-neutral-950 text-white" : "bg-neutral-200 text-neutral-600"}`}>
          {enabled ? "Enabled" : "Disabled"}
        </span>
      </div>

      {notice ? <p className="mt-6 rounded-2xl bg-neutral-900 px-4 py-3 text-sm text-white" role="status">{notice}</p> : null}
      {errorMessage ? <p className="mt-6 rounded-2xl border border-neutral-200 bg-white px-4 py-3 text-sm text-neutral-700" role="alert">{errorMessage}</p> : null}

      {isLoading ? (
        <div className="mt-8 grid min-h-64 place-items-center rounded-3xl border border-dashed border-neutral-300 bg-white text-sm text-neutral-500">
          正在加载公开配置…
        </div>
      ) : (
        <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(20rem,0.95fr)]">
          <AdminCard title="公开入口" description="候选人名称只用于公开展示；授权范围来自所选 Grant。">
            <div className="space-y-5">
              <label className="block text-sm font-medium text-neutral-700">
                公开候选人
                <input
                  className="mt-2 w-full rounded-2xl border border-neutral-200 bg-neutral-50 px-4 py-3 text-neutral-950 outline-none transition focus:border-neutral-500 focus:bg-white focus:ring-4 focus:ring-neutral-100"
                  maxLength={200}
                  onChange={(event) => setCandidateName(event.target.value)}
                  value={candidateName}
                />
              </label>
              <label className="block text-sm font-medium text-neutral-700">
                默认公开 Grant
                <select
                  className="mt-2 w-full rounded-2xl border border-neutral-200 bg-neutral-50 px-4 py-3 text-neutral-950 outline-none transition focus:border-neutral-500 focus:bg-white focus:ring-4 focus:ring-neutral-100"
                  onChange={(event) => setGrantId(event.target.value)}
                  value={grantId}
                >
                  <option value="">请选择 Access Grant</option>
                  {grants.map((grant) => (
                    <option key={grant.id} value={grant.id}>
                      {grant.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-5 rounded-2xl border border-neutral-200 bg-neutral-50 p-4 text-sm font-medium text-neutral-800">
                <span>
                  启用 Public Demo
                  <span className="mt-1 block text-xs font-normal text-neutral-500">关闭后首页保留，但不能创建 Interview Session。</span>
                </span>
                <input
                  aria-label="启用 Public Demo"
                  checked={enabled}
                  className="size-5 accent-neutral-950"
                  onChange={(event) => setEnabled(event.target.checked)}
                  type="checkbox"
                />
              </label>
              {enabled && selectedGrantState && !selectedGrantState.available ? (
                <p className="rounded-2xl bg-neutral-100 px-4 py-3 text-xs leading-5 text-neutral-600">
                  当前 Grant 状态为 {selectedGrantState.label}，无法启用公开访问。
                </p>
              ) : null}
              <button
                className="w-full rounded-2xl bg-neutral-950 px-5 py-3.5 text-sm font-semibold text-white transition hover:bg-neutral-800 disabled:bg-neutral-300"
                disabled={isSaving || !candidateName.trim() || !grantId}
                onClick={() => void save()}
                type="button"
              >
                {isSaving ? "正在保存…" : "保存公开配置"}
              </button>
            </div>
          </AdminCard>

          <div className="space-y-6">
            <AdminCard title="当前绑定 Grant">
              {selectedGrant ? (
                <div>
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-lg font-semibold text-neutral-950">{selectedGrant.name}</p>
                      <p className="mt-1 text-xs text-neutral-500">有效至 {formatDate(selectedGrant.expires_at)}</p>
                    </div>
                    <span className="rounded-full bg-neutral-100 px-2.5 py-1 text-xs font-semibold text-neutral-600">
                      {selectedGrantState?.label}
                    </span>
                  </div>
                  <dl className="mt-5 grid grid-cols-2 gap-3">
                    <div className="rounded-2xl bg-neutral-50 p-4">
                      <dt className="text-xs text-neutral-500">剩余请求</dt>
                      <dd className="mt-1 text-lg font-semibold">{selectedGrant.max_requests - selectedGrant.request_count}</dd>
                    </div>
                    <div className="rounded-2xl bg-neutral-50 p-4">
                      <dt className="text-xs text-neutral-500">授权项目</dt>
                      <dd className="mt-1 text-lg font-semibold">{selectedGrant.projects.length}</dd>
                    </div>
                  </dl>
                </div>
              ) : (
                <p className="text-sm text-neutral-500">尚未选择 Access Grant。</p>
              )}
            </AdminCard>

            <AdminCard title="当前公开范围" description="Profile 与 Technical 仍要求资料已发布；Project 额外受 Grant 范围限制。">
              <ul className="space-y-2 text-sm">
                <li className="rounded-2xl bg-neutral-50 px-4 py-3 font-medium text-neutral-700">Profile 公开资料</li>
                <li className="rounded-2xl bg-neutral-50 px-4 py-3 font-medium text-neutral-700">Technical 公开资料</li>
                {selectedGrant?.projects.map((project) => (
                  <li className="rounded-2xl border border-neutral-200 px-4 py-3 font-medium text-neutral-700" key={project.id}>{project.name}</li>
                ))}
              </ul>
            </AdminCard>
          </div>
        </div>
      )}
    </Layout>
  );
}
