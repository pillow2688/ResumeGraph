import { useState, type ChangeEvent, type FormEvent } from "react";

import type { KnowledgeStatus } from "../types/knowledgeDocument";

export const MARKDOWN_MAX_BYTES = 1024 * 1024;

type InputMode = "paste" | "upload";

interface MarkdownInputDialogProps {
  busy: boolean;
  error: string | null;
  heading: string;
  includeTitle: boolean;
  onCancel: () => void;
  onPaste: (
    title: string,
    content: string,
    classification?: KnowledgeStatus,
  ) => Promise<void>;
  onUpload: (
    title: string,
    file: File,
    classification?: KnowledgeStatus,
  ) => Promise<void>;
  pasteSubmitLabel: string;
  uploadSubmitLabel: string;
  classificationOptions?: Array<{
    value: KnowledgeStatus;
    label: string;
  }>;
  classificationHelp?: string;
}

function markdownFileError(file: File): string | null {
  if (!file.name.toLowerCase().endsWith(".md")) {
    return "只支持 .md 文件。";
  }
  if (file.size > MARKDOWN_MAX_BYTES) {
    return "Markdown 文件不能超过 1 MiB。";
  }
  if (file.size === 0) {
    return "Markdown 文件不能为空。";
  }
  return null;
}

export function MarkdownInputDialog({
  busy,
  error,
  heading,
  includeTitle,
  onCancel,
  onPaste,
  onUpload,
  pasteSubmitLabel,
  uploadSubmitLabel,
  classificationOptions = [],
  classificationHelp,
}: MarkdownInputDialogProps) {
  const [mode, setMode] = useState<InputMode>("paste");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [classification, setClassification] = useState<KnowledgeStatus | "">("");
  const byteLength = new TextEncoder().encode(content).byteLength;

  function selectMode(nextMode: InputMode): void {
    setMode(nextMode);
    setLocalError(null);
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>): void {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
    setLocalError(selected ? markdownFileError(selected) : null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setLocalError(null);
    const normalizedTitle = title.trim();
    if (includeTitle && !normalizedTitle) {
      setLocalError("请输入文档标题。");
      return;
    }
    if (classificationOptions.length > 0 && !classification) {
      setLocalError("请选择资料身份。");
      return;
    }

    if (mode === "paste") {
      if (!content.trim()) {
        setLocalError("Markdown 内容不能为空。");
        return;
      }
      if (byteLength > MARKDOWN_MAX_BYTES) {
        setLocalError("Markdown 内容不能超过 1 MiB。");
        return;
      }
      await onPaste(normalizedTitle, content, classification || undefined);
      return;
    }

    if (!file) {
      setLocalError("请选择 Markdown 文件。");
      return;
    }
    const selectedFileError = markdownFileError(file);
    if (selectedFileError) {
      setLocalError(selectedFileError);
      return;
    }
    await onUpload(normalizedTitle, file, classification || undefined);
  }

  return (
    <div
      aria-labelledby="markdown-dialog-title"
      aria-modal="true"
      className="fixed inset-0 z-40 grid place-items-center bg-slate-950/45 p-4 backdrop-blur-sm"
      role="dialog"
    >
      <form
        className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-3xl bg-white p-6 shadow-2xl sm:p-8"
        onSubmit={(event) => void handleSubmit(event)}
      >
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-2xl font-semibold tracking-tight" id="markdown-dialog-title">
            {heading}
          </h2>
          <button
            aria-label="关闭 Markdown 表单"
            className="grid size-9 place-items-center rounded-full text-xl text-slate-500 hover:bg-slate-100"
            disabled={busy}
            onClick={onCancel}
            type="button"
          >
            ×
          </button>
        </div>

        <div className="mt-6 flex rounded-xl bg-slate-100 p-1" role="tablist">
          <button
            aria-selected={mode === "paste"}
            className={`flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold ${mode === "paste" ? "bg-white shadow-sm" : "text-slate-600"}`}
            onClick={() => selectMode("paste")}
            role="tab"
            type="button"
          >
            粘贴 Markdown
          </button>
          <button
            aria-selected={mode === "upload"}
            className={`flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold ${mode === "upload" ? "bg-white shadow-sm" : "text-slate-600"}`}
            onClick={() => selectMode("upload")}
            role="tab"
            type="button"
          >
            上传 .md 文件
          </button>
        </div>

        {includeTitle ? (
          <label className="mt-6 block text-sm font-medium text-slate-800">
            文档标题
            <input
              autoFocus
              className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 outline-none focus:border-cyan-700 focus:ring-4 focus:ring-cyan-100"
              maxLength={200}
              onChange={(event) => setTitle(event.target.value)}
              required
              value={title}
            />
          </label>
        ) : null}

        {classificationOptions.length > 0 ? (
          <label
            className="mt-5 block text-sm font-medium text-slate-800"
            htmlFor="knowledge-classification"
          >
            资料身份
            <select
              aria-label="资料身份"
              className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-4 py-3 outline-none focus:border-cyan-700 focus:ring-4 focus:ring-cyan-100"
              id="knowledge-classification"
              onChange={(event) =>
                setClassification(event.target.value as KnowledgeStatus | "")
              }
              required
              value={classification}
            >
              <option value="">请选择资料身份</option>
              {classificationOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            {classificationHelp ? (
              <span className="mt-2 block text-xs leading-5 text-slate-500">
                {classificationHelp}
              </span>
            ) : null}
          </label>
        ) : null}

        {mode === "paste" ? (
          <div className="mt-5 text-sm font-medium text-slate-800">
            <label htmlFor="markdown-content">Markdown 内容</label>
            <textarea
              className="mt-2 min-h-72 w-full resize-y rounded-xl border border-slate-300 px-4 py-3 font-mono text-sm leading-6 outline-none focus:border-cyan-700 focus:ring-4 focus:ring-cyan-100"
              id="markdown-content"
              onChange={(event) => setContent(event.target.value)}
              placeholder="# 标题\n\n在这里粘贴 Markdown…"
              required
              value={content}
            />
            <span className="mt-2 block text-xs text-slate-500">
              {byteLength.toLocaleString("zh-CN")} / {MARKDOWN_MAX_BYTES.toLocaleString("zh-CN")} 字节
            </span>
          </div>
        ) : (
          <div className="mt-5 block rounded-2xl border border-dashed border-slate-300 p-6 text-sm font-medium text-slate-800">
            <label htmlFor="markdown-file">选择 Markdown 文件</label>
            <input
              accept=".md"
              className="mt-3 block w-full text-sm"
              id="markdown-file"
              onChange={handleFileChange}
              type="file"
            />
            <span className="mt-3 block text-xs text-slate-500">
              仅接受 UTF-8 编码的 .md 文件，最大 1 MiB。
            </span>
            {file ? (
              <span className="mt-2 block text-sm text-slate-700">
                {file.name} · {file.size.toLocaleString("zh-CN")} 字节
              </span>
            ) : null}
          </div>
        )}

        {localError || error ? (
          <div
            className="mt-5 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"
            role="alert"
          >
            {localError ?? error}
          </div>
        ) : null}

        <div className="mt-7 flex justify-end gap-3">
          <button
            className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold"
            disabled={busy}
            onClick={onCancel}
            type="button"
          >
            取消
          </button>
          <button
            className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
            disabled={busy}
            type="submit"
          >
            {busy ? "正在保存…" : mode === "paste" ? pasteSubmitLabel : uploadSubmitLabel}
          </button>
        </div>
      </form>
    </div>
  );
}
