/* 要我决定 · 小Pai 运行 (D78): the personal read and its strict parse. No runtime
   imports, so the shell's reminder count can use it without the candidate modules. */
import type { DomainCommand } from "@/lib/domain-candidate";

export type RunDecisionsApi = <T>(path: string, body?: unknown) => Promise<T>;
export type RunQuestion = { id: string; question: string; why: string; options: { value: string; label: string }[]; allow_free_text: boolean };
export type RunCandidate = {
  event_id: string; sequence: number; operation: string | null; write_tier: "T0" | "T1" | "T2" | null;
  kind: string | null; package: boolean; separate_reason: "separate_entry" | "named_decision" | null;
  command: DomainCommand | null; summary?: { title?: string; url?: string };
};
export type RunDecision = {
  run_id: string; goal: string; status: string; error_code: string | null; reading_token: string; created_at: string;
  scope: "category" | "personal"; category: { id: string; name: string } | null;
  product_id: string | null; proposal_id: string | null; project_id: string | null;
  questions: RunQuestion[]; question_sequence: number | null; needs_review: boolean;
  candidates: RunCandidate[]; more_candidates: boolean;
};
export type RunDecisionsPage = {
  version: "personal-run-decisions/v1"; principal_id: string; as_of: string; runs: RunDecision[];
  total_runs: number; candidate_count: number; question_count: number; truncated: boolean; unavailable_runs: number;
};

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
const timestamp = (value: unknown): value is string => typeof value === "string" && Number.isFinite(Date.parse(value));
const count = (value: unknown) => Number.isSafeInteger(value) && Number(value) >= 0;
function question(value: unknown): value is RunQuestion {
  return record(value) && typeof value.id === "string" && typeof value.question === "string" && !!value.question.trim()
    && typeof value.why === "string" && Array.isArray(value.options)
    && value.options.every(option => record(option) && typeof option.value === "string" && typeof option.label === "string")
    && typeof value.allow_free_text === "boolean";
}
function candidate(value: unknown, run: Record<string, unknown>): value is RunCandidate {
  if (!record(value) || !uuid(value.event_id) || !Number.isSafeInteger(value.sequence) || typeof value.package !== "boolean") return false;
  if (!(value.write_tier === null || ["T0", "T1", "T2"].includes(String(value.write_tier)))) return false;
  if (!value.package) return value.command === null;
  // A package item always carries its frozen command for this run and category.
  const command = value.command;
  const category = record(run.category) ? run.category.id : null;
  return record(command) && command.operation === value.operation && command.category_id === category
    && ["T0", "T1"].includes(String(value.write_tier)) && value.separate_reason === null && record(command.payload);
}
function run(value: unknown): value is RunDecision {
  if (!record(value) || !uuid(value.run_id) || typeof value.goal !== "string" || typeof value.status !== "string"
    || !timestamp(value.created_at) || !["category", "personal"].includes(String(value.scope))
    || !(value.category === null || record(value.category) && uuid(value.category.id) && typeof value.category.name === "string")
    || (value.scope === "category") !== (value.category !== null)
    || !Array.isArray(value.questions) || !value.questions.every(question)
    || !Array.isArray(value.candidates) || typeof value.needs_review !== "boolean" || typeof value.more_candidates !== "boolean") return false;
  const ids = value.candidates.map(item => record(item) ? item.event_id : null);
  return value.candidates.every(item => candidate(item, value)) && new Set(ids).size === ids.length;
}
/** A foreign, partial or malformed read never shows as "nothing to decide". */
export function parseRunDecisions(value: unknown, principalId: string): RunDecisionsPage {
  if (!record(value) || value.version !== "personal-run-decisions/v1" || value.principal_id !== principalId || !timestamp(value.as_of)
    || !Array.isArray(value.runs) || !value.runs.every(run) || !count(value.total_runs) || value.total_runs !== value.runs.length
    || !count(value.candidate_count) || !count(value.question_count) || typeof value.truncated !== "boolean" || !count(value.unavailable_runs)
    || new Set(value.runs.map(item => (item as RunDecision).run_id)).size !== value.runs.length) throw new Error("小Pai 运行的待决定事项未完整取得，不能显示为空。");
  const page = value as RunDecisionsPage;
  if (page.candidate_count !== page.runs.reduce((total, item) => total + item.candidates.length, 0)
    || page.question_count !== page.runs.reduce((total, item) => total + item.questions.length, 0)) throw new Error("小Pai 运行的待决定数量与明细不一致，请刷新。");
  return page;
}
export const runDecisionsPath = "v1/personal/run-decisions";
export const runTitle = (goal: string) => goal.split(/\n|【当前页面/)[0].trim() || "小Pai 运行";

/** Deep link into 要我决定 with one candidate version preselected (B8). */
export function decideHref(runId: string, eventId?: string) {
  const query = new URLSearchParams({ area: "work", decide: runId });
  if (eventId) query.set("candidate", eventId);
  return `/?${query}`;
}
export function decideTarget(search: string): { runId: string; eventId: string | null } | null {
  const params = new URLSearchParams(search);
  const runId = params.get("decide"), eventId = params.get("candidate");
  return uuid(runId) ? { runId, eventId: uuid(eventId) ? eventId : null } : null;
}
/** Default: every package item; a deep link to one version selects only that version. */
export function initialSelection(item: RunDecision, eventId: string | null): string[] {
  const eligible = item.candidates.filter(entry => entry.package).map(entry => entry.event_id);
  return eventId ? eligible.filter(id => id === eventId) : eligible;
}

