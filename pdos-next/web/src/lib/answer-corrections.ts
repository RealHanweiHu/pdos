import { defaultSearchPreferences, validSearchPreferences, type SearchPreferences } from "./search-preferences";
import type { ContinuationRequest, ContinuationSource } from "./run-continuation";

export type CorrectionWorkState = {
  version: "agent-work-state/v1"; session_id: string | null; revision: number;
  focus_objects: { id: string; kind: string; version: number | null; title?: string }[];
  citations?: { citation_id: string; title: string; source_revision: number }[];
  exclusions: { id: string; kind?: string; reason: string }[];
  search_preferences?: SearchPreferences;
  search_context?: { kind: string; scoped: boolean; label: string };
};
export type CorrectionContext = {
  root: string;
  run: { run_id: string; session_id: string; status: string; reverted: boolean; project_id?: string | null; proposal_id?: string | null; conversation?: { next_run_id: string | null } };
  workState: CorrectionWorkState;
};
export type CorrectionSource = { id: string; title: string; revision: number };
export type CorrectionContinuation = { kind: "continue"; path: string; body: ContinuationRequest & { search_preferences?: SearchPreferences } };
export type CorrectionExclusion = { kind: "exclude_source"; path: string; body: { expected_revision: number; request_key: string; action: "exclude_source"; item_id: string } };
export type AnswerCorrection = CorrectionContinuation | CorrectionExclusion;
export type CorrectionAction = { action: "supplement"; text: string; sources?: ContinuationSource[] } | { action: "same_category"; text?: string; sources?: ContinuationSource[] } | { action: "exclude_source"; sourceId: string };
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const exact = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).every(key => keys.includes(key));
export function canCorrectAnswer(context: CorrectionContext): boolean {
  return context.workState.version === "agent-work-state/v1" && uuid.test(context.run.run_id) && uuid.test(context.run.session_id)
    && context.workState.session_id === context.run.session_id
    && ["completed", "partial", "failed", "cancelled"].includes(context.run.status)
    && !context.run.reverted && !context.run.conversation?.next_run_id;
}
export function correctionSources(state: CorrectionWorkState): CorrectionSource[] {
  const excluded = new Set(state.exclusions.map(item => item.id));
  const values = [...(state.citations ?? []).map(item => ({ id: item.citation_id, title: item.title, revision: item.source_revision })),
    ...state.focus_objects.filter(item => item.kind === "artifact").map(item => ({ id: item.id, title: item.title || "所选资料", revision: item.version! }))];
  return values.filter((item, index) => uuid.test(item.id) && Number.isSafeInteger(item.revision) && item.revision > 0 && !excluded.has(item.id) && values.findIndex(other => other.id === item.id) === index);
}
export function canSearchSameCategory(context: CorrectionContext): boolean {
  return canCorrectAnswer(context) && !!(context.run.project_id || context.run.proposal_id)
    && context.workState.search_context?.scoped === true
    && ["project", "proposal"].includes(context.workState.search_context.kind);
}
function validSources(value: unknown): value is ContinuationSource[] {
  return Array.isArray(value) && value.every(item => record(item) && exact(item, ["artifact_id", "expected_revision"]) && Object.keys(item).length === 2 && uuid.test(String(item.artifact_id)) && Number.isSafeInteger(item.expected_revision) && Number(item.expected_revision) > 0) && new Set(value.map(item => item.artifact_id)).size === value.length;
}
function workStatePath(context: CorrectionContext): string {
  return `${context.root.replace(/agent-runs$/, "agent-sessions")}/${context.run.session_id}/work-state`;
}
/** Ordinary server requests only. The parent retains/replays these exact bodies in its existing journal. */
export function answerCorrection(context: CorrectionContext, action: CorrectionAction, key: string): AnswerCorrection {
  if (!["supplement", "same_category", "exclude_source"].includes(action.action)) throw new Error("当前操作尚未接入服务器条件。");
  if (!canCorrectAnswer(context) || !uuid.test(key) || !/^(v1\/(?:personal\/|categories\/[a-f0-9-]+\/)?)agent-runs$/i.test(context.root)) throw new Error("请从当前可继续的回答操作。");
  if (action.action === "exclude_source") {
    if ((!Number.isSafeInteger(context.workState.revision) || context.workState.revision < 1) || !correctionSources(context.workState).some(item => item.id === action.sourceId)) throw new Error("请先读取本次携带中的资料。");
    return { kind: "exclude_source", path: workStatePath(context), body: { expected_revision: context.workState.revision, request_key: key, action: "exclude_source", item_id: action.sourceId } };
  }
  if (action.action === "same_category" && !canSearchSameCategory(context)) throw new Error("请从当前项目或提案继续补查。");
  const goal = action.text?.trim() || (action.action === "same_category" ? "继续查找同品类历史，补充可参考的处理经验。" : "");
  if (!goal || goal.length > 8000 || action.sources !== undefined && !validSources(action.sources)) throw new Error("请填写补充条件并核对所选资料。");
  const preferences = context.workState.search_preferences ?? defaultSearchPreferences;
  return { kind: "continue", path: context.root, body: { goal, idempotency_key: key, continue_from_run_id: context.run.run_id,
    ...(action.sources?.length ? { sources: action.sources.map(item => ({ ...item })) } : {}),
    ...(action.action === "same_category" ? { search_preferences: { ...preferences, scope: "same_category" } } : {}),
  } };
}
/** Checks local replay shape and current session binding; this is never an authority proof. */
export function restoreAnswerCorrection(value: unknown, context: CorrectionContext): AnswerCorrection | null {
  if (!record(value) || !exact(value, ["kind", "path", "body"]) || Object.keys(value).length !== 3 || !record(value.body)) return null;
  const body = value.body;
  if (value.kind === "continue") {
    if (value.path !== context.root || !exact(body, ["goal", "idempotency_key", "continue_from_run_id", "sources", "search_preferences"])
      || body.continue_from_run_id !== context.run.run_id || typeof body.goal !== "string" || !body.goal.trim() || body.goal.length > 8000 || !uuid.test(String(body.idempotency_key))
      || body.sources !== undefined && !validSources(body.sources)
      || body.search_preferences !== undefined && (!validSearchPreferences(body.search_preferences) || body.search_preferences.scope !== "same_category")) return null;
  } else if (value.kind === "exclude_source") {
    if (value.path !== workStatePath(context) || !exact(body, ["expected_revision", "request_key", "action", "item_id"]) || Object.keys(body).length !== 4
      || body.action !== "exclude_source" || !Number.isSafeInteger(body.expected_revision) || Number(body.expected_revision) < 1 || !uuid.test(String(body.request_key)) || !uuid.test(String(body.item_id))) return null;
  } else return null;
  return JSON.parse(JSON.stringify(value)) as AnswerCorrection;
}
export function exclusionApplied(request: CorrectionExclusion, value: CorrectionWorkState, context: CorrectionContext): boolean {
  return value.version === "agent-work-state/v1" && value.session_id === context.run.session_id
    && value.revision > request.body.expected_revision && value.exclusions.some(item => item.id === request.body.item_id);
}
