"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { WorkspaceIdentity } from "@/components/workspace-types";

import { requestProjects } from "./project-api";
import { ProjectWorkspaceError, ProjectWorkspaceLoading } from "./project-workspace-state";
import { ProjectWorkspaceView } from "./project-workspace-view";
import { useProjectActions } from "./use-project-actions";

type LoadState = "loading" | "ready" | "error" | "redirecting";

export function ProjectWorkspace() {
  const { replace } = useRouter();
  const actions = useProjectActions({ replace });
  const { setProjects } = actions;
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    let active = true;
    requestProjects().then(
      (loaded) => {
        if (!active) return;
        if (loaded === null) {
          setLoadState("redirecting");
          replace("/login");
          return;
        }
        setIdentity(loaded.identity);
        setProjects(loaded.projects);
        setLoadState("ready");
      },
      () => {
        if (active) setLoadState("error");
      },
    );
    return () => { active = false; };
  }, [replace, setProjects]);

  async function retryLoad() {
    try {
      const loaded = await requestProjects();
      if (loaded === null) {
        setLoadState("redirecting");
        replace("/login");
        return;
      }
      setIdentity(loaded.identity);
      setProjects(loaded.projects);
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }

  async function logout() {
    setLoggingOut(true);
    try {
      await fetch("/api/session/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      replace("/login");
    }
  }

  if (loadState === "redirecting") return null;
  if (loadState === "loading") return <ProjectWorkspaceLoading />;
  if (loadState === "error" || identity === null) {
    return <ProjectWorkspaceError onRetry={() => { setLoadState("loading"); void retryLoad(); }} />;
  }
  const canEdit = ["owner", "admin", "project_manager"].includes(identity.user.role);
  return (
    <ProjectWorkspaceView
      canEdit={canEdit}
      errorMessage={actions.errorMessage}
      identity={identity}
      loggingOut={loggingOut}
      onCancelEdit={actions.clearSelection}
      onLogout={() => void logout()}
      onSelect={actions.selectProject}
      onStageTransition={(project, stageId) => void actions.transitionStage(project, stageId)}
      onStatusTransition={(project, status) => void actions.transitionStatus(project, status)}
      onUpdate={actions.updateProject}
      projects={actions.projects}
      saving={actions.saving}
      selectedProject={actions.selectedProject}
      statusMessage={actions.statusMessage}
    />
  );
}
