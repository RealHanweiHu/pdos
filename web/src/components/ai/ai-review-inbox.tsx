"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { requestProjects } from "@/components/projects/project-api";
import type { Project } from "@/components/projects/project-types";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import { applyFinding, requestFindings, reviewFinding } from "./ai-api";
import { AiReviewInboxView, type FindingFilter } from "./ai-review-inbox-view";
import type { AiFinding } from "./ai-types";

type LoadState = "loading" | "ready" | "forbidden" | "error" | "redirecting";
const internalRoles = new Set(["owner", "admin", "project_manager", "engineer", "quality"]);

function messageFrom(error: unknown) {
  return error instanceof Error ? error.message : "操作失败，请稍后重试。";
}

export function AiReviewInbox() {
  const { replace } = useRouter();
  const [state, setState] = useState<LoadState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [findings, setFindings] = useState<AiFinding[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<FindingFilter>("all");
  const [busy, setBusy] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  async function load() {
    try {
      const loaded = await requestProjects();
      if (loaded === null) {
        setState("redirecting");
        replace("/login");
        return;
      }
      setIdentity(loaded.identity);
      if (!internalRoles.has(loaded.identity.user.role)) {
        setState("forbidden");
        return;
      }
      const items = await requestFindings();
      setProjects(loaded.projects);
      setFindings(items);
      const deepLinkedId = new URLSearchParams(window.location.search).get("finding");
      setSelectedId(
        items.some((item) => item.id === deepLinkedId) ? deepLinkedId : items[0]?.id ?? null,
      );
      setState("ready");
    } catch (loadError) {
      setError(messageFrom(loadError));
      setState("error");
    }
  }

  useEffect(() => {
    let active = true;
    requestProjects().then(
      async (loaded) => {
        if (!active) return;
        if (loaded === null) {
          setState("redirecting");
          replace("/login");
          return;
        }
        setIdentity(loaded.identity);
        if (!internalRoles.has(loaded.identity.user.role)) {
          setState("forbidden");
          return;
        }
        try {
          const items = await requestFindings();
          if (!active) return;
          setProjects(loaded.projects);
          setFindings(items);
          const deepLinkedId = new URLSearchParams(window.location.search).get("finding");
          setSelectedId(
            items.some((item) => item.id === deepLinkedId) ? deepLinkedId : items[0]?.id ?? null,
          );
          setState("ready");
        } catch (loadError) {
          if (!active) return;
          setError(messageFrom(loadError));
          setState("error");
        }
      },
      (loadError) => {
        if (!active) return;
        setError(messageFrom(loadError));
        setState("error");
      },
    );
    return () => { active = false; };
  }, [replace]);

  const filtered = useMemo(
    () => findings.filter((finding) => filter === "all" || finding.finding_type === filter),
    [filter, findings],
  );
  const selected =
    filtered.find((finding) => finding.id === selectedId) ?? filtered[0] ?? null;

  function replaceFinding(updated: AiFinding, success: string) {
    setFindings((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    setSelectedId(updated.id);
    setStatus(success);
  }

  async function review(
    finding: AiFinding,
    payload: Parameters<typeof reviewFinding>[1],
    success: string,
  ) {
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      replaceFinding(await reviewFinding(finding.id, payload), success);
      return true;
    } catch (reviewError) {
      setError(messageFrom(reviewError));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function apply(finding: AiFinding) {
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      replaceFinding(
        await applyFinding(finding.id),
        finding.finding_type === "knowledge_draft"
          ? "Finding 已应用为未验证 Memory 草稿；仍需另一位成员验证"
          : "Finding 已应用到业务对象，并完成二次鉴权与真值复核",
      );
    } catch (applyError) {
      setError(messageFrom(applyError));
    } finally {
      setBusy(false);
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

  if (state === "redirecting") return null;
  if (state === "loading") {
    return <main aria-busy="true" className="mx-auto max-w-6xl px-4 py-10 text-sm text-muted-foreground">正在加载 AI Review 收件箱…</main>;
  }
  if (state === "error" || identity === null) {
    return (
      <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
        <h1 className="text-lg font-semibold">AI Review 暂不可用</h1>
        <p className="mt-1 text-sm text-muted-foreground">{error ?? "无法读取收件箱。"}</p>
        <button className="mt-4 min-h-11 rounded-lg bg-primary px-3 text-primary-foreground" onClick={() => { setState("loading"); setError(null); void load(); }} type="button">重新加载</button>
      </main>
    );
  }
  if (state === "forbidden") {
    return (
      <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
        <h1 className="text-lg font-semibold">此工作区仅供内部成员</h1>
        <p className="mt-1 text-sm text-muted-foreground">外部成员不能查看或裁决 AI Finding。</p>
      </main>
    );
  }

  return (
    <AiReviewInboxView
      busy={busy}
      error={error}
      filter={filter}
      findings={filtered}
      identity={identity}
      loggingOut={loggingOut}
      onAccept={(finding) => review(finding, { decision: "accepted" }, "建议已接受；尚未写入业务对象")}
      onApply={(finding) => void apply(finding)}
      onEditAccept={(finding, editedPayload) => review(
        finding,
        { decision: "accepted", edited_payload: editedPayload },
        "修改后的建议已接受；尚未写入业务对象",
      )}
      onFilterChange={(next) => { setFilter(next); setSelectedId(null); }}
      onLogout={() => void logout()}
      onReject={(finding, reason) => review(
        finding,
        { decision: "rejected", comment: reason },
        "建议已拒绝，原因已记录",
      )}
      onSelect={setSelectedId}
      projects={projects}
      selected={selected}
      status={status}
    />
  );
}
