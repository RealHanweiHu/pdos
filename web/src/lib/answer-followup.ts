import type { CorrectionWorkState } from "./answer-corrections";
import { restoreContinuation, type ContinuationRequest } from "./run-continuation";
import type { WorkspaceTransport } from "./workspace-api";
export type FeedbackSource = { selection_id: string; source_type: string; source_id: string };
export type AnswerExclusions = { run_id: string; state: CorrectionWorkState; feedbacks: FeedbackSource[] };
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
/** Private event metadata supplies exact identity mapping only; it grants no read/write authority. */
export async function readExclusionSources(api: WorkspaceTransport, root: string, runId: string): Promise<FeedbackSource[]> {
  const values: FeedbackSource[] = [];
  let after = 0;
  for (;;) {
    const page = await api<{ items: { event: unknown }[]; next_cursor: number }>(`${root}/${runId}/events?after=${after}&page_size=200`);
    for (const row of page.items) {
      const value = row.event;
      if (!object(value) || value.type !== "retrieval_feedback" || value.version !== "retrieval-feedback/v1" || value.action !== "not_relevant" || !object(value.selection) || !object(value.source)) continue;
      if (uuid.test(String(value.selection.id)) && typeof value.source.source_type === "string" && uuid.test(String(value.source.source_id))) values.push({ selection_id: String(value.selection.id), source_type: value.source.source_type, source_id: String(value.source.source_id) });
    }
    if (page.items.length < 200 || page.next_cursor <= after) return values;
    after = page.next_cursor;
  }
}
/** Presentation only: keep original cells, citations and source order; only choose collapsed cards/rows. */
export function collapsedAnswerCitations(answer: unknown, snapshot: AnswerExclusions | null, runId: string): string[] {
  if (!snapshot || snapshot.run_id !== runId || !object(answer) || !Array.isArray(answer.sources)) return [];
  const excluded = snapshot.state.exclusions;
  return answer.sources.filter(object).filter(source => excluded.some(entry =>
    entry.kind === "artifact" && source.source_type === "artifact" && source.source_id === entry.id
    || source.citation_id === entry.id
    || snapshot.feedbacks.some(item => item.selection_id === entry.id && item.source_type === source.source_type && item.source_id === source.source_id)
  )).map(source => String(source.citation_id)).filter(value => uuid.test(value));
}
export function deeperLookupRequest(runId: string, goal: string, key: string, sources: ContinuationRequest["sources"] = []): ContinuationRequest {
  if (!uuid.test(runId) || !uuid.test(key)) throw new Error("请从当前回答继续查找。");
  const text = goal.trim() || "沿用当前问题继续深入查找，核对更多来源，并保留尚未确认的信息。";
  if (text.length > 8000) throw new Error("请简短说明接下来要深入查什么。");
  const request: ContinuationRequest = { goal: text, idempotency_key: key, continue_from_run_id: runId, lookup_depth: "deep", ...(sources?.length ? { sources: sources.map(item => ({ ...item })) } : {}) };
  if (!restoreContinuation({ root: "v1/agent-runs", owner_id: "local-deep", request }, "v1/agent-runs", "local-deep", runId)) throw new Error("请核对所选资料的固定版本。");
  return request;
}
