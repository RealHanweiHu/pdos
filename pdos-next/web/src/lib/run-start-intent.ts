import { validWorkFollowupAction, type WorkFollowupAction } from "./work-followup";
import { restoreContinuation } from "./run-continuation";
import { validVerificationAction, type VerificationAction } from "./verification-action";
import { validSearchPreferences, type SearchPreferences } from "./search-preferences";
export type RequestedSkill = { key: string; version: string; digest: string };
type Start = { goal: string; idempotency_key: string; product_id?: string | null; continue_from_run_id?: string; verification_action?: VerificationAction; work_followup_action?: WorkFollowupAction; proposal_id?: string; project_id?: string; sources?: { artifact_id: string; expected_revision: number }[]; lookup_depth?: "deep"; context_revision?: number; requested_skills?: RequestedSkill[]; search_preferences?: SearchPreferences };
export type RunStartIntent = { path: "v1/agent-runs"; body: Start };
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
/** Restore only an original start in this exact proposal scope, never an arbitrary POST. */
export function restoreRunStart(value: unknown, proposalId?: string, projectId?: string): RunStartIntent | null {
  if (!record(value) || Object.keys(value).some(key => !["path", "body"].includes(key)) || value.path !== "v1/agent-runs" || !record(value.body)) return null;
  const body = value.body;
  if (body.work_followup_action !== undefined) {
    if (Object.keys(body).some(key => !["goal", "idempotency_key", "continue_from_run_id", "sources", "work_followup_action"].includes(key))
      || proposalId !== undefined || !projectId || !validWorkFollowupAction(body.work_followup_action)
      || body.work_followup_action.project_id !== projectId
      || typeof body.continue_from_run_id !== "string" || !uuid.test(body.continue_from_run_id)
      || typeof body.goal !== "string" || !body.goal.trim() || body.goal.length > 8000
      || typeof body.idempotency_key !== "string" || body.idempotency_key.length < 8 || body.idempotency_key.length > 160
      || !Array.isArray(body.sources) || body.sources.length < 1 || body.sources.some(source => !record(source)
        || Object.keys(source).some(key => !["artifact_id", "expected_revision"].includes(key))
        || typeof source.artifact_id !== "string" || !uuid.test(source.artifact_id)
        || !Number.isSafeInteger(source.expected_revision) || Number(source.expected_revision) < 1)) return null;
    return value as RunStartIntent;
  }
  if (body.verification_action !== undefined) {
    if (Object.keys(body).some(key => !["goal", "idempotency_key", "continue_from_run_id", "sources", "verification_action"].includes(key))
      || proposalId !== undefined || !projectId || !validVerificationAction(body.verification_action)
      || body.verification_action.selection.project_id !== projectId
      || typeof body.continue_from_run_id !== "string" || !uuid.test(body.continue_from_run_id)
      || typeof body.goal !== "string" || !body.goal.trim() || body.goal.length > 8000
      || typeof body.idempotency_key !== "string" || body.idempotency_key.length < 8 || body.idempotency_key.length > 160
      || !Array.isArray(body.sources) || body.sources.some(source => !record(source)
        || Object.keys(source).some(key => !["artifact_id", "expected_revision"].includes(key))
        || typeof source.artifact_id !== "string" || !uuid.test(source.artifact_id)
        || !Number.isSafeInteger(source.expected_revision) || Number(source.expected_revision) < 1)) return null;
    return value as RunStartIntent;
  }
  if (body.continue_from_run_id !== undefined) {
    if (typeof body.continue_from_run_id !== "string" || !uuid.test(body.continue_from_run_id)
      || !restoreContinuation({ root: "v1/agent-runs", owner_id: "local-start", request: body }, "v1/agent-runs", "local-start", body.continue_from_run_id)) return null;
    return value as RunStartIntent;
  }
  if (Object.keys(body).some(key => !["goal", "idempotency_key", "product_id", "proposal_id", "project_id", "sources", "requested_skills", "search_preferences"].includes(key))
    || body.search_preferences !== undefined && !validSearchPreferences(body.search_preferences)
    || typeof body.goal !== "string" || body.goal.trim().length < 1 || body.goal.length > 8000
    || typeof body.idempotency_key !== "string" || body.idempotency_key.length < 8 || body.idempotency_key.length > 160
    || !(body.product_id === null || typeof body.product_id === "string" && uuid.test(body.product_id))
    || body.proposal_id !== proposalId || proposalId !== undefined && body.product_id !== null
    || body.project_id !== projectId || projectId !== undefined && (!uuid.test(projectId) || body.product_id === null)
    || !Array.isArray(body.sources) || body.sources.some(source => !record(source)
      || Object.keys(source).some(key => !["artifact_id", "expected_revision"].includes(key))
      || typeof source.artifact_id !== "string" || !uuid.test(source.artifact_id)
      || !Number.isSafeInteger(source.expected_revision) || Number(source.expected_revision) < 1)
    || body.requested_skills !== undefined && (!Array.isArray(body.requested_skills) || body.requested_skills.length > 8
      || body.requested_skills.some(skill => !record(skill) || Object.keys(skill).length !== 3
        || typeof skill.key !== "string" || !skill.key || skill.key.length > 160
        || typeof skill.version !== "string" || !skill.version || skill.version.length > 160
        || typeof skill.digest !== "string" || !/^[a-f0-9]{64}$/.test(skill.digest))
      || new Set(body.requested_skills.map(skill => (skill as RequestedSkill).key)).size !== body.requested_skills.length)) return null;
  return value as RunStartIntent;
}
