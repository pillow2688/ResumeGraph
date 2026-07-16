import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { InterviewPublicCitation } from "../../types/interview";
import type { InterviewChatTurn } from "./types";
import { AgentProgress } from "./AgentProgress";
import { CitationList } from "./CitationList";
import { MessageBubble } from "./MessageBubble";

const statusMessage = {
  answered: null,
  answered_with_boundary: "以下回答包含当前实现情况和后续可考虑的方案。",
  partial_answer: "现有资料只能确认其中一部分。",
  insufficient_evidence: "现有资料不足以支持准确回答。",
  access_restricted: "该问题涉及当前未开放的项目资料。",
} as const;

interface AssistantMessageProps {
  turn: InterviewChatTurn;
  onCitationOpen: (citation: InterviewPublicCitation) => void;
  onRetry: (question: string) => void;
}

export function AssistantMessage({
  turn,
  onCitationOpen,
  onRetry,
}: AssistantMessageProps) {
  const response = turn.response;

  async function copyAnswer(): Promise<void> {
    if (response && navigator.clipboard) {
      await navigator.clipboard.writeText(response.answer);
    }
  }

  return (
    <MessageBubble label="AI 候选人回答" side="left">
        <p className="mb-3 text-xs font-semibold text-slate-500">AI 候选人</p>
        {!response && !turn.error && !turn.stopped ? (
          <AgentProgress completed={false} events={turn.events} />
        ) : null}
        {response ? (
          <>
            {statusMessage[response.status] ? (
              <p className="mb-3 rounded-lg bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
                {statusMessage[response.status]}
              </p>
            ) : null}
            <div className="interview-markdown text-[15px] leading-7 text-slate-800">
              <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
                {response.answer}
              </ReactMarkdown>
            </div>
            {response.agent_trace.public_path.length > 0 ? (
              <p className="mt-4 text-xs text-slate-500">
                回答路径：{response.agent_trace.public_path.join(" → ")}
              </p>
            ) : null}
            <AgentProgress completed events={turn.events} />
            <CitationList citations={response.citations} onOpen={onCitationOpen} />
            <div className="mt-4 flex gap-2">
              <button
                className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-800"
                onClick={() => void copyAnswer()}
                type="button"
              >
                复制回答
              </button>
            </div>
          </>
        ) : null}
        {turn.error || turn.stopped ? (
          <div
            className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900"
            role="alert"
          >
            <p>{turn.stopped ? "已停止生成。你可以修改问题后重新提交。" : turn.error}</p>
            {!turn.stopped ? (
              <button
                className="mt-3 rounded-lg border border-rose-300 bg-white px-3 py-1.5 text-xs font-semibold"
                onClick={() => onRetry(turn.question)}
                type="button"
              >
                重新提交
              </button>
            ) : null}
          </div>
        ) : null}
    </MessageBubble>
  );
}
