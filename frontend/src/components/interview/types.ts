import type {
  ConversationAskResponse,
  InterviewPublicEvent,
} from "../../types/interview";

export interface InterviewChatTurn {
  id: string;
  question: string;
  events: InterviewPublicEvent[];
  response: ConversationAskResponse | null;
  error: string | null;
  stopped: boolean;
}
