import {
  candidateFormBasisKey, candidateLinkKey, candidateMappingKey, candidatePayload, candidateSourceKey,
  validCandidateMaterials, validCandidateScope,
  type CandidateFormPayload, type CandidateFormScope, type CandidateMaterials,
} from "./candidate-form-contract";
import { eventTime, json, positive, record, same, snapshot, uuid, validReads,
  type Read, type Missing } from "./ui-contract";

export const candidateOperation = "quality.capa.verification.candidate.record" as const;
export type CandidateHost = {
  scope: CandidateFormScope | null; materials: CandidateMaterials;
  product_revision: number; required_source_read_set: readonly Read[];
  allowed: boolean; current_evaluation: "evaluated_current" | "not_evaluated_historical" | "unavailable";
  source_status: "current" | "needs_recheck" | "unavailable";
  authority: { authorized: boolean; qualified: boolean | null; synthetic: boolean };
  missing: readonly Missing[]; allowProductVisibility: boolean;
  /** A host-confirmed new access/read epoch; never a local grant or unlock switch. */
  accessEpoch: string;
};
export type CandidateCommand = {
  command_id: string; idempotency_key: string; product_id: string; expected_revision: number;
  operation: typeof candidateOperation;
  payload: CandidateFormPayload & { confirmation_token?: string };
  source_read_set: Read[];
};
export type CandidatePending = { stage: "inputs" | "preview" | "execute"; command: CandidateCommand };
export type CandidateInputs = { operation: typeof candidateOperation; allowed: boolean; required_source_read_set: Read[] };
export type CandidateReview = Record<string, unknown> & {
  operation: typeof candidateOperation; payload_semantic: CandidateFormPayload;
  stable_anchor: Record<string, unknown>; binding: Record<string, unknown>; inspection: Record<string, unknown>;
  raw_source_basis: unknown[]; required_source_read_set: Read[]; sources: unknown[];
  authority_snapshot: Record<string, unknown>; policy_snapshot: Record<string, unknown>;
  owner_id: string; visibility: "private" | "category" | "audience"; current_issue_revision: number;
};
export type CandidatePrepared = { command: CandidateCommand; expires_at: string; review: CandidateReview };
export type CandidateReceipt = { id: string; operation: typeof candidateOperation; subject_id: string;
  subject_revision: 1; subject_type: "capa_verification_candidate" };
export type CandidateLocal = { schema_version: "candidate-workflow.v1"; identity: string;
  draft: CandidateFormPayload | null; pending: CandidatePending | null;
  savedReceipt: CandidateReceipt | null; outcome: "none" | "unknown" | "saved";
};

