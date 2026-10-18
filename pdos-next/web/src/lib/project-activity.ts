"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { projectWorkbenchHref } from "./global-navigation";
import { workRecord, workRoot, workUuid, type ProjectWorkApi, type WorkRef, type WorkScope } from "./project-work";

const destinations = {
  plan: ["projects", "plan", ""], build: ["projects", "builds", "prepare"], start: ["projects", "builds", "start"], execution: ["projects", "builds", "execution"], supply: ["projects", "builds", "supply"], cost: ["projects", "builds", "cost"],
  verification: ["projects", "verification", "prepare"], professional: ["projects", "verification", "request"], handoff: ["projects", "verification", "handoff"], launch: ["projects", "verification", "launch"], results: ["projects", "verification", "results"], quality: ["projects", "issues", ""],
  definition: ["products", "definition", ""], variants: ["products", "variants", ""], originals: ["projects", "files", ""], sources: ["knowledge", "sources", ""],
} as const;
export type ActivityView = keyof typeof destinations;
type ActivityCommon = {
  id: string; operation: string; event_type: string; recorded_at: string; occurred_at: string | null; original_timezone: string | null;
  subject: WorkRef & { kind: string; title: string | null };
  actor: { id: string; name: string | null; kind: "human" | "ai" | null }; requester: { id: string; name: string | null };
  summary: string; next_steps: string | null;
  sources: (WorkRef & { kind: string; position?: string })[]; task_refs: WorkRef[];
  link: { view: ActivityView; label: string } | null;
};
export const activityRunStates = { queued: "等待执行", running: "执行中", waiting_input: "待本人答复", completed: "已完成", partial: "部分结果", cancelled: "已取消", failed: "未完成" } as const;
const runEvents = { accepted: "小Pai 工作已受理", needs_input: "小Pai 工作等待本人答复", model_unavailable: "小Pai 模型服务暂不可用", reconciliation_required: "小Pai 原调用结果待核对", run_reconciled: "小Pai 原调用已核对", finished: "小Pai 工作已记录结果", run_state: "小Pai 工作状态已记录" } as const;
export type ProjectActivityItem = ActivityCommon & (
  { record_kind: "domain_receipt"; status: null; receipt_id: string; run_id: string | null }
  | { record_kind: "run_event"; status: keyof typeof activityRunStates | null; receipt_id: null; run_id: string }
);
export type ProjectActivityPage = { version: "project-activity/v1"; category_id: string; product_id: string; principal_id: string; project: WorkRef & { name: string }; as_of: string; items: ProjectActivityItem[]; next_cursor: string | null };
const text = (v: unknown): v is string => typeof v === "string" && !!v.trim();
const nullableText = (v: unknown): v is string | null => v === null || typeof v === "string";
const instant = (v: unknown): v is string => typeof v === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const positive = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) > 0;
const ref = (v: unknown): v is WorkRef & Record<string, unknown> => workRecord(v) && workUuid(v.id) && positive(v.revision);
const person = (v: unknown) => workRecord(v) && workUuid(v.id) && nullableText(v.name);
const unique = (values: string[]) => new Set(values).size === values.length;
const cursorValid = (v: unknown): v is string => typeof v === "string" && v.length > 0 && v.length <= 2048 && /^[A-Za-z0-9_-]+$/.test(v);
function item(v: unknown, scope: WorkScope): v is ProjectActivityItem {
  if (!(workRecord(v) && workUuid(v.id) && text(v.operation) && text(v.event_type) && instant(v.recorded_at) && (v.occurred_at === null || instant(v.occurred_at)) && nullableText(v.original_timezone)
    && ref(v.subject) && text(v.subject.kind) && nullableText(v.subject.title) && person(v.actor) && workRecord(v.actor) && [null, "human", "ai"].includes(v.actor.kind as null | "human" | "ai") && person(v.requester)
    && text(v.summary) && nullableText(v.next_steps)
    && Array.isArray(v.sources) && v.sources.every(row => ref(row) && text(row.kind) && (row.position === undefined || typeof row.position === "string"))
    && Array.isArray(v.task_refs) && v.task_refs.every(ref) && unique(v.task_refs.map(row => `${row.id}:${row.revision}`))
    && (v.link === null || (workRecord(v.link) && typeof v.link.view === "string" && Object.hasOwn(destinations, v.link.view) && text(v.link.label))))) return false;
  if (v.record_kind === "domain_receipt") return workUuid(v.receipt_id) && (v.run_id === null || workUuid(v.run_id)) && v.status === null && v.operation !== "agent.run.record" && !v.event_type.startsWith("agent.run.") && v.subject.kind !== "agent_run";
  if (v.record_kind !== "run_event") return false;
  const event = v.event_type.slice("agent.run.".length);
  return v.operation === "agent.run.record" && v.event_type.startsWith("agent.run.") && Object.hasOwn(runEvents, event) && v.summary === runEvents[event as keyof typeof runEvents]
    && v.receipt_id === null && workUuid(v.run_id) && v.subject.id === v.run_id && v.subject.kind === "agent_run" && v.subject.title === null
    && workRecord(v.requester) && v.requester.id === scope.principalId && instant(v.occurred_at) && v.occurred_at === v.recorded_at && v.original_timezone === null
    && v.next_steps === null && v.sources.length === 0 && v.task_refs.length === 0 && v.link === null && (v.status === null || (typeof v.status === "string" && Object.hasOwn(activityRunStates, v.status)))
    && Object.keys(v).every(key => ["id", "record_kind", "status", "operation", "event_type", "recorded_at", "occurred_at", "original_timezone", "subject", "actor", "requester", "summary", "next_steps", "receipt_id", "run_id", "sources", "task_refs", "link"].includes(key));
}
export function parseProjectActivity(value: unknown, scope: WorkScope): ProjectActivityPage {
  if (!workRecord(value) || value.version !== "project-activity/v1" || value.category_id !== scope.categoryId || value.product_id !== scope.productId || value.principal_id !== scope.principalId || !ref(value.project) || value.project.id !== scope.projectId || !text(value.project.name) || !instant(value.as_of) || !Array.isArray(value.items) || value.items.length > 20 || !value.items.every(row => item(row, scope)) || !unique(value.items.map(row => row.id)) || !unique(value.items.flatMap(row => row.receipt_id === null ? [] : [row.receipt_id])) || value.items.some(row => Date.parse(row.recorded_at) > Date.parse(value.as_of as string)) || !(value.next_cursor === null || cursorValid(value.next_cursor)) || (value.next_cursor !== null && value.items.length === 0)) throw new Error("项目动态资料未完整取得，请刷新后重试。");
  return value as ProjectActivityPage;
}
export function projectActivityPath(scope: WorkScope, cursor?: string) {
  const query = new URLSearchParams({ project_id: scope.projectId, page_size: "20" });
  if (cursor !== undefined) { if (!cursorValid(cursor)) throw new Error("分页游标不完整，请刷新项目动态。"); query.set("cursor", cursor); }
  return `${workRoot(scope)}/project-work/activity?${query}`;
}
export function projectActivityHref(scope: WorkScope, view: ActivityView) {
  const [bench, section, task] = destinations[view], query = new URLSearchParams(projectWorkbenchHref(scope.categoryId, scope.productId, scope.projectId));
  query.set("bench", bench); query.set("view", section);
  if (task) query.set("task", task); else query.delete("task");
  return `?${query}`;
}
type Stored = { api: ProjectWorkApi; binding: string; status: "loading" | "ready" | "error"; page: ProjectActivityPage | null; error: string; moreError: string; loadingMore: boolean; cursors: string[] };
const failureMessage = (failure: unknown) => failure instanceof Error ? failure.message : "项目动态读取失败，请重试。";
const denied = (failure: unknown) => workRecord(failure) && [401, 403].includes(Number(failure.status));
export function useProjectActivity(api: ProjectWorkApi, scope: WorkScope, readVersion = 0) {
  const { categoryId, productId, projectId, principalId } = scope;
  const [stored, setStored] = useState<Stored | null>(null), [attempt, setAttempt] = useState(0);
  const epoch = useRef(0), loading = useRef(false);
  const binding = JSON.stringify([categoryId, productId, projectId, principalId, readVersion, attempt]);
  const current = stored?.api === api && stored.binding === binding ? stored : null;
  const base = useCallback((): Stored => ({ api, binding, status: "loading", page: null, error: "", moreError: "", loadingMore: false, cursors: [] }), [api, binding]);
  useEffect(() => {
    let active = true; const generation = ++epoch.current; loading.current = false;
    const requestScope = { categoryId, productId, projectId, principalId };
    void Promise.resolve().then(async () => {
      if (!active) return;
      setStored(base());
      try { const page = parseProjectActivity(await api<unknown>(projectActivityPath(requestScope)), requestScope); if (active && generation === epoch.current) setStored({ ...base(), status: "ready", page }); }
      catch (failure) { if (active && generation === epoch.current) setStored({ ...base(), status: "error", error: failureMessage(failure) }); }
    });
    return () => { active = false; epoch.current = generation + 1; loading.current = false; };
  }, [api, categoryId, productId, projectId, principalId, base]);
  const loadMore = useCallback(async () => {
    if (!current?.page || current.status !== "ready" || !current.page.next_cursor || loading.current) return;
    const previous = current.page, cursor = previous.next_cursor!, generation = epoch.current;
    loading.current = true; setStored({ ...current, loadingMore: true, moreError: "" });
    try {
      const requestScope = { categoryId, productId, projectId, principalId };
      const page = parseProjectActivity(await api<unknown>(projectActivityPath(requestScope, cursor)), requestScope);
      if (generation !== epoch.current) return;
      if (page.as_of !== previous.as_of || (page.next_cursor !== null && [cursor, ...current.cursors].includes(page.next_cursor)) || page.items.some(row => previous.items.some(old => row.id === old.id || (row.receipt_id !== null && row.receipt_id === old.receipt_id)))) throw new Error("分页记录或读取时点不一致，已保留原页，请刷新或重试。");
      setStored({ ...current, page: { ...page, items: [...previous.items, ...page.items] }, cursors: [...current.cursors, cursor], loadingMore: false, moreError: "" });
    } catch (failure) {
      if (generation === epoch.current) setStored(denied(failure) ? { ...base(), status: "error", error: "项目访问已失效，已清除已读取的动态。" } : { ...current, loadingMore: false, moreError: failureMessage(failure) });
    } finally { if (generation === epoch.current) loading.current = false; }
  }, [api, categoryId, productId, projectId, principalId, current, base]);
  const refresh = useCallback(() => setAttempt(value => value + 1), []);
  return { status: current?.status ?? "loading", page: current?.page ?? null, error: current?.error ?? "", moreError: current?.moreError ?? "", loadingMore: current?.loadingMore ?? false, loadMore, refresh };
}
