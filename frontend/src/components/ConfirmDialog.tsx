interface ConfirmDialogProps {
  busyLabel: string;
  confirmLabel: string;
  description: string;
  isConfirming: boolean;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
  title: string;
}

export function ConfirmDialog({
  busyLabel,
  confirmLabel,
  description,
  isConfirming,
  onCancel,
  onConfirm,
  title,
}: ConfirmDialogProps) {
  return (
    <div
      aria-labelledby="confirm-dialog-title"
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4 backdrop-blur-sm"
      role="alertdialog"
    >
      <div className="w-full max-w-md rounded-3xl bg-white p-6 shadow-2xl sm:p-8">
        <div className="grid size-12 place-items-center rounded-full bg-rose-50 text-2xl text-rose-700">
          !
        </div>
        <h2 className="mt-5 text-xl font-semibold tracking-tight" id="confirm-dialog-title">
          {title}
        </h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
        <div className="mt-7 flex justify-end gap-3">
          <button
            className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            disabled={isConfirming}
            onClick={onCancel}
            type="button"
          >
            取消
          </button>
          <button
            className="rounded-xl bg-rose-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-rose-800 disabled:opacity-60"
            disabled={isConfirming}
            onClick={() => void onConfirm()}
            type="button"
          >
            {isConfirming ? busyLabel : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

