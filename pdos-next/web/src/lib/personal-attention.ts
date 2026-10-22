"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type PersonalAttentionApi = <T>(path: string, body?: unknown) => Promise<T>;
export type AttentionQueue = "decide" | "receive" | "verify" | "external";
type Named = { id: string; name: string };
export type AttentionDetail = string | number | boolean | null | AttentionDetail[] | { [key: string]: AttentionDetail };
export type PersonalAttentionItem = {
  id: string; kind: string; queue: AttentionQueue;
  source: { id: string; version_id: string | null; revision: number | null; epoch: number | null };
  category: Named; product: Named | null; project: Named | null;
  title: string; reason: string; state: string;
  responsible: { id: string; name: string | null }; responsibility: string;
  recorded_at: string; due_at: string | null; valid_until: string | null;
  blocked: { code: string; message: string } | null;
  target: "proposal" | "project"; details: { [key: string]: AttentionDetail };
};
export type PersonalAttentionPage = {
  version: "personal-attention/v1"; principal_id: string; queue: AttentionQueue;
  items: PersonalAttentionItem[]; total_records: number; next_cursor: string | null; as_of: string;
};
export type PersonalAttentionState = {
  status: "loading" | "ready" | "error"; items: PersonalAttentionItem[]; totalRecords: number | null;
  asOf: string | null; nextCursor: string | null; error: string; loadingMore: boolean; moreError: string;
  loadMore: () => Promise<void>; retry: () => void;
};
type Stored = Omit<PersonalAttentionState, "loadMore" | "retry"> & {
  api: PersonalAttentionApi; principalId: string; reload: number; queue: AttentionQueue; attempt: number; cursors: string[];
};
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && !!value.trim();
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
const positive = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
const timestamp = (value: unknown): value is string => typeof value === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const cursorValue = (value: unknown): value is string => typeof value === "string" && /^[A-Za-z0-9_-]{1,2048}$/.test(value);
const named = (value: unknown) => record(value) && uuid(value.id) && text(value.name);
const unique = (values: string[]) => new Set(values).size === values.length;
function detail(value: unknown, depth = 0): boolean {
  if (value === null || typeof value === "boolean") return true;
  if (typeof value === "string") return value.length <= 2048;
  if (typeof value === "number") return Number.isFinite(value);
  if (depth >= 3) return false;
  if (Array.isArray(value)) return value.length <= 40 && value.every(entry => detail(entry, depth + 1));
  return record(value) && Object.keys(value).length <= 40 && Object.entries(value).every(([key, entry]) => /^[a-z][a-z0-9_]{0,79}$/.test(key) && detail(entry, depth + 1));
}
function item(value: unknown, principalId: string, queue: AttentionQueue): value is PersonalAttentionItem {
  if (!record(value) || !text(value.kind) || !/^[a-z][a-z0-9_]*$/.test(value.kind) || value.kind.length > 80 || value.queue !== queue
    || !record(value.source) || !uuid(value.source.id) || value.id !== `${value.kind}:${value.source.id}`
    || !(value.source.version_id === null || uuid(value.source.version_id)) || !(value.source.revision === null || positive(value.source.revision)) || !(value.source.epoch === null || positive(value.source.epoch))
    || !named(value.category) || !(value.product === null || named(value.product)) || !(value.project === null || named(value.project))
    || !text(value.title) || !text(value.reason) || !text(value.state) || !text(value.responsibility)
    || !record(value.responsible) || value.responsible.id !== principalId || !(value.responsible.name === null || text(value.responsible.name))
    || !timestamp(value.recorded_at) || !(value.due_at === null || timestamp(value.due_at)) || !(value.valid_until === null || timestamp(value.valid_until))
    || !(value.blocked === null || (record(value.blocked) && text(value.blocked.code) && text(value.blocked.message)))
    || !["proposal", "project"].includes(String(value.target)) || (value.target === "project" && (!named(value.product) || !named(value.project)))
    || !record(value.details) || !detail(value.details)) return false;
  return true;
}
/** Reject an incomplete or foreign read; neither means an empty personal queue. */
export function parsePersonalAttention(value: unknown, principalId: string, queue: AttentionQueue): PersonalAttentionPage {
  if (!uuid(principalId) || !record(value) || value.version !== "personal-attention/v1" || value.principal_id !== principalId || value.queue !== queue
    || !timestamp(value.as_of) || !Number.isSafeInteger(value.total_records) || Number(value.total_records) < 0
    || !Array.isArray(value.items) || value.items.length > 20 || !value.items.every(entry => item(entry, principalId, queue))
    || !unique(value.items.map(entry => entry.id)) || Number(value.total_records) < value.items.length
    || !(value.next_cursor === null || cursorValue(value.next_cursor))) throw new Error("个人注意项资料未完整取得，不能显示为空或零。");
  return value as PersonalAttentionPage;
}
export function personalAttentionPath(queue: AttentionQueue, cursor?: string) {
  const query = new URLSearchParams({ queue, page_size: "20" });
  if (cursor !== undefined) query.set("cursor", cursor);
  return `v1/personal/attention?${query}`;
}
/** Navigation only. Original domain pages recheck authority and current versions. */
export function personalAttentionHref(value: PersonalAttentionItem) {
  if (value.target === "proposal") return `/categories/${encodeURIComponent(value.category.id)}/proposals/${encodeURIComponent(value.source.id)}`;
  if (!value.project) return null;
  return `/?${new URLSearchParams({ area: "cockpit", category: value.category.id, project: value.project.id })}`;
}
const failureMessage = (failure: unknown) => failure instanceof Error ? failure.message : "注意项读取失败，请重试。";
const denied = (failure: unknown) => record(failure) && [401, 403].includes(Number(failure.status));

