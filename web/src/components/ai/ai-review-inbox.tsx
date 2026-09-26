"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useFirstScreenSample } from "@/components/diagnostics/use-first-screen-sample";

import { requestProjectList } from "@/components/projects/project-api";
import type { Project } from "@/components/projects/project-types";
import { requestIdentity } from "@/components/workspace-api";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import {
  applyFinding,
  requestFindings,
  requestReviewInbox,
  requestInboxRiskCandidates,
  reviewFinding,
} from "./ai-api";
import { AiReviewInboxView, type FindingFilter } from "./ai-review-inbox-view";
import type { AiFinding, ReviewInboxDigest, RiskCandidate } from "./ai-types";
import { FindingReviewUndo } from "./finding-review-undo";
import { FindingBatchReview } from "./finding-batch-review";
import { ConversationFinding } from "./conversation-finding";
import { ReviewInboxExtras } from "./review-inbox-extras";

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
  const [lastReview, setLastReview] = useState<AiFinding | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<FindingFilter>("all");
  const [busy, setBusy] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [digest, setDigest] = useState<ReviewInboxDigest | null>(null);
  const [candidatesByProject, setCandidatesByProject] = useState<Record<string, RiskCandidate[]>>({});

  const [extrasState, setExtrasState] = useState<"loading" | "ready" | "error">("loading");
  const loadSequence = useRef(0);
  const extrasSequence = useRef(0);

  const loadExtras = useCallback(async (isActive: () => boolean = () => true) => {
    const sequence = ++extrasSequence.current;
    const isCurrent = () => isActive() && extrasSequence.current === sequence;
    setExtrasState("loading");
    try {
      const [nextDigest, candidates] = await Promise.all([
        requestReviewInbox(), requestInboxRiskCandidates(),
      ]);
      if (!isCurrent()) return;
      const grouped: Record<string, RiskCandidate[]> = {};
      for (const candidate of candidates) {
        (grouped[candidate.project_id] ??= []).push(candidate);
      }
      setDigest(nextDigest);
      setCandidatesByProject(grouped);
      setExtrasState("ready");
    } catch {
      if (isCurrent()) setExtrasState("error");
    }
  }, []);

  const load = useCallback(async (isActive: () => boolean = () => true) => {
    const sequence = ++loadSequence.current;
    const isCurrent = () => isActive() && loadSequence.current === sequence;
    extrasSequence.current += 1;
    setDigest(null);
    setCandidatesByProject({});
    setExtrasState("loading");
    try {
      const loadedIdentity = await requestIdentity();
      if (!isCurrent()) return;
      if (loadedIdentity === null) {
        setState("redirecting");
        replace("/login");
        return;
      }
      setIdentity(loadedIdentity);
      if (!internalRoles.has(loadedIdentity.user.role)) {
        setState("forbidden");
        return;
      }
      // All four scoped reads start after identity. Supplemental queues have
      // their own loading/error state and do not block reviewing a Finding.
      void loadExtras(isCurrent);
      const [loadedProjects, items] = await Promise.all([requestProjectList(), requestFindings()]);
      if (!isCurrent()) return;
      if (loadedProjects === null) {
        setState("redirecting");
        replace("/login");
        return;
      }
      setProjects(loadedProjects);
      setFindings(items);
      const deepLinkedId = new URLSearchParams(window.location.search).get("finding");
      setSelectedId(items.some((item) => item.id === deepLinkedId) ? deepLinkedId : items[0]?.id ?? null);
      setState("ready");
    } catch (loadError) {
      if (!isCurrent()) return;
      setError(messageFrom(loadError));
      setState("error");
    }
  }, [loadExtras, replace]);

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => { if (active) return load(() => active); });
    return () => { active = false; };
  }, [load]);

  const activeFindings = useMemo(
    () => findings.filter((finding) => finding.status !== "archived"),
    [findings],
  );
  const archivedFindings = useMemo(
    () => findings.filter((finding) => finding.status === "archived"),
    [findings],
  );
  const filtered = useMemo(
    () => activeFindings.filter((finding) => filter === "all" || finding.finding_type === filter),
    [filter, activeFindings],
  );
  const selected =
    filtered.find((finding) => finding.id === selectedId) ?? filtered[0] ?? null;

  useFirstScreenSample("review", state === "ready" && extrasState === "ready" ? "ready"
    : ["error", "forbidden", "redirecting"].includes(state) || extrasState === "error" ? "error" : "loading",
    { projects: projects.length, findings: findings.length, active: activeFindings.length, archived: archivedFindings.length });

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
      const reviewed = await reviewFinding(finding.id, payload);
      replaceFinding(reviewed, success);
      setLastReview(reviewed);
      return true;
    } catch (reviewError) {
      setError(messageFrom(reviewError));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function apply(finding: AiFinding) {
    setLastReview(null);
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

  const projectNames = Object.fromEntries([
    ...projects.map((project) => [project.id, project.name]),
    ...(digest?.groups.map((group) => [group.project_id, group.project_name]) ?? []),
  ]);

  return (
    <AiReviewInboxView
      busy={busy}
      error={error}
      extraSections={
        <div data-testid="review-extras" data-state={extrasState}>
          {lastReview && <FindingReviewUndo key={lastReview.updated_at} items={[lastReview]} onRecorded={result => { for (const item of result.items) replaceFinding(item, "已记录撤销裁决；建议当前状态已刷新。"); setLastReview(null); void loadExtras(); }}/>}
          <FindingBatchReview projectNames={projectNames} onRecorded={items => { setFindings(current => current.map(item => items.find(result => result.id === item.id) ?? item)); void loadExtras(); }}/>
          {archivedFindings.some(finding => finding.id === selectedId) && <section className="mt-4 space-y-2" aria-label="所选归档建议"><p className="text-sm">当前链接指向已归档建议，可查看原内容、历史或恢复。</p><ConversationFinding key={selectedId} findingId={selectedId!} onRecorded={finding => { replaceFinding(finding, "建议已恢复到待审队列，处理期重新起算。"); void loadExtras(); }}/></section>}
          {extrasState === "loading" ? <p className="mt-4 text-sm text-muted-foreground" aria-busy="true">正在加载候选与待办摘要…</p> : null}
          {extrasState === "error" ? (
            <div className="mt-4 rounded-lg border border-destructive/30 p-4" role="alert">
              <p className="text-sm text-destructive">候选与待办摘要暂不可用；尚未确认是否有待处理事项。</p>
              <button className="mt-2 min-h-11 rounded-lg border px-3 text-sm" onClick={() => void loadExtras()} type="button">重新加载候选与摘要</button>
            </div>
          ) : null}
          {digest !== null ? <ReviewInboxExtras
            actorKey={`${identity.tenant.id}:${identity.user.id}`}
          archived={archivedFindings}
          candidatesByProject={candidatesByProject}
          digest={digest}
          refreshing={extrasState !== "ready"}
          onNotice={({ status: nextStatus, error: nextError }) => {
            setStatus(nextStatus ?? null);
            setError(nextError ?? null);
          }}
          onRefresh={async () => {
            setFindings(await requestFindings());
            await loadExtras();
          }}
          projectNames={projectNames}
        /> : null}
        </div>
      }
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
