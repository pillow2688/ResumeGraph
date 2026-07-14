export interface ProjectSummary {
  id: string;
  name: string;
}

export interface AccessGrant {
  id: string;
  name: string;
  expires_at: string;
  max_requests: number;
  request_count: number;
  revoked_at: string | null;
  created_at: string;
  projects: ProjectSummary[];
}

export interface AccessGrantCreateRequest {
  name: string;
  expires_at: string;
  max_requests: number;
  project_ids: string[];
}

export interface AccessGrantCreateResponse {
  grant: AccessGrant;
  access_token: string;
}

export interface AccessTokenExchangeRequest {
  access_token: string;
}

export interface RecruiterSession {
  grant_id: string;
  grant_name: string;
  expires_at: string;
  remaining_requests: number;
  allowed_projects: ProjectSummary[];
}

export interface RecruiterExchangeResponse {
  recruiter: RecruiterSession;
}

