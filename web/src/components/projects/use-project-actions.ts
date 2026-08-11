"use client";

import { useState } from "react";

import { readProject } from "./project-api";
import type { ProjectFormValues } from "./project-form";
import type { Project } from "./project-types";

export function useProjectActions({ replace }: { replace: (href: string) => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const selectedProject = projects.find((project) => project.id === selectedId) ?? null;

  function applyProject(updated: Project) {
    setProjects((current) =>
      current
        .map((project) => (project.id === updated.id ? updated : project))
        .sort((left, right) => right.updated_at.localeCompare(left.updated_at)),
    );
  }

  async function authenticatedProjectRequest(path: string, body: object) {
    const response = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (response.status === 401) {
      replace("/login");
      return null;
    }
    return response;
  }

  async function updateProject(project: Project, values: ProjectFormValues) {
    const patch: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(values)) {
      if (JSON.stringify(value) !== JSON.stringify(project[key as keyof ProjectFormValues])) {
        patch[key] = value;
      }
    }
    if (Object.keys(patch).length === 0) {
      setStatusMessage("没有需要保存的更改");
      return { ok: true as const };
    }
    setSaving(true);
    setStatusMessage(null);
    setErrorMessage(null);
    try {
      const response = await fetch(`/api/projects/${project.id}`, {
        method: "PATCH",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (response.status === 401) {
        replace("/login");
        return { ok: false as const, message: "登录已失效，正在返回登录页。" };
      }
      if (!response.ok) return { ok: false as const, message: "项目未更新，请检查字段。" };
      applyProject(await readProject(response));
      setStatusMessage("项目已更新");
      return { ok: true as const };
    } catch {
      return { ok: false as const, message: "网络连接失败，请稍后重试。" };
    } finally {
      setSaving(false);
    }
  }

  async function transitionStatus(project: Project, toStatus: Project["status"]) {
    setSaving(true);
    setStatusMessage(null);
    setErrorMessage(null);
    try {
      const response = await authenticatedProjectRequest(
        `/api/projects/${project.id}/transitions`,
        { to_status: toStatus },
      );
      if (response === null) return;
      if (!response.ok) {
        setErrorMessage("项目状态未更新，请检查当前状态。");
        return;
      }
      const updated = await readProject(response);
      applyProject(updated);
      setStatusMessage(`状态已更新为${projectStatusLabel(updated.status)}`);
    } catch {
      setErrorMessage("项目状态更新失败，请稍后重试。");
    } finally {
      setSaving(false);
    }
  }

  async function transitionStage(project: Project, toStageId: string) {
    setSaving(true);
    setStatusMessage(null);
    setErrorMessage(null);
    try {
      const response = await authenticatedProjectRequest(
        `/api/projects/${project.id}/stage-transitions`,
        { to_stage_id: toStageId },
      );
      if (response === null) return;
      if (!response.ok) {
        setErrorMessage("阶段未推进；仅进行中的项目可进入相邻阶段。");
        return;
      }
      const updated = await readProject(response);
      applyProject(updated);
      setStatusMessage(`当前阶段已推进到${updated.current_stage.name}`);
    } catch {
      setErrorMessage("阶段推进失败，请稍后重试。");
    } finally {
      setSaving(false);
    }
  }

  return {
    clearSelection: () => setSelectedId(null),
    errorMessage,
    projects,
    saving,
    selectProject: (project: Project) => setSelectedId(project.id),
    selectedProject,
    setProjects,
    statusMessage,
    transitionStage,
    transitionStatus,
    updateProject,
  };
}

function projectStatusLabel(status: Project["status"]) {
  return {
    draft: "草稿",
    proposed: "待批准",
    approved: "已批准",
    active: "进行中",
    on_hold: "已暂停",
    completed: "已完成",
    archived: "已归档",
  }[status];
}
