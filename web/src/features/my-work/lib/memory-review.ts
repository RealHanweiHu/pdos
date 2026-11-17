/* 我的工作 · 要我复核（记忆 M3, P88; memory design §14.9; D508): review items assigned to
   me (corrections routed to me, 待复核 flags after an object revision, hand-overs after an
   author left) and the routes I raised from my own corrections. Nothing changes until the
   assignee acts; adopting a personal card writes it as a note through the owner's own
   "我的记忆" path, a team card is saved through scope_note.save on the team memo. */
import { useCallback, useEffect, useState } from "react";

export const memoryReviewPath = "v1/personal/memory/review-items";
export type MemoryReviewApi = <T>(path: string, body?: unknown) => Promise<T>;

export type ReviewKind = "fact" | "skill" | "personal" | "team" | "object_updated" | "author_departed";
export type ReviewItem = {
  item_id: string;
  source: "correction" | "staleness" | "departure";
  kind: ReviewKind;
  label: string;
  status: "open" | "adopted" | "forwarded" | "dismissed" | "resolved";
  choices: string[];
  text: string | null;
  proposed_kind: string | null;
  recorded_at: string;
  parent_id: string | null;
  run_id: string | null;
  reasons: string[];
  scope: { kind: string; id: string | null; category_id: string | null };
  object?: { kind: string; id: string; title: string | null; recorded_version: number | null; current_version: number | null };
  target?: { kind: string; key: string; version: string };
  note?: { kind: "scope_note" | "personal_note"; id: string; revision: number };
};
export type ReviewPage = { items: ReviewItem[]; raised: ReviewItem[]; count: number; note: string };

const kinds = new Set<ReviewKind>(["fact", "skill", "personal", "team", "object_updated", "author_departed"]);
const statuses = new Set(["open", "adopted", "forwarded", "dismissed", "resolved"]);
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isItem(value: unknown): value is ReviewItem {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.item_id === "string" && uuid.test(item.item_id)
    && kinds.has(item.kind as ReviewKind) && typeof item.label === "string"
    && statuses.has(item.status as string) && Array.isArray(item.choices)
    && item.choices.every(choice => typeof choice === "string")
    && (item.text === null || typeof item.text === "string")
    && typeof item.recorded_at === "string";
}

export function parseReviewPage(value: unknown): ReviewPage | null {
  if (!value || typeof value !== "object") return null;
  const page = value as Record<string, unknown>;
  if (page.version !== "memory-review-items/v1" || !Array.isArray(page.items) || !Array.isArray(page.raised)) return null;
  if (!page.items.every(isItem) || !page.raised.every(isItem)) return null;
  return { items: page.items, raised: page.raised, count: page.items.length, note: typeof page.note === "string" ? page.note : "" };
}

export const reviewDecisionPath = (itemId: string) => `${memoryReviewPath}/${itemId}/decision`;
export const reviewRoutePath = (itemId: string) => `${memoryReviewPath}/${itemId}/routes`;

export const decisionLabels: Record<string, string> = {
  adopted: "记下", resolved: "已处理", dismissed: "不处理", forwarded: "已转交",
};
export const proposedKindLabels: Record<string, string> = {
  convention: "约定 / 口径", background: "背景", concern: "关注点", decision_context: "决策背景", observation: "观察",
};

/** Which further routes a person may still add to their own correction. */
export function routeChoices(item: ReviewItem): ("personal" | "team" | "forward")[] {
  if (item.source !== "correction" || item.parent_id) return [];
  const choices: ("personal" | "team" | "forward")[] = ["personal"];
  if (item.scope.kind !== "global") choices.push("team");
  if (item.kind === "fact" && item.status === "open" && item.object) choices.push("forward");
  return choices;
}

export function requestKey() {
  return globalThis.crypto.randomUUID();
}

function message(failure: unknown) {
  return failure instanceof Error && failure.message ? failure.message : "记忆复核暂不可用。";
}

export type MemoryReviewState = { status: "loading" | "ready" | "error"; page: ReviewPage | null; error: string; retry: () => void };

export function useMemoryReview(api: MemoryReviewApi, principalId: string, reload: number): MemoryReviewState {
  const [attempt, setAttempt] = useState(0);
  const scope = JSON.stringify([principalId, reload, attempt]);
  const [stored, setStored] = useState<{ scope: string; api: MemoryReviewApi; page: ReviewPage | null; error: string } | null>(null);
  useEffect(() => {
    let live = true;
    api<unknown>(memoryReviewPath).then(value => {
      if (!live) return;
      const page = parseReviewPage(value);
      setStored({ scope, api, page, error: page ? "" : "记忆复核的返回格式无法识别。" });
    }).catch(failure => { if (live) setStored({ scope, api, page: null, error: message(failure) }); });
    return () => { live = false; };
  }, [api, scope]);
  const retry = useCallback(() => setAttempt(value => value + 1), []);
  const current = stored?.scope === scope && stored.api === api ? stored : null;
  return { status: !current ? "loading" : current.error ? "error" : "ready", page: current?.page ?? null, error: current?.error ?? "", retry };
}
