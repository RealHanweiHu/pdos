"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { WorkspaceIdentity } from "@/components/workspace-types";

import { requestPool } from "./requirement-api";
import { RequirementPoolError, RequirementPoolLoading } from "./requirement-pool-state";
import { RequirementPoolView } from "./requirement-pool-view";
import type { CustomerSummary } from "./requirement-types";
import { useRequirementActions } from "./use-requirement-actions";

type LoadState = "loading" | "ready" | "error" | "redirecting";

export function RequirementPool() {
  const { push, replace } = useRouter();
  const actions = useRequirementActions({ push, replace });
  const { setRequirements } = actions;
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [customers, setCustomers] = useState<CustomerSummary[]>([]);
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
  }, [replace, setRequirements]);

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

  const canEdit = ["owner", "admin", "project_manager"].includes(identity.user.role);
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
      creating={actions.creating}
      customers={customers}
      convertingRequirement={actions.convertingRequirement}
      editingRequirement={actions.editingRequirement}
      identity={identity}
      loggingOut={loggingOut}
      onCancelCreate={actions.cancelCreate}
      onCancelConversion={actions.cancelConversion}
      onCancelEdit={actions.cancelEdit}
      onCreate={actions.createRequirement}
      onConvert={actions.convertRequirement}
      onBeginConversion={actions.beginConversion}
      onLogout={() => void logout()}
      onNew={actions.startCreate}
      onSelect={actions.selectRequirement}
      onUpdate={actions.updateRequirement}
      requirements={actions.requirements}
      saving={actions.saving}
      statusMessage={actions.statusMessage}
    />
  );
}
