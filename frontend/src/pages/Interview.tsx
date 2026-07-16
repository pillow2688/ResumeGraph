import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  createInterviewConversation,
  deleteInterviewConversation,
  streamInterviewQuestion,
} from "../api/interview";
import { getRecruiterSession, logoutRecruiter } from "../api/recruiterAccess";
import { ChatComposer } from "../components/interview/ChatComposer";
import { ChatMessageList } from "../components/interview/ChatMessageList";
import { ChatWindow } from "../components/interview/ChatWindow";
import { CitationDrawer } from "../components/interview/CitationDrawer";
import { ConversationSidebar } from "../components/interview/ConversationSidebar";
import { InterviewHeader } from "../components/interview/InterviewHeader";
import { InterviewLayout } from "../components/interview/InterviewLayout";
import type { InterviewChatTurn } from "../components/interview/types";
import { WelcomeSuggestions } from "../components/interview/WelcomeSuggestions";
import type { RecruiterSession } from "../types/accessGrant";
import type {
  InterviewPublicCitation,
  InterviewPublicEvent,
} from "../types/interview";

function uuid(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const suffix = Math.random().toString(16).slice(2).padEnd(12, "0").slice(0, 12);
  return `00000000-0000-4000-8000-${suffix}`;
}

function safeErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429 || error.code === "request_quota_exhausted") {
      return "当前访问授权的请求次数已用完。";
    }
    if (error.code === "conversation_not_found") {
      return "当前对话已过期，请新建对话后继续。";
    }
    if (error.status === 409) {
      return "当前对话正在处理另一个问题，请稍候再试。";
    }
    if (error.message && !error.message.toLowerCase().includes("internal")) {
      return error.message;
    }
  }
  return "面试回答服务暂时不可用，请稍后重试。";
}

