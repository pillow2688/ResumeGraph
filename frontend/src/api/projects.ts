import type {
  Project,
  ProjectCreateRequest,
  ProjectUpdateRequest,
} from "../types/project";
import { apiRequest } from "./client";

const projectsPath = "/api/v1/admin/projects";

export function listProjects(): Promise<Project[]> {
  return apiRequest<Project[]>(projectsPath);
}

export function getProject(projectId: string): Promise<Project> {
  return apiRequest<Project>(`${projectsPath}/${projectId}`);
}

export function createProject(payload: ProjectCreateRequest): Promise<Project> {
  return apiRequest<Project, ProjectCreateRequest>(projectsPath, {
    method: "POST",
    body: payload,
  });
}

export function updateProject(
  projectId: string,
  payload: ProjectUpdateRequest,
): Promise<Project> {
  return apiRequest<Project, ProjectUpdateRequest>(`${projectsPath}/${projectId}`, {
    method: "PATCH",
    body: payload,
  });
}

export function deleteProject(projectId: string): Promise<void> {
  return apiRequest<void>(`${projectsPath}/${projectId}`, {
    method: "DELETE",
  });
}
