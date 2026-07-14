import { useState } from "react";

interface OneTimeTokenDialogProps {
  accessToken: string;
  onClose: () => void;
}

export function OneTimeTokenDialog({
  accessToken,
  onClose,
}: OneTimeTokenDialogProps) {
  const [copyStatus, setCopyStatus] = useState<string | null>(null);

  async function copyToken(): Promise<void> {
    try {
      await navigator.clipboard.writeText(accessToken);
      setCopyStatus("访问码已复制。");
    } catch {
      setCopyStatus("复制失败，请手动保存访问码。");
    }
  }

  return (
    <div
      aria-labelledby="token-dialog-title"
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-center bg-slate-950/55 p-4 backdrop-blur-sm"
      role="alertdialog"
    >
      <div className="w-full max-w-xl rounded-3xl bg-white p-6 shadow-2xl sm:p-8">
        <div className="grid size-12 place-items-center rounded-full bg-amber-100 text-xl text-amber-800">
          !
        </div>
        <h2 className="mt-5 text-2xl font-semibold tracking-tight" id="token-dialog-title">
          访问码只显示一次，请立即保存。
        </h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          关闭后无法再次查看；如访问码遗失，请撤销该授权并重新创建。
        </p>
        <code className="mt-5 block break-all rounded-xl border border-slate-200 bg-slate-950 p-4 text-sm leading-6 text-cyan-200">
          {accessToken}
        </code>
        {copyStatus ? (
          <p className="mt-3 text-sm text-slate-600" role="status">
            {copyStatus}
          </p>
        ) : null}
        <div className="mt-7 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <button
            className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            onClick={() => void copyToken()}
            type="button"
          >
            复制访问码
          </button>
          <button
            className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-semibold text-white hover:bg-slate-800"
            onClick={onClose}
            type="button"
          >
            我已保存，关闭
          </button>
        </div>
      </div>
    </div>
  );
}

