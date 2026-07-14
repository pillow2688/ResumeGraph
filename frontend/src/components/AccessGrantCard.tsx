import type { AccessGrant } from "../types/accessGrant";

interface AccessGrantCardProps {
  grant: AccessGrant;
  onRevoke: (grant: AccessGrant) => void;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "未知";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function grantStatus(grant: AccessGrant): { label: string; className: string } {
  if (grant.revoked_at) {
    return { label: "已撤销", className: "bg-slate-100 text-slate-600" };
  }
  if (new Date(grant.expires_at).getTime() <= Date.now()) {
    return { label: "已过期", className: "bg-amber-50 text-amber-800" };
  }
  if (grant.request_count >= grant.max_requests) {
    return { label: "已用尽", className: "bg-amber-50 text-amber-800" };
  }
  return { label: "有效", className: "bg-emerald-50 text-emerald-700" };
}

export function AccessGrantCard({ grant, onRevoke }: AccessGrantCardProps) {
  const status = grantStatus(grant);

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">{grant.name}</h2>
          <p className="mt-2 text-xs text-slate-500">有效至 {formatDate(grant.expires_at)}</p>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${status.className}`}>
          {status.label}
        </span>
      </div>

      <dl className="mt-5 grid grid-cols-2 gap-3 rounded-xl bg-slate-50 p-4 text-sm">
        <div>
          <dt className="text-slate-500">请求用量</dt>
          <dd className="mt-1 font-semibold text-slate-950">
            {grant.request_count} / {grant.max_requests}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">授权项目</dt>
          <dd className="mt-1 font-semibold text-slate-950">{grant.projects.length}</dd>
        </div>
      </dl>

      <div className="mt-5">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">可访问项目</p>
        <ul className="mt-2 flex flex-wrap gap-2">
          {grant.projects.map((project) => (
            <li
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700"
              key={project.id}
            >
              {project.name}
            </li>
          ))}
        </ul>
      </div>

      {!grant.revoked_at ? (
        <div className="mt-6 border-t border-slate-100 pt-4 text-right">
          <button
            className="rounded-lg px-3 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50"
            onClick={() => onRevoke(grant)}
            type="button"
          >
            撤销授权
          </button>
        </div>
      ) : null}
    </article>
  );
}