export function Interview() {
  const navigate = useNavigate();
  const [session, setSession] = useState<RecruiterSession | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [remainingRequests, setRemainingRequests] = useState(0);
  const [selectedProjectIds, setSelectedProjectIds] = useState<string[]>([]);
  const [turns, setTurns] = useState<InterviewChatTurn[]>([]);
  const [question, setQuestion] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [citation, setCitation] = useState<InterviewPublicCitation | null>(null);
  const [activeProjectIds, setActiveProjectIds] = useState<string[]>([]);
  const [activeTopics, setActiveTopics] = useState<string[]>([]);
  const [turnNumber, setTurnNumber] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  const projectNames = useMemo(() => {
    const selected = new Set(selectedProjectIds);
    return (
      session?.allowed_projects
        .filter((project) => selected.has(project.id))
        .map((project) => project.name) ?? []
    );
  }, [selectedProjectIds, session]);

  const activeProjectNames = useMemo(() => {
    const active = new Set(activeProjectIds);
    return (
      session?.allowed_projects
        .filter((project) => active.has(project.id))
        .map((project) => project.name) ?? []
    );
  }, [activeProjectIds, session]);

  useEffect(() => {
    let active = true;
    async function initialize(): Promise<void> {
      try {
        const currentSession = await getRecruiterSession();
        if (!active) return;
        setSession(currentSession);
        setSelectedProjectIds(currentSession.allowed_projects.map((project) => project.id));
        setRemainingRequests(currentSession.remaining_requests);
        const conversation = await createInterviewConversation();
        if (!active) return;
        setConversationId(conversation.conversation_id);
        setRemainingRequests(conversation.remaining_requests);
      } catch (error) {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          navigate("/access", { replace: true });
          return;
        }
        setPageError("暂时无法创建面试对话，请稍后重试。");
      } finally {
        if (active) setIsLoading(false);
      }
    }
    void initialize();
    return () => {
      active = false;
      abortRef.current?.abort();
    };
  }, [navigate]);

  function updateTurn(
    turnId: string,
    update: (turn: InterviewChatTurn) => InterviewChatTurn,
  ): void {
    setTurns((current) =>
      current.map((turn) => (turn.id === turnId ? update(turn) : turn)),
    );
  }

  async function sendQuestion(overrideQuestion?: string): Promise<void> {
    const normalized = (overrideQuestion ?? question).trim();
    if (!conversationId || !normalized || isSubmitting || remainingRequests <= 0) return;

    const turnId = uuid();
    const controller = new AbortController();
    abortRef.current = controller;
    setQuestion("");
    setIsSubmitting(true);
    setPageError(null);
    setTurns((current) => [
      ...current,
      {
        id: turnId,
        question: normalized,
        events: [],
        response: null,
        error: null,
        stopped: false,
      },
    ]);

    function onEvent(event: InterviewPublicEvent): void {
      if (event.event_type === "heartbeat" || event.event_type === "answer_completed") return;
      updateTurn(turnId, (turn) => ({ ...turn, events: [...turn.events, event] }));
    }

    try {
      const response = await streamInterviewQuestion(
        conversationId,
        {
          request_id: turnId,
          question: normalized,
          ...(selectedProjectIds.length > 0
            ? { project_ids: selectedProjectIds }
            : {}),
        },
        { signal: controller.signal, onEvent },
      );
      updateTurn(turnId, (turn) => ({ ...turn, response }));
      setRemainingRequests(response.remaining_requests);
      setActiveProjectIds(response.context.active_project_ids);
      setActiveTopics(response.context.active_technical_topics);
      setTurnNumber(response.context.turn_number);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        updateTurn(turnId, (turn) => ({ ...turn, stopped: true }));
      } else if (error instanceof ApiError && error.status === 401) {
        setTurns([]);
        setConversationId(null);
        navigate("/access", { replace: true });
      } else {
        if (error instanceof ApiError && error.status === 429) setRemainingRequests(0);
        updateTurn(turnId, (turn) => ({ ...turn, error: safeErrorMessage(error) }));
      }
    } finally {
      abortRef.current = null;
      setIsSubmitting(false);
    }
  }

  async function newConversation(): Promise<void> {
    if (isSubmitting || !conversationId) return;
    setPageError(null);
    try {
      await deleteInterviewConversation(conversationId);
      const created = await createInterviewConversation();
      setConversationId(created.conversation_id);
      setRemainingRequests(created.remaining_requests);
      setTurns([]);
      setQuestion("");
      setActiveProjectIds([]);
      setActiveTopics([]);
      setTurnNumber(0);
      setCitation(null);
      setSidebarOpen(false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setTurns([]);
        navigate("/access", { replace: true });
        return;
      }
      setPageError(safeErrorMessage(error));
    }
  }

  async function logout(): Promise<void> {
    abortRef.current?.abort();
    try {
      await logoutRecruiter();
      setTurns([]);
      setConversationId(null);
      navigate("/access", { replace: true });
    } catch {
      setPageError("暂时无法退出访问，请稍后重试。");
    }
  }

  function toggleProject(projectId: string): void {
    setSelectedProjectIds((current) =>
      current.includes(projectId)
        ? current.filter((value) => value !== projectId)
        : [...current, projectId],
    );
  }

  return (
    <InterviewLayout
      citationDrawer={<CitationDrawer citation={citation} onClose={() => setCitation(null)} />}
      header={
        <InterviewHeader
          conversationReady={Boolean(conversationId)}
          onMenu={() => setSidebarOpen(true)}
          onNewConversation={() => void newConversation()}
          projectNames={projectNames}
          remainingRequests={remainingRequests}
        />
      }
      sidebar={
        <ConversationSidebar
          conversationId={conversationId}
          disabled={isSubmitting}
          onClose={() => setSidebarOpen(false)}
          onLogout={() => void logout()}
          onNewConversation={() => void newConversation()}
          onProjectToggle={toggleProject}
          open={sidebarOpen}
          remainingRequests={remainingRequests}
          selectedProjectIds={selectedProjectIds}
          session={session}
        />
      }
    >
      <ChatWindow
        composer={
          <ChatComposer
            disabled={isLoading || !conversationId || remainingRequests <= 0}
            isSubmitting={isSubmitting}
            onChange={setQuestion}
            onSend={() => void sendQuestion()}
            onStop={() => abortRef.current?.abort()}
            projectNames={projectNames}
            value={question}
          />
        }
      >
      {pageError ? (
        <div
          className="mx-auto mt-3 w-[calc(100%-2rem)] max-w-5xl rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900"
          role="alert"
        >
          {pageError}
        </div>
      ) : null}

      {turns.length === 0 ? (
        <WelcomeSuggestions onSelect={setQuestion} projectNames={projectNames} />
      ) : (
        <>
          {(activeProjectNames.length > 0 || activeTopics.length > 0 || turnNumber > 0) && (
            <div className="mx-auto flex w-full max-w-5xl flex-wrap gap-x-4 gap-y-1 px-4 pt-3 text-xs text-slate-500 sm:px-6">
              {activeProjectNames.length > 0 ? (
                <span>当前项目：{activeProjectNames.join("、")}</span>
              ) : null}
              {activeTopics.length > 0 ? (
                <span>当前技术主题：{activeTopics.join("、")}</span>
              ) : null}
              {turnNumber > 0 ? <span>当前对话：第 {turnNumber} 轮</span> : null}
            </div>
          )}
          <ChatMessageList
            onCitationOpen={setCitation}
            onRetry={(retryQuestion) => void sendQuestion(retryQuestion)}
            turns={turns}
          />
        </>
      )}

      </ChatWindow>
    </InterviewLayout>
  );
}
