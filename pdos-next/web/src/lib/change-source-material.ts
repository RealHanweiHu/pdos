import { qualitySource } from "./build-quality-loop-view";
import { workRecord, workSame, workUuid, type WorkRead, type WorkSource } from "./project-work";
import type { WorkspaceTransport } from "./workspace-api";
import { handoffTime } from "./build-handoff-view";

/** Shared source registration only; formal Change decisions keep their existing flow. */
export type ChangeMaterialScope = { productId: string; productRevision: number; projectId: string; changeId: string; principalId: string };
export type MaterialRequest = { path: string; body: Record<string, unknown> } | { path: null; body: Record<string, unknown>; artifact_payload: MaterialArtifact; required_source_read_set: WorkRead[] };
export type MaterialArtifact = { title: string; content: string; source_label: string; visibility: "private" | "category" | "audience" };
export type MaterialDraft = { stage: "material_draft"; material: Record<string, unknown>; material_content: string; material_visibility: string; required_source_read_set: WorkRead[]; artifact_payload: MaterialArtifact };
export type MaterialCommand = { command_id: string; idempotency_key: string; product_id: string; expected_revision: number; operation: "evidence.artifact.register"; payload: MaterialArtifact; source_read_set: WorkRead[] };
export type MaterialReceipt = { id: string; operation: "evidence.artifact.register"; subject_type: "artifact"; subject_id: string; subject_revision: number; result: { id: string; revision: number; status: string } };
export type MaterialPending = { stage: "draft"; request: MaterialRequest } | { stage: "register"; request: MaterialRequest; draft: MaterialDraft; command: MaterialCommand } | { stage: "read"; request: MaterialRequest; draft: MaterialDraft; command: MaterialCommand; receipt: MaterialReceipt };
export type MaterialLocal = { schema_version: 1; scope: ChangeMaterialScope; pending: MaterialPending | null; source: WorkSource | null };
const revision = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) > 0;
const text = (v: unknown): v is string => typeof v === "string" && !!v.trim();
function reads(v: unknown): v is WorkRead[] { return Array.isArray(v) && v.every(row => workRecord(row) && workUuid(row.artifact_id) && revision(row.expected_revision)) && new Set(v.map(row => row.artifact_id)).size === v.length; }
function artifact(v: unknown): v is MaterialArtifact { return workRecord(v) && Object.keys(v).every(key => ["title", "content", "source_label", "visibility"].includes(key)) && text(v.title) && v.title.length <= 200 && text(v.content) && text(v.source_label) && v.source_label.length <= 200 && ["private", "category", "audience"].includes(String(v.visibility)); }
function request(v: unknown, s: ChangeMaterialScope): v is MaterialRequest { if (!workRecord(v) || !workRecord(v.body) || v.body.change_id !== s.changeId) return false; return v.path === null ? v.body.schema_version === "pdos-field-change-implementation-occurrence-v1" && artifact(v.artifact_payload) && reads(v.required_source_read_set) : v.path === `v1/products/${s.productId}/change-execution/selection-material` && revision(v.body.expected_change_revision); }
function materialMatches(value: Record<string, unknown>, requested: Record<string, unknown>, s: ChangeMaterialScope): boolean {
  if (!workRecord(value.scope) || value.scope.product_id !== s.productId || value.scope.project_id !== s.projectId || value.change_id !== s.changeId) return false;
  if (workRecord(requested.field_intent)) return value.schema_version === "pdos-field-change-selection-v1" && workSame(value.feedback, requested.field_intent.feedback) && value.executor_id === requested.field_intent.executor_id && workSame(value.item, requested.item) && value.status === requested.status && workSame(value.valid_until === null ? null : handoffTime(value.valid_until), requested.valid_until === null ? null : handoffTime(requested.valid_until)) && value.reason === requested.reason && value.decider_id === s.principalId;
  if (requested.schema_version === "pdos-field-change-implementation-occurrence-v1") return value.executor_id === s.principalId && workSame(value, requested);
  return false;
}
export function parseMaterialDraft(v: unknown, requested: MaterialRequest, s: ChangeMaterialScope): MaterialDraft {
  if (!workRecord(v) || v.stage !== "material_draft" || !workRecord(v.material) || !text(v.material_content) || /[\r\n]/.test(v.material_content) || !artifact(v.artifact_payload) || v.artifact_payload.content !== v.material_content || v.artifact_payload.visibility !== v.material_visibility || !reads(v.required_source_read_set) || !materialMatches(v.material, requested.body, s)) throw new Error("尚未取得与所选实际变更、原生依据和本人声明一致的来源材料。");
  let body: unknown; try { body = JSON.parse(v.material_content); } catch { throw new Error("服务器来源材料不是完整的结构化原文。"); }
  if (!workSame(body, v.material)) throw new Error("来源原文与本次材料内容不一致，不能登记。");
  return v as MaterialDraft;
}
function command(v: unknown, s: ChangeMaterialScope, draft: MaterialDraft): v is MaterialCommand { return workRecord(v) && workUuid(v.command_id) && workUuid(v.idempotency_key) && v.product_id === s.productId && revision(v.expected_revision) && v.operation === "evidence.artifact.register" && artifact(v.payload) && workSame(v.payload, draft.artifact_payload) && reads(v.source_read_set) && workSame(v.source_read_set, draft.required_source_read_set); }
function receipt(v: unknown, c: MaterialCommand): v is MaterialReceipt { return workRecord(v) && workUuid(v.id) && v.operation === c.operation && v.subject_type === "artifact" && workUuid(v.subject_id) && v.subject_revision === 1 && workRecord(v.result) && v.result.id === v.subject_id && v.result.revision === 1 && v.result.status === "active"; }
export async function runMaterialRequest(api: WorkspaceTransport, waiting: MaterialPending, s: ChangeMaterialScope, onStage: (value: MaterialPending) => void, active: () => boolean) {
  if (!validMaterialPending(waiting, s)) throw new Error("原材料请求与当前实际变更或本人范围不一致。");
  let step = waiting; if (!active()) return null;
  if (step.stage === "draft") { const request = step.request, value = request.path === null ? { stage: "material_draft", material: request.body, material_content: request.artifact_payload.content, material_visibility: request.artifact_payload.visibility, artifact_payload: request.artifact_payload, required_source_read_set: request.required_source_read_set } : await api<unknown>(request.path, request.body); if (!active()) return null; const draft = parseMaterialDraft(value, request, s); step = { stage: "register", request, draft, command: { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation: "evidence.artifact.register", product_id: s.productId, expected_revision: s.productRevision, payload: structuredClone(draft.artifact_payload), source_read_set: structuredClone(draft.required_source_read_set) } }; onStage(step); }
  if (step.stage === "register") { const value = await api<unknown>("v1/commands", step.command); if (!active()) return null; if (!receipt(value, step.command)) throw new Error("材料登记回执尚未核实，请保留同一原请求。"); step = { ...step, stage: "read", receipt: value }; onStage(step); }
  const value = await api<unknown>(`v1/products/${s.productId}/workspace`); if (!active()) return null;
  if (!workRecord(value) || !Array.isArray(value.sources)) throw new Error("材料已登记，实际原文尚未完整读回；请继续核对已有材料。");
  const row = value.sources.find(row => workRecord(row) && row.id === step.receipt.subject_id && row.revision === step.receipt.subject_revision);
  if (!workRecord(row) || row.content !== step.command.payload.content || row.status !== "active" || row.original_id !== null || !text(row.title) || typeof row.visibility !== "string") throw new Error("材料已登记，尚未取得同一实际原文版本；请继续只读核对。");
  const source = await qualitySource({ id: String(row.id), revision: Number(row.revision), title: row.title, content: String(row.content), visibility: row.visibility, status: String(row.status) }, 1);
  return active() ? { source, receipt: step.receipt } : null;
}
export function validMaterialPending(v: unknown, s: ChangeMaterialScope): v is MaterialPending { if (!workRecord(v) || !request(v.request, s)) return false; if (v.stage === "draft") return true; if (!["register", "read"].includes(String(v.stage))) return false; try { const draft = parseMaterialDraft(v.draft, v.request, s); if (!command(v.command, s, draft)) return false; return v.stage === "register" || receipt(v.receipt, v.command); } catch { return false; } }
export function blankMaterialLocal(scope: ChangeMaterialScope): MaterialLocal { return { schema_version: 1, scope: structuredClone(scope), pending: null, source: null }; }
export const materialStorageKey = (s: ChangeMaterialScope, slot: string) => `pdos.change-material.v1:${s.principalId}:${s.productId}:${s.projectId}:${s.changeId}:${slot}`;
export function restoreMaterialLocal(v: unknown, s: ChangeMaterialScope): MaterialLocal | null { if (!workRecord(v) || v.schema_version !== 1 || !workRecord(v.scope) || !workSame({ ...v.scope, productRevision: s.productRevision }, s) || v.pending !== null && !validMaterialPending(v.pending, s) || v.source !== null && (!workRecord(v.source) || !workUuid(v.source.id) || !revision(v.source.revision) || v.source.kind !== "artifact" || typeof v.source.position !== "string" || !/^line:1;quote_sha256:[0-9a-f]{64}$/.test(v.source.position)) || v.pending !== null && v.source !== null) return null; return { ...(structuredClone(v) as MaterialLocal), scope: structuredClone(s) }; }