export function usePersonalAttention(api: PersonalAttentionApi, principalId: string, reload: number, queue: AttentionQueue): PersonalAttentionState {
  const [stored, setStored] = useState<Stored | null>(null), [attempt, setAttempt] = useState(0);
  const epoch = useRef(0), loading = useRef(false);
  const matches = (value: Stored | null) => value?.api === api && value.principalId === principalId && value.reload === reload && value.queue === queue && value.attempt === attempt;
  const current = matches(stored) ? stored : null;
  const base = useCallback((): Stored => ({ api, principalId, reload, queue, attempt, cursors: [], status: "loading", items: [], totalRecords: null, asOf: null, nextCursor: null, error: "", loadingMore: false, moreError: "" }), [api, principalId, reload, queue, attempt]);
  useEffect(() => {
    let active = true; const generation = ++epoch.current; loading.current = false;
    void Promise.resolve().then(async () => {
      if (!active) return;
      setStored(base());
      try {
        const page = parsePersonalAttention(await api<unknown>(personalAttentionPath(queue)), principalId, queue);
        if (active && generation === epoch.current) setStored({ ...base(), status: "ready", items: page.items, totalRecords: page.total_records, asOf: page.as_of, nextCursor: page.next_cursor });
      } catch (failure) { if (active && generation === epoch.current) setStored({ ...base(), status: "error", error: failureMessage(failure) }); }
    });
    return () => { active = false; epoch.current = generation + 1; loading.current = false; };
  }, [api, principalId, reload, queue, base]);
  const loadMore = useCallback(async () => {
    if (!current || current.status !== "ready" || !current.nextCursor || loading.current) return;
    const cursor = current.nextCursor, generation = epoch.current; loading.current = true;
    setStored({ ...current, loadingMore: true, moreError: "" });
    try {
      const page = parsePersonalAttention(await api<unknown>(personalAttentionPath(queue, cursor)), principalId, queue);
      if (generation !== epoch.current) return;
      if ((page.next_cursor !== null && (page.next_cursor === cursor || current.cursors.includes(page.next_cursor))) || page.items.some(entry => current.items.some(previous => previous.id === entry.id))) throw new Error("分页返回了重复游标或记录，已保留原页，请刷新或重试。");
      const items = [...current.items, ...page.items];
      if (page.total_records < items.length) throw new Error("注意项已变化，已保留原页，请刷新重读。");
      setStored({ ...current, status: "ready", items, totalRecords: page.total_records, asOf: page.as_of, nextCursor: page.next_cursor, cursors: [...current.cursors, cursor], loadingMore: false, moreError: "" });
    } catch (failure) {
      if (generation !== epoch.current) return;
      setStored(denied(failure) ? { ...base(), status: "error", error: failureMessage(failure) } : { ...current, loadingMore: false, moreError: failureMessage(failure) });
    } finally { if (generation === epoch.current) loading.current = false; }
  }, [api, principalId, queue, current, base]);
  const retry = useCallback(() => setAttempt(value => value + 1), []);
  return { status: current?.status ?? "loading", items: current?.items ?? [], totalRecords: current?.totalRecords ?? null, asOf: current?.asOf ?? null, nextCursor: current?.nextCursor ?? null, error: current?.error ?? "", loadingMore: current?.loadingMore ?? false, moreError: current?.moreError ?? "", loadMore, retry };
}
