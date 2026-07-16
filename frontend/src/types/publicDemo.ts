import type { AccessGrant } from "./accessGrant";

export type PublicDemoStatus =
  | {
      available: true;
      candidate_name: string;
      message?: never;
    }
  | {
      available: false;
      candidate_name?: never;
      message: string;
    };

export interface PublicDemoSession {
  redirect_url: "/interview";
}

export interface PublicDemoAdminConfig {
  configured: boolean;
  candidate_name?: string;
  default_access_grant_id?: string;
  default_access_grant?: AccessGrant;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface PublicDemoUpdateRequest {
  candidate_name: string;
  default_access_grant_id: string;
  enabled: boolean;
}
