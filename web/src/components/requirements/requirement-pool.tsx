"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { readRequirement, requestPool } from "./requirement-api";
import type { RequirementFormValues } from "./requirement-form";
import { RequirementPoolError, RequirementPoolLoading } from "./requirement-pool-state";
import { RequirementPoolView } from "./requirement-pool-view";
import type {
  CustomerSummary,
  Requirement,
  WorkspaceIdentity,
} from "./requirement-types";

type LoadState = "loading" | "ready" | "error" | "redirecting";

export function RequirementPool() {
  const { replace } = useRouter();
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [customers, setCustomers] = useState<CustomerSummary[]>([]);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    let active = true;
    requestPool().then(
      (loaded) => {
        if (!active) return;
        if (loaded === null) {
          setLoadState("redirecting");
          replace("/login");
          return;
        }
        setIdentity(loaded.identity);
        setRequirements(loaded.requirements);
        setCustomers(loaded.customers);
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
      const loaded = await requestPool();
      if (loaded === null) {
        setLoadState("redirecting");
        replace("/login");
        return;
      }
      setIdentity(loaded.identity);
      setRequirements(loaded.requirements);
      setCustomers(loaded.customers);
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }

  if (loadState === "redirecting") return null;

  if (loadState === "loading") return <RequirementPoolLoading />;

  if (loadState === "error" || identity === null) {
    return (
      <RequirementPoolError
        onRetry={() => {
          setLoadState("loading");
          void retryLoad();
        }}
      />
    );
  }

  async function createRequirement(values: RequirementFormValues) {
    setSaving(true);
    setStatusMessage(null);
    try {
      const response = await fetch("/api/requirements", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (response.status === 401) {
        replace("/login");
        return { ok: false as const, message: "登录已失效，正在返回登录页。" };
      }
      if (!response.ok) {
        return { ok: false as const, message: "需求未保存，请检查编号或关联客户。" };
      }
      const created = await readRequirement(response);
      setRequirements((current) => [created, ...current]);
      setCreating(false);
      setStatusMessage("需求已创建");
      return { ok: true as const };
    } catch {
      return { ok: false as const, message: "网络连接失败，请稍后重试。" };
    } finally {
      setSaving(false);
    }
  }

  const canEdit = ["owner", "admin", "project_manager"].includes(identity.user.role);
  const editingRequirement =
    requirements.find((requirement) => requirement.id === editingId) ?? null;

  async function updateRequirement(
    requirement: Requirement,
    values: RequirementFormValues,
  ) {
    const patch: Record<string, unknown> = {};
    const currentValues = {
      code: requirement.code,
      title: requirement.title,
      customer_id: requirement.customer?.id ?? null,
      priority: requirement.priority,
      source: requirement.source,
      description: requirement.description,
      acceptance_criteria: requirement.acceptance_criteria,
      status: requirement.status,
    };
    for (const [key, value] of Object.entries(values)) {
      if (JSON.stringify(value) !== JSON.stringify(currentValues[key as keyof typeof currentValues])) {
        patch[key] = value;
      }
    }
    if (Object.keys(patch).length === 0) {
      setEditingId(null);
      setStatusMessage("没有需要保存的更改");
      return { ok: true as const };
    }
    setSaving(true);
    setStatusMessage(null);
    try {
      const response = await fetch(`/api/requirements/${requirement.id}`, {
        method: "PATCH",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (response.status === 401) {
        replace("/login");
        return { ok: false as const, message: "登录已失效，正在返回登录页。" };
      }
      if (!response.ok) {
        return { ok: false as const, message: "需求未更新，请检查字段或关联客户。" };
      }
      const updated = await readRequirement(response);
      setRequirements((current) =>
        current
          .map((item) => (item.id === updated.id ? updated : item))
          .sort((left, right) => right.updated_at.localeCompare(left.updated_at)),
      );
      setEditingId(null);
      setStatusMessage("需求已更新");
      return { ok: true as const };
    } catch {
      return { ok: false as const, message: "网络连接失败，请稍后重试。" };
    } finally {
      setSaving(false);
    }
  }

  async function logout() {
    setLoggingOut(true);
    try {
      await fetch("/api/session/logout", {
        method: "POST",
        credentials: "same-origin",
      });
    } finally {
      replace("/login");
    }
  }

  return (
    <RequirementPoolView
      canEdit={canEdit}
      creating={creating}
      customers={customers}
      editingRequirement={editingRequirement}
      identity={identity}
      loggingOut={loggingOut}
      onCancelCreate={() => setCreating(false)}
      onCancelEdit={() => setEditingId(null)}
      onCreate={createRequirement}
      onLogout={() => void logout()}
      onNew={() => {
        setEditingId(null);
        setCreating(true);
      }}
      onSelect={(requirement) => {
        setCreating(false);
        setEditingId(requirement.id);
      }}
      onUpdate={updateRequirement}
      requirements={requirements}
      saving={saving}
      statusMessage={statusMessage}
    />
  );
}
