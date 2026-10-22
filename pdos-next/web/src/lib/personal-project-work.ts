"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type PersonalProjectWorkApi = <T>(path: string, body?: unknown) => Promise<T>;
export type PersonalWorkQueue = "receive" | "verify" | "tasks" | "commitments";
export type PersonalWorkItem = {
  id: string;
  category: { id: string; name: string };
  product: { id: string; name: string };
  project: { id: string; name: string };
  task: { id: string; version_id: string; revision: number; state: "proposed" | "assigned" | "accepted" | "in_progress" | "submitted" | "completed"; title: string };
  assignee: { id: string; name: string | null } | null;
  recipient: { id: string; name: string | null } | null;
  recorded_at: string;
  commitment: { id: string; revision: number; task_revision: number; promisor_id: string; recipient_id: string; outcome_keys: string[]; promised_at: string | null; original_timezone: string; calendar_id: string | null } | null;
  timing: "unknown" | "pending" | "overdue" | null;
};
export type PersonalWorkPage = { version: "personal-project-work/v1"; principal_id: string; as_of: string; queue: PersonalWorkQueue; total_records: number; items: PersonalWorkItem[]; next_cursor: string | null };
export type PersonalProjectWorkState = { status: "loading" | "ready" | "error"; items: PersonalWorkItem[]; totalRecords: number | null; asOf: string | null; nextCursor: string | null; error: string; loadingMore: boolean; moreError: string; loadMore: () => Promise<void>; retry: () => void };
type Stored = Omit<PersonalProjectWorkState, "loadMore" | "retry"> & { api: PersonalProjectWorkApi; principalId: string; reload: number; queue: PersonalWorkQueue; attempt: number; cursors: string[] };

const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string" && !!v.trim();
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(v);
const positive = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) > 0;
const timestamp = (v: unknown): v is string => typeof v === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const zone = (v: unknown): v is string => { if (!text(v)) return false; try { new Intl.DateTimeFormat("en", { timeZone: v }); return true; } catch { return false; } };
const named = (v: unknown) => record(v) && uuid(v.id) && text(v.name);
const person = (v: unknown) => v === null || (record(v) && uuid(v.id) && (v.name === null || text(v.name)));
const unique = (values: string[]) => new Set(values).size === values.length;
function item(v: unknown, queue: PersonalWorkQueue): v is PersonalWorkItem {
  if (!record(v) || !uuid(v.id) || !named(v.category) || !named(v.product) || !named(v.project) || !record(v.task) || !uuid(v.task.id) || !uuid(v.task.version_id) || !positive(v.task.revision) || !["proposed", "assigned", "accepted", "in_progress", "submitted", "completed"].includes(String(v.task.state)) || !text(v.task.title) || !person(v.assignee) || !person(v.recipient) || !timestamp(v.recorded_at) || !(v.timing === null || ["unknown", "pending", "overdue"].includes(String(v.timing)))) return false;
  const c = v.commitment;
  if (c !== null && (!record(c) || !uuid(c.id) || !positive(c.revision) || !positive(c.task_revision) || !uuid(c.promisor_id) || !uuid(c.recipient_id) || !Array.isArray(c.outcome_keys) || !c.outcome_keys.length || !c.outcome_keys.every(text) || !unique(c.outcome_keys) || !(c.promised_at === null || timestamp(c.promised_at)) || !zone(c.original_timezone) || !(c.calendar_id === null || uuid(c.calendar_id)))) return false;
  return queue === "commitments" ? record(c) && v.id === c.id : v.id === v.task.id;
}
export function parsePersonalProjectWork(value: unknown, principalId: string, queue: PersonalWorkQueue): PersonalWorkPage {
  if (!record(value) || value.version !== "personal-project-work/v1" || value.principal_id !== principalId || value.queue !== queue || !timestamp(value.as_of) || !Number.isSafeInteger(value.total_records) || Number(value.total_records) < 0 || !Array.isArray(value.items) || value.items.length > 20 || !value.items.every(v => item(v, queue)) || !unique(value.items.map(v => v.id)) || Number(value.total_records) < value.items.length || !(value.next_cursor === null || text(value.next_cursor))) throw new Error("个人项目队列资料未完整取得，不能显示为空或零。");
  return value as PersonalWorkPage;
}
export function personalProjectWorkPath(queue: PersonalWorkQueue, cursor?: string) { const query = new URLSearchParams({ queue, page_size: "20" }); if (cursor !== undefined) query.set("cursor", cursor); return `v1/personal/project-work?${query}`; }
const failureMessage = (failure: unknown) => failure instanceof Error ? failure.message : "队列读取失败，请重试。";
const denied = (failure: unknown) => record(failure) && [401, 403].includes(Number(failure.status));

