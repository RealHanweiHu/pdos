"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import type { WorkspaceIdentity } from "@/components/workspace-types";

import {
  requestModelGovernanceBootstrap,
  updateModelGovernance,
} from "./model-governance-api";
import {
  ModelGovernanceError,
  ModelGovernanceForbidden,
  ModelGovernanceLoading,
} from "./model-governance-state";
import type { ModelGovernanceSnapshot, ModelGovernanceUpdate } from "./model-governance-types";
import { ModelGovernanceView } from "./model-governance-view";

type LoadState = "loading" | "ready" | "forbidden" | "error" | "redirecting";

export function ModelGovernance() {
  const { replace } = useRouter();
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [snapshot, setSnapshot] = useState<ModelGovernanceSnapshot | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const applyBootstrap = useCallback(
    (loaded: Awaited<ReturnType<typeof requestModelGovernanceBootstrap>>) => {
      if (loaded === null) {
        setLoadState("redirecting");
        replace("/login");
        return;
      }
      setIdentity(loaded.identity);
      if (loaded.kind === "forbidden") {
        setLoadState("forbidden");
        return;
      }
      setSnapshot(loaded.snapshot);
      setLoadState("ready");
    },
    [replace],
  );

  async function load() {
    try {
      applyBootstrap(await requestModelGovernanceBootstrap());
    } catch {
      setLoadState("error");
    }
  }

  useEffect(() => {
    let active = true;
    requestModelGovernanceBootstrap().then(
      (loaded) => {
        if (active) applyBootstrap(loaded);
      },
      () => {
        if (active) setLoadState("error");
      },
    );
    return () => {
      active = false;
    };
  }, [applyBootstrap]);

  async function save(update: ModelGovernanceUpdate) {
    setSaving(true);
    setSaved(false);
    setSaveError(null);
    try {
      const updated = await updateModelGovernance(update);
      if (updated === null) {
        setLoadState("redirecting");
        replace("/login");
        return;
      }
      setSnapshot(updated);
      setSaved(true);
    } catch {
      setSaveError("保存失败。设置必须来自合格候选池，且预算须在允许范围内。");
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

  if (loadState === "redirecting") return null;
  if (loadState === "loading") return <ModelGovernanceLoading />;
  if (loadState === "error" || identity === null) {
    return (
      <ModelGovernanceError
        onRetry={() => {
          setLoadState("loading");
          void load();
        }}
      />
    );
  }
  if (loadState === "forbidden") {
    return (
      <ModelGovernanceForbidden
        identity={identity}
        loggingOut={loggingOut}
        onLogout={() => void logout()}
      />
    );
  }
  if (snapshot === null) return <ModelGovernanceLoading />;
  return (
    <ModelGovernanceView
      identity={identity}
      loggingOut={loggingOut}
      onLogout={() => void logout()}
      onSave={(update) => void save(update)}
      saveError={saveError}
      saved={saved}
      saving={saving}
      snapshot={snapshot}
    />
  );
}
