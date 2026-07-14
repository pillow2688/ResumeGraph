import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  createProject,
  deleteProject,
  listProjects,
  updateProject,
} from "../api/projects";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Layout } from "../components/Layout";
import { ProjectCard } from "../components/ProjectCard";
import { ProjectForm } from "../components/ProjectForm";
import type { Project, ProjectCreateRequest } from "../types/project";

type FormMode = { type: "create" } | { type: "edit"; project: Project } | null;
type ProjectAction = "load" | "save" | "delete";

function getProjectErrorMessage(error: unknown, action: ProjectAction): string {
  if (error instanceof ApiError) {
    if (action === "delete" && error.status === 409 && error.code === "project_in_use") {
      return "该项目仍被访问授权或知识文档使用，请先解除相关引用。";
    }
    if (error.status === 422) {
      return "输入内容有误，请检查后重试。";
    }
    if (error.status === 503 || error.status === 0) {
      return action === "load"
        ? "加载项目失败，请稍后重试。"
        : "服务暂时不可用，请稍后重试。";
    }
  }

  const labels: Record<ProjectAction, string> = {
    load: "加载项目",
    save: "保存项目",
    delete: "删除项目",
  };
  return `${labels[action]}失败，请稍后重试。`;
}

export function Projects() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [formMode, setFormMode] = useState<FormMode>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [projectToDelete, setProjectToDelete] = useState<Project | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let isActive = true;

    async function loadProjectList(): Promise<void> {
      try {
        const loadedProjects = await listProjects();
        if (isActive) {
          setProjects(loadedProjects);
        }
      } catch (error) {
        if (!isActive) {
          return;
        }
        if (error instanceof ApiError && error.status === 401) {
          navigate("/admin/login", {
            replace: true,
            state: { message: "管理员会话已失效，请重新登录。" },
          });
          return;
        }
        setLoadError(getProjectErrorMessage(error, "load"));
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }

    void loadProjectList();
    return () => {
      isActive = false;
    };
  }, [navigate, reloadKey]);

  function retryLoad(): void {
    setIsLoading(true);
    setLoadError(null);
    setReloadKey((current) => current + 1);
  }

  async function handleSave(payload: ProjectCreateRequest): Promise<void> {
    if (!formMode) {
      return;
    }
    setIsSaving(true);
    setActionError(null);
    setNotice(null);
    try {
      if (formMode.type === "create") {
        const created = await createProject(payload);
        setProjects((current) => [created, ...current]);
        setNotice("项目已创建");
      } else {
        const updated = await updateProject(formMode.project.id, payload);
        setProjects((current) =>
          current.map((project) => (project.id === updated.id ? updated : project)),
        );
        setNotice("项目已更新");
      }
      setFormMode(null);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setActionError(getProjectErrorMessage(error, "save"));
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDelete(): Promise<void> {
    if (!projectToDelete) {
      return;
    }
    setIsDeleting(true);
    setActionError(null);
    setNotice(null);
    try {
      await deleteProject(projectToDelete.id);
      setProjects((current) =>
        current.filter((project) => project.id !== projectToDelete.id),
      );
      setProjectToDelete(null);
      setNotice("项目已删除");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        navigate("/admin/login", { replace: true });
        return;
      }
      setActionError(getProjectErrorMessage(error, "delete"));
      setProjectToDelete(null);
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <Layout>
      <section className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-cyan-700">管理员工作台</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">项目管理</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
            维护可授权给面试官查看的项目基础资料。
          </p>
        </div>
        <button
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
          onClick={() => setFormMode({ type: "create" })}
          type="button"
        >
          <span aria-hidden="true" className="text-lg">+</span>
          创建项目
        </button>
      </section>

      {notice ? (
        <div className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800" role="status">
          {notice}
        </div>
      ) : null}
      {actionError ? (
        <div className="mt-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800" role="alert">
          {actionError}
        </div>
      ) : null}

      <section aria-busy={isLoading} aria-label="项目列表" className="mt-8">
        {isLoading ? (
          <div className="grid min-h-64 place-items-center rounded-2xl border border-dashed border-slate-300 bg-white">
            <div className="text-center">
              <div className="mx-auto size-8 animate-spin rounded-full border-2 border-slate-200 border-t-cyan-700" />
              <p className="mt-4 text-sm font-medium text-slate-600">正在加载项目…</p>
            </div>
          </div>
        ) : loadError ? (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-6 py-10 text-center" role="alert">
            <h2 className="font-semibold text-rose-950">暂时无法显示项目</h2>
            <p className="mt-2 text-sm text-rose-800">{loadError}</p>
            <button
              className="mt-5 rounded-xl border border-rose-300 bg-white px-4 py-2.5 text-sm font-semibold text-rose-800 hover:bg-rose-100"
              onClick={retryLoad}
              type="button"
            >
              重新加载
            </button>
          </div>
        ) : projects.length === 0 ? (
          <div className="grid min-h-72 place-items-center rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center">
            <div>
              <div className="mx-auto grid size-14 place-items-center rounded-2xl bg-slate-100 text-2xl text-slate-600">+</div>
              <h2 className="mt-5 text-xl font-semibold">还没有项目</h2>
              <p className="mt-2 text-sm leading-6 text-slate-600">创建第一个项目，再为面试官配置访问授权。</p>
              <button
                className="mt-6 rounded-xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white hover:bg-slate-800"
                onClick={() => setFormMode({ type: "create" })}
                type="button"
              >
                创建第一个项目
              </button>
            </div>
          </div>
        ) : (
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            {projects.map((project) => (
              <ProjectCard
                key={project.id}
                onDelete={setProjectToDelete}
                onEdit={(selectedProject) =>
                  setFormMode({ type: "edit", project: selectedProject })
                }
                project={project}
              />
            ))}
          </div>
        )}
      </section>

      {formMode ? (
        <ProjectForm
          initialProject={formMode.type === "edit" ? formMode.project : undefined}
          isSaving={isSaving}
          key={formMode.type === "edit" ? formMode.project.id : "create"}
          onCancel={() => setFormMode(null)}
          onSubmit={handleSave}
        />
      ) : null}

      {projectToDelete ? (
        <ConfirmDialog
          busyLabel="正在删除…"
          confirmLabel="确认删除"
          description={`你将删除“${projectToDelete.name}”。该操作完成后无法撤销。`}
          isConfirming={isDeleting}
          onCancel={() => setProjectToDelete(null)}
          onConfirm={handleDelete}
          title="确认删除项目？"
        />
      ) : null}
    </Layout>
  );
}