export function usePersonalProjectWork(api: PersonalProjectWorkApi, principalId: string, reload: number, queue: PersonalWorkQueue): PersonalProjectWorkState {
  const [stored, setStored] = useState<Stored | null>(null), [attempt, setAttempt] = useState(0);
  const epoch = useRef(0), loading = useRef(false);
  const matches = (v: Stored | null) => v?.api === api && v.principalId === principalId && v.reload === reload && v.queue === queue && v.attempt === attempt;
  const current = matches(stored) ? stored : null;
  const base = useCallback((): Stored => ({ api, principalId, reload, queue, attempt, cursors: [], status: "loading", items: [], totalRecords: null, asOf: null, nextCursor: null, error: "", loadingMore: false, moreError: "" }), [api, principalId, reload, queue, attempt]);
  useEffect(() => {
    let active = true; const generation = ++epoch.current; loading.current = false;
    void Promise.resolve().then(async () => {
      if (!active) return;
      setStored(base());
      try { const page = parsePersonalProjectWork(await api<unknown>(personalProjectWorkPath(queue)), principalId, queue); if (active && generation === epoch.current) setStored({ ...base(), status: "ready", items: page.items, totalRecords: page.total_records, asOf: page.as_of, nextCursor: page.next_cursor }); }
      catch (failure) { if (active && generation === epoch.current) setStored({ ...base(), status: "error", error: failureMessage(failure) }); }
    });
    return () => { active = false; epoch.current = generation + 1; loading.current = false; };
  }, [api, principalId, reload, queue, base]);
  const loadMore = useCallback(async () => {
    if (!current || current.status !== "ready" || !current.nextCursor || loading.current) return;
    const cursor = current.nextCursor, generation = epoch.current; loading.current = true;
    setStored({ ...current, loadingMore: true, moreError: "" });
    try {
      const page = parsePersonalProjectWork(await api<unknown>(personalProjectWorkPath(queue, cursor)), principalId, queue);
      if (generation !== epoch.current) return;
      if ((page.next_cursor !== null && (page.next_cursor === cursor || current.cursors.includes(page.next_cursor))) || page.items.some(v => current.items.some(old => old.id === v.id))) throw new Error("分页返回了重复游标或记录，已保留原页，请刷新或重试。");
      const items = [...current.items, ...page.items];
      if (page.total_records < items.length) throw new Error("队列数量已变化，已保留原页，请刷新重读。");
      setStored({ ...current, status: "ready", items, totalRecords: page.total_records, asOf: page.as_of, nextCursor: page.next_cursor, cursors: [...current.cursors, cursor], loadingMore: false, moreError: "" });
    } catch (failure) {
      if (generation !== epoch.current) return;
      setStored(denied(failure) ? { ...base(), status: "error", error: failureMessage(failure) } : { ...current, loadingMore: false, moreError: failureMessage(failure) });
    } finally { if (generation === epoch.current) loading.current = false; }
  }, [api, principalId, queue, current, base]);
  const retry = useCallback(() => setAttempt(v => v + 1), []);
  return { status: current?.status ?? "loading", items: current?.items ?? [], totalRecords: current?.totalRecords ?? null, asOf: current?.asOf ?? null, nextCursor: current?.nextCursor ?? null, error: current?.error ?? "", loadingMore: current?.loadingMore ?? false, moreError: current?.moreError ?? "", loadMore, retry };
}
