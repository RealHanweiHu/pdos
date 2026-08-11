"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { WorkspaceIdentity } from "@/components/workspace-types";

import { readCase, requestCases } from "./case-api";
import type { CaseFormValues } from "./case-form";
import type { DevelopmentCase } from "./case-types";
import { CaseWorkspaceError, CaseWorkspaceLoading } from "./case-workspace-state";
import { CaseWorkspaceView } from "./case-workspace-view";

type LoadState = "loading" | "ready" | "error" | "redirecting";

export function CaseWorkspace() {
  const { replace } = useRouter();
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [cases, setCases] = useState<DevelopmentCase[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    requestCases().then(
      (loaded) => {
        if (!active) return;
        if (loaded === null) {
          setLoadState("redirecting");
          replace("/login");
          return;
        }
        setIdentity(loaded.identity);
        setCases(loaded.cases);
        setLoadState("ready");
      },
      () => {
        if (active) setLoadState("error");
      },
    );
    return () => {
      active = false;
    };
  }, [replace]);

  async function retryLoad() {
    try {
      const loaded = await requestCases();
      if (loaded === null) {
        setLoadState("redirecting");
        replace("/login");
        return;
      }
      setIdentity(loaded.identity);
      setCases(loaded.cases);
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }

  if (loadState === "redirecting") return null;
  if (loadState === "loading") return <CaseWorkspaceLoading />;
  if (loadState === "error" || identity === null) {
    return (
      <CaseWorkspaceError
        onRetry={() => {
          setLoadState("loading");
          void retryLoad();
        }}
      />
    );
  }

  const selectedCase = cases.find((developmentCase) => developmentCase.id === selectedId) ?? null;
  const canEdit = ["owner", "admin", "project_manager"].includes(identity.user.role);

  async function updateCase(developmentCase: DevelopmentCase, values: CaseFormValues) {
    const patch: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(values)) {
      if (JSON.stringify(value) !== JSON.stringify(developmentCase[key as keyof CaseFormValues])) {
        patch[key] = value;
      }
    }
    if (Object.keys(patch).length === 0) {
      setSelectedId(null);
      setStatusMessage("没有需要保存的更改");
      return { ok: true as const };
    }
    setSaving(true);
    setStatusMessage(null);
    setErrorMessage(null);
    try {
      const response = await fetch(`/api/development-cases/${developmentCase.id}`, {
        method: "PATCH",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (response.status === 401) {
        replace("/login");
        return { ok: false as const, message: "登录已失效，正在返回登录页。" };
      }
      if (!response.ok) return { ok: false as const, message: "开发案例未更新，请检查字段。" };
      const updated = await readCase(response);
      setCases((current) =>
        current
          .map((item) => (item.id === updated.id ? updated : item))
          .sort((left, right) => right.updated_at.localeCompare(left.updated_at)),
      );
      setSelectedId(null);
      setStatusMessage("开发案例已更新");
      return { ok: true as const };
    } catch {
      return { ok: false as const, message: "网络连接失败，请稍后重试。" };
    } finally {
      setSaving(false);
    }
  }

  async function transitionCase(developmentCase: DevelopmentCase, toStatus: DevelopmentCase["status"]) {
    setSaving(true);
    setStatusMessage(null);
    setErrorMessage(null);
    try {
      const response = await fetch(`/api/development-cases/${developmentCase.id}/transitions`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to_status: toStatus }),
      });
      if (response.status === 401) {
        replace("/login");
        return;
      }
      if (!response.ok) {
        setErrorMessage("状态未更新，请检查当前状态或关联 Project。");
        return;
      }
      const updated = await readCase(response);
      setCases((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setStatusMessage(`状态已更新为${caseStatusLabel(updated.status)}`);
    } catch {
      setErrorMessage("状态更新失败，请稍后重试。");
    } finally {
      setSaving(false);
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

  return (
    <CaseWorkspaceView
      canEdit={canEdit}
      cases={cases}
      errorMessage={errorMessage}
      identity={identity}
      loggingOut={loggingOut}
      onCancelEdit={() => setSelectedId(null)}
      onLogout={() => void logout()}
      onSelect={(developmentCase) => setSelectedId(developmentCase.id)}
      onTransition={(developmentCase, toStatus) => void transitionCase(developmentCase, toStatus)}
      onUpdate={updateCase}
      saving={saving}
      selectedCase={selectedCase}
      statusMessage={statusMessage}
    />
  );
}

function caseStatusLabel(status: DevelopmentCase["status"]) {
  return {
    draft: "草稿",
    evaluating: "评估中",
    approved: "已批准",
    rejected: "已拒绝",
    converted: "已转项目",
  }[status];
}