export function candidateIdentity(host: CandidateHost): string | null {
  if (!validCandidateScope(host.scope)) return null;
  const s = host.scope;
  return JSON.stringify([s.tenant_id, s.product_id, s.project_id, s.principal_id, s.issue_id, s.capa_id]);
}
export function candidateHostBasis(host: CandidateHost): string | null {
  if (!validCandidateScope(host.scope) || !validCandidateMaterials(host.scope, host.materials) ||
      !positive(host.product_revision) || !validReads(host.required_source_read_set) ||
      typeof host.allowed !== "boolean" || !record(host.authority) ||
      typeof host.authority.authorized !== "boolean" ||
      !(host.authority.qualified === null || typeof host.authority.qualified === "boolean") ||
      typeof host.authority.synthetic !== "boolean" || typeof host.allowProductVisibility !== "boolean" ||
      typeof host.accessEpoch !== "string" || !host.accessEpoch ||
      !["evaluated_current", "not_evaluated_historical", "unavailable"].includes(host.current_evaluation) ||
      !["current", "needs_recheck", "unavailable"].includes(host.source_status) ||
      !Array.isArray(host.missing) || !host.missing.every(row => record(row) && typeof row.code === "string" &&
        typeof row.detail === "string" && !!row.code && !!row.detail)) return null;
  return JSON.stringify([candidateFormBasisKey(host.scope, host.materials), host.product_revision,
    host.required_source_read_set, host.allowed, host.current_evaluation, host.source_status,
    host.authority, host.allowProductVisibility, host.accessEpoch]);
}
export function candidateCanPrepare(host: CandidateHost): boolean {
  return candidateHostBasis(host) !== null && host.allowed === true && host.current_evaluation === "evaluated_current" &&
    host.source_status === "current" && host.authority.authorized === true && host.authority.qualified === true;
}
export function exactCandidatePayload(value: unknown): value is CandidateFormPayload {
  if (!record(value) || Object.keys(value).length !== 8 || !uuid(value.issue_id) || !positive(value.expected_issue_revision) ||
      !uuid(value.capa_id) || !Array.isArray(value.remediation_link_refs) ||
      !value.remediation_link_refs.every(ref => record(ref) && Object.keys(ref).length === 2 && uuid(ref.id) && ref.revision === 1) ||
      new Set(value.remediation_link_refs.map(ref => ref.id)).size !== value.remediation_link_refs.length ||
      !Array.isArray(value.mappings) || !Array.isArray(value.sources) ||
      typeof value.reason !== "string" || !value.reason.trim() || [...value.reason].length > 2000 ||
      !["private", "category", "audience"].includes(String(value.visibility)) || !json(value)) return false;
  // Reuse the frozen form validator with the exact already-selected objects. This
  // validates wire shape, not source visibility, qualification or currentness.
  const failures = [...new Set(value.mappings.map(row => record(row) ? String(row.failure_id) : ""))];
  const scope: CandidateFormScope = { tenant_id: value.issue_id, product_id: value.issue_id, project_id: value.issue_id,
    principal_id: value.issue_id, issue_id: value.issue_id, current_issue: { id: value.issue_id, revision: value.expected_issue_revision },
    capa_id: value.capa_id, failure_ids: failures.length ? failures : ["shape-validation-only"],
    visibility: value.visibility as CandidateFormScope["visibility"], issue_label: "", capa_label: "", origin_issue: null };
  // An empty mapping is a real indeterminate candidate, not a manufactured pair.
  const materials: CandidateMaterials = { links: value.remediation_link_refs.map(ref => ({ ref, label: "", detail: "", visibility: value.visibility })) as unknown as CandidateMaterials["links"],
    mappings: value.mappings.map(mapping => ({ mapping, label: "", detail: "", original_value: null,
      conditions: null, occurred_at: null, original_timezone: null, visibility: value.visibility })) as unknown as CandidateMaterials["mappings"],
    sources: value.sources.map(reference => ({ reference, title: "", visibility: value.visibility })) as unknown as CandidateMaterials["sources"] };
  if (!validCandidateMaterials(scope, materials)) return false;
  const payload = candidatePayload(scope, materials, { links: materials.links.map(row => candidateLinkKey(row.ref)),
    mappings: materials.mappings.map(row => candidateMappingKey(row.mapping)), sources: materials.sources.map(row => candidateSourceKey(row.reference)),
    reason: value.reason, visibility: value.visibility as CandidateFormScope["visibility"] }, true);
  return payload !== null && same(payload, value);
}
export function validCandidateCommand(value: unknown, identity?: string): value is CandidateCommand {
  if (!record(value) || Object.keys(value).length !== 7 || !uuid(value.command_id) || !uuid(value.idempotency_key) ||
      !uuid(value.product_id) || !positive(value.expected_revision) || value.operation !== candidateOperation ||
      !record(value.payload) || !validReads(value.source_read_set)) return false;
  const { confirmation_token, ...payload } = value.payload;
  if (Object.hasOwn(value.payload, "confirmation_token") && (typeof confirmation_token !== "string" || confirmation_token.length < 20 || confirmation_token.length > 128)) return false;
  if (!exactCandidatePayload(payload)) return false;
  if (identity) { try { const parts: unknown = JSON.parse(identity); if (!Array.isArray(parts) || parts.length !== 6 ||
    value.product_id !== parts[1] || payload.issue_id !== parts[4] || payload.capa_id !== parts[5]) return false;
  } catch { return false; } }
  return true;
}
export function candidateReads(...sets: readonly (readonly Read[])[]): Read[] {
  const refs = new Map<string, number>();
  for (const set of sets) for (const row of set) {
    if (!uuid(row.artifact_id) || !positive(row.expected_revision) || (refs.has(row.artifact_id) && refs.get(row.artifact_id) !== row.expected_revision))
      throw new Error("来源版本冲突，需重新读取，不能改写原出处。");
    refs.set(row.artifact_id, row.expected_revision);
  }
  const result = [...refs].map(([artifact_id, expected_revision]) => ({ artifact_id, expected_revision }));

  return result;
}
export function newCandidateCommand(host: CandidateHost, payload: CandidateFormPayload, commandId: string, key: string): CandidateCommand {
  if (!candidateCanPrepare(host) || !host.scope || !exactCandidatePayload(payload) ||
      payload.issue_id !== host.scope.issue_id || payload.capa_id !== host.scope.capa_id ||
      payload.expected_issue_revision !== host.scope.current_issue.revision || payload.visibility !== host.scope.visibility)
    throw new Error("当前固定问题、受众或专业能力未核对，不能提交候选。");
  const selected = candidatePayload(host.scope, host.materials, {
    links: payload.remediation_link_refs.map(candidateLinkKey), mappings: payload.mappings.map(candidateMappingKey),
    sources: payload.sources.map(candidateSourceKey), reason: payload.reason, visibility: payload.visibility,
  }, host.allowProductVisibility);
  if (!same(selected, payload)) throw new Error("选定材料已变化，请重新核对真实选项。");
  const reads = [...payload.sources, ...payload.mappings.flatMap(row => row.applicability_sources)]
    .map(ref => ({ artifact_id: ref.artifact_id, expected_revision: ref.expected_revision }));
  const command = { command_id: commandId, idempotency_key: key, product_id: host.scope.product_id,
    expected_revision: host.product_revision, operation: candidateOperation, payload,
    source_read_set: candidateReads(host.required_source_read_set, reads) };
  if (!validCandidateCommand(command)) throw new Error("原命令标识或完整材料缺失，不能开始办理。");
  return snapshot(command);
}
export function candidateInputsCommand(value: unknown, original: CandidateCommand): CandidateCommand | null {
  if (!record(value) || value.operation !== candidateOperation || typeof value.allowed !== "boolean" ||
      !validReads(value.required_source_read_set)) throw new Error("未取得本候选的明确核对结果与完整来源。");
  if (!value.allowed) return null;
  const reads = value.required_source_read_set;
  if (!original.source_read_set.every(ref => reads.some(row => same(row, ref))))
    throw new Error("服务器来源并集缺少原选定材料，不能继续预览。");
  return snapshot({ ...original, source_read_set: reads });
}
export function candidatePrepared(value: unknown, original: CandidateCommand, now = Date.now()): CandidatePrepared | null {
  if (!record(value) || !validCandidateCommand(value.command) || !record(value.review) ||
      eventTime(value.expires_at) === null || Date.parse(String(value.expires_at)) <= now ||
      typeof value.command.payload.confirmation_token !== "string" ||
      (Object.hasOwn(value, "write_tier") && value.write_tier !== "T1") ||
      (Object.hasOwn(value, "named_decision") && value.named_decision !== false)) return null;
  const withoutToken = (payload: CandidateCommand["payload"]) => Object.fromEntries(Object.entries(payload)
    .filter(([key]) => key !== "confirmation_token"));
  if (!same({ ...value.command, payload: withoutToken(value.command.payload) },
      { ...original, payload: withoutToken(original.payload) })) return null;
  const r = value.review, fields = ["operation", "payload_semantic", "stable_anchor", "binding", "inspection",
    "raw_source_basis", "required_source_read_set", "sources", "authority_snapshot", "policy_snapshot",
    "owner_id", "visibility", "current_issue_revision"];
  if (Object.keys(r).length !== fields.length || !fields.every(field => Object.hasOwn(r, field)) || !json(r) ||
      r.operation !== candidateOperation || !same(r.payload_semantic, withoutToken(original.payload)) ||
      !record(r.stable_anchor) || !record(r.binding) || !record(r.binding.basis) || !record(r.inspection) ||
      !Array.isArray(r.raw_source_basis) || !validReads(r.required_source_read_set) || !Array.isArray(r.sources) ||
      !record(r.authority_snapshot) || !record(r.policy_snapshot) || !uuid(r.owner_id) ||
      r.visibility !== original.payload.visibility || r.current_issue_revision !== original.payload.expected_issue_revision ||
      !same(r.required_source_read_set, original.source_read_set) ||
      r.binding.basis.issue_id !== original.payload.issue_id || r.binding.basis.capa_id !== original.payload.capa_id ||
      !same(r.binding.remediation_link_refs, original.payload.remediation_link_refs) ||
      !same(r.binding.mappings, original.payload.mappings) || !same(r.inspection.binding, r.binding) ||
      r.inspection.applicable !== null || r.inspection.independently_verified !== null ||
      r.inspection.observation_complete !== null || r.inspection.result !== "indeterminate") return null;
  return snapshot(value as unknown as CandidatePrepared);
}
export function candidateErrorStatus(value: unknown): number | undefined {
  // Workspace transport throws Error instances with actual .status/.code fields.
  return value !== null && typeof value === "object" && "status" in value && typeof value.status === "number" ? value.status : undefined;
}
export function candidateReceipt(value: unknown): value is CandidateReceipt {
  return record(value) && uuid(value.id) && value.operation === candidateOperation && uuid(value.subject_id) &&
    value.subject_revision === 1 && value.subject_type === "capa_verification_candidate";
}
export function blankCandidateLocal(identity: string): CandidateLocal {
  return { schema_version: "candidate-workflow.v1", identity, draft: null, pending: null, savedReceipt: null, outcome: "none" };
}
export function restoreCandidateLocal(value: unknown, identity: string): CandidateLocal | null {
  if (!record(value) || Object.keys(value).length !== 6 || value.schema_version !== "candidate-workflow.v1" || value.identity !== identity ||
      !(value.draft === null || exactCandidatePayload(value.draft)) ||
      !(value.savedReceipt === null || candidateReceipt(value.savedReceipt)) ||
      !["none", "unknown", "saved"].includes(String(value.outcome))) return null;
  if (value.pending !== null && (!record(value.pending) || Object.keys(value.pending).length !== 2 ||
      !["inputs", "preview", "execute"].includes(String(value.pending.stage)) || !validCandidateCommand(value.pending.command, identity) ||
      (value.pending.stage === "execute" ? typeof value.pending.command.payload.confirmation_token !== "string" :
        Object.hasOwn(value.pending.command.payload, "confirmation_token")))) return null;
  if (value.outcome === "saved") {
    if (!candidateReceipt(value.savedReceipt)) return null;
    return snapshot({ ...blankCandidateLocal(identity), savedReceipt: value.savedReceipt, outcome: "saved" });
  }
  if (value.savedReceipt !== null || (value.outcome === "unknown" && (!record(value.pending) || value.pending.stage !== "execute"))) return null;
  return snapshot(value as unknown as CandidateLocal);
}
export function candidateBasisChanged(local: CandidateLocal): CandidateLocal {
  // A write may already have committed. A changed read must not erase its exact recovery key.
  return local.pending?.stage === "execute" ? { ...local, draft: null } : { ...local, draft: null, pending: null };
}
export function candidateSaved(local: CandidateLocal, receipt: CandidateReceipt): CandidateLocal {
  return snapshot({ ...local, draft: null, pending: null, savedReceipt: receipt, outcome: "saved" });
}
export function candidateFailureOutcome(local: CandidateLocal, status?: number): {
  clearPrivate: boolean; saved: boolean; pending: CandidatePending | null;
} {
  const saved = local.outcome === "saved" || local.savedReceipt !== null;
  return { clearPrivate: status === 401 || status === 403, saved, pending: saved ? null : local.pending };
}
