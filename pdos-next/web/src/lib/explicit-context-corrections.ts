import { canCorrectAnswer, type CorrectionContext, type CorrectionWorkState } from "./answer-corrections";
import type { ContinuationRequest } from "./run-continuation";

export type ContextOption = { source_type: string; source_id: string; object_id: string; source_revision: number; title: string; is_current: boolean };
export type ContextChoice = { source_type: string; source_id: string; expected_revision: number };
export type ExplicitCorrectionKind = "replace_focus" | "fixed_versions" | "current_only" | "limit_sources" | "clear";
export type ContextSelectionSource = { source_type: string; source_id: string; source_revision: number; title: string };
export type ContextSelection = { version: 1; status: "available" | "unavailable"; focus: ContextSelectionSource | null; version_mode: "any" | "current" | "fixed"; versions: ContextSelectionSource[]; sources: ContextSelectionSource[] | null };
export type ExplicitWorkState = CorrectionWorkState & { context_selection?: ContextSelection };
export type ExplicitCorrectionRequest = { path: string; body: { expected_revision: number; request_key: string; action: "correct_context"; context_change: { kind: ExplicitCorrectionKind; sources: ContextChoice[] } }; continuation: ContinuationRequest };
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const kinds = ["artifact", "knowledge", "issue", "capa", "change", "external_wait", "supply", "build", "test_run", "field_feedback", "project_status", "manufacturing_document", "verification_handoff"];

export function contextStatePath(context: CorrectionContext): string {
  return `${context.root.replace(/agent-runs$/, "agent-sessions")}/${context.run.session_id}/work-state`;
}
export function contextOptionsPath(context: CorrectionContext, query: string, objectId?: string): string {
  if (!canCorrectAnswer(context) || query.length > 120 || objectId !== undefined && !uuid.test(objectId)) throw new Error("请从当前会话选择资料。");
  const params = new URLSearchParams(objectId ? { object_id: objectId } : { query: query.trim() });
  return `${contextStatePath(context)}/context-options?${params}`;
}
export function explicitCorrection(context: CorrectionContext, kind: ExplicitCorrectionKind, selected: ContextOption[], key: string, continuationKey: string): ExplicitCorrectionRequest {
  if (!canCorrectAnswer(context) || !uuid.test(key) || !uuid.test(continuationKey) || !["replace_focus", "fixed_versions", "current_only", "limit_sources", "clear"].includes(kind)) throw new Error("请从当前回答纠正。");
  const sources = selected.map(row => ({ source_type: row.source_type, source_id: row.source_id, expected_revision: row.source_revision }));
  if (sources.length > 50 || sources.some(row => !kinds.includes(row.source_type) || !uuid.test(row.source_id) || !Number.isSafeInteger(row.expected_revision) || row.expected_revision < 1)
    || new Set(sources.map(row => `${row.source_type}:${row.source_id}`)).size !== sources.length
    || ["current_only", "clear"].includes(kind) && sources.length !== 0
    || !["current_only", "clear"].includes(kind) && sources.length === 0 || kind === "replace_focus" && sources.length !== 1) throw new Error("请选择要核对的实际对象或版本。");
  return { path: contextStatePath(context), body: { expected_revision: context.workState.revision, request_key: key, action: "correct_context", context_change: { kind, sources } },
    continuation: { goal: kind === "clear" ? "解除资料限定，按当前问题重新核对。" : "按照这次选定的对象与资料条件，重新核对当前问题。", idempotency_key: continuationKey, continue_from_run_id: context.run.run_id } };
}
/** A replay response is historical. Always compare the latest read before continuing. */
export function correctionSaved(request: ExplicitCorrectionRequest, state: ExplicitWorkState, context: CorrectionContext): boolean {
  if (state.version !== "agent-work-state/v1" || state.session_id !== context.run.session_id || state.revision <= request.body.expected_revision) return false;
  const selection = state.context_selection;
  if (request.body.context_change.kind === "clear") return selection === undefined;
  if (!selection || selection.version !== 1 || selection.status !== "available") return false;
  if (request.body.context_change.kind === "current_only") return selection.version_mode === "current";
  // The full fixed identities are supplied by the server; titles never establish a match.
  const rows = (request.body.context_change.kind === "replace_focus" ? [selection.focus] : request.body.context_change.kind === "fixed_versions" ? selection.versions : selection.sources);
  return !!rows && rows.length === request.body.context_change.sources.length && request.body.context_change.sources.every(ref => rows.some(row => row?.source_type === ref.source_type && row.source_id === ref.source_id && row.source_revision === ref.expected_revision));
}
