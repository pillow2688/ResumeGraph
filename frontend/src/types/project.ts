export interface Project {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface ProjectCreateRequest {
  name: string;
  description: string;
}

export interface ProjectUpdateRequest {
  name?: string;
  description?: string;
}
