import { record, same, snapshot, validReads, uuid, positive } from "./ui-contract";
import { proofClockCurrent } from "@/lib/proof-clock";
import { factCanPrepare, factIdentity, factSourceKey, observationOperation, reviewOperation, sameFactCommand, sameFactPayloadSemantics,
  tokenlessFactPayload, validFactCommand, validFactPayload, type FactCommand, type FactHost, type FactOperation,
  type FactPayload, type FactPrepared, type FactReceipt, type FactSource } from "./fact-workflow-contract";

export type FactPending = { stage: "inputs" | "preview" | "execute"; command: FactCommand };
export type FactLocal = { schema_version: "capa-fact-local-v1"; identity: string; pending: FactPending | null;
  savedReceipt: FactReceipt | null; outcome: "none" | "unknown" | "saved" };
export const blankFactLocal = (identity: string): FactLocal => ({ schema_version: "capa-fact-local-v1", identity, pending: null, savedReceipt: null, outcome: "none" });
export function factReceipt(x: unknown, operation?: FactOperation): x is FactReceipt {
  return record(x) && uuid(x.id) && uuid(x.subject_id) && positive(x.subject_revision) &&
    (x.operation === observationOperation && x.subject_type === "capa_observation" ||
      x.operation === reviewOperation && x.subject_type === "capa_named_verification_review") && (!operation || x.operation === operation);
}
export function factBegin(local: FactLocal, pending: FactPending): FactLocal {
  if (local.pending?.stage === "execute" && (pending.stage !== "execute" || !same(local.pending.command, pending.command))) throw new Error("原保存结果尚待核对，不能替换请求。");
  return snapshot({ ...local, pending, savedReceipt: null, outcome: pending.stage === "execute" ? "unknown" : "none" });
}
export const factBasisChanged = (local: FactLocal): FactLocal => local.pending?.stage === "execute" ? local : { ...local, pending: null };
export function factSaved(local: FactLocal, receipt: FactReceipt): FactLocal {
  if (!factReceipt(receipt, local.pending?.command.operation)) throw new Error("尚未取得本操作保存回执。");
  return snapshot({ ...local, pending: null, savedReceipt: receipt, outcome: "saved" });
}
export function factFailure(local: FactLocal, failure: unknown): { clearPrivate: boolean; saved: boolean; local: FactLocal } {
  const status = failure !== null && typeof failure === "object" && "status" in failure ? failure.status : undefined;
  const saved = local.outcome === "saved" || local.savedReceipt !== null;
  const clearPrivate = status === 401 || status === 403;
  return { clearPrivate, saved, local: clearPrivate ? { ...blankFactLocal(local.identity), outcome: saved ? "saved" : "none" } :
    saved ? { ...local, pending: null, outcome: "saved" } : local };
}
export function restoreFactLocal(x: unknown, identity: string): FactLocal | null {
  if (!record(x) || Object.keys(x).length !== 5 || x.schema_version !== "capa-fact-local-v1" || x.identity !== identity ||
      !["none", "unknown", "saved"].includes(String(x.outcome)) || !(x.savedReceipt === null || factReceipt(x.savedReceipt))) return null;
  if (x.outcome === "saved") return factReceipt(x.savedReceipt) ? snapshot({ ...blankFactLocal(identity), savedReceipt: x.savedReceipt, outcome: "saved" }) : null;
  if (x.savedReceipt !== null) return null;
  if (x.pending !== null) {
    if (!record(x.pending) || Object.keys(x.pending).length !== 2 || !["inputs", "preview", "execute"].includes(String(x.pending.stage)) ||
        !validFactCommand(x.pending.command)) return null;
    const c = x.pending.command;
    let parts: unknown; try { parts = JSON.parse(identity); } catch { return null; }
    if (!Array.isArray(parts) || parts.length !== 6 || c.product_id !== parts[1] || c.payload.issue_id !== parts[4] || c.payload.capa_id !== parts[5]) return null;
    const token = c.operation === observationOperation ? "confirmation_token" : "approval_token";
    if (x.pending.stage === "execute" ? !Object.hasOwn(c.payload, token) : Object.hasOwn(c.payload, token)) return null;
  }
  if (x.outcome === "unknown" && (!record(x.pending) || x.pending.stage !== "execute")) return null;
  return snapshot(x as FactLocal);
}
export function factInputsCommand(value: unknown, original: FactCommand): FactCommand | null {
  if (record(value) && Object.hasOwn(value, "command")) {
    if (Object.keys(value).length !== 2 || !validFactCommand(value.command) || !same(value.command.payload, tokenlessFactPayload(value.command.payload)) ||
        !same({ ...value.command, source_read_set: original.source_read_set }, original) || !reviewedFactMatches(value.review, value.command) ||
        !original.source_read_set.every(r => (value.command as FactCommand).source_read_set.some(n => same(r, n))))
      throw new Error("服务器实际核对与原请求、完整来源或固定范围不能闭合。");
    return snapshot(value.command);
  }
  if (!record(value) || value.operation !== original.operation || typeof value.allowed !== "boolean" || !validReads(value.required_source_read_set))
    throw new Error("尚未取得本操作的明确核对与完整来源。");
  if (!value.allowed) return null;
  const reads = value.required_source_read_set;
  if (!original.source_read_set.every(r => reads.some(n => same(r, n))))
    throw new Error("服务器读集缺少原选定来源，不能继续。");
  return snapshot({ ...original, source_read_set: reads });
}
function reviewedFactMatches(value: unknown, original: FactCommand): boolean {
  if (!record(value)) return false;
  const r = value, keys = ["operation", "payload_semantic", "stable_anchor", "binding", "inspection", "raw_source_basis",
    "required_source_read_set", "sources", "authority_snapshot", "policy_snapshot", "owner_id", "visibility", "current_issue_revision"];
  return Object.keys(r).length === keys.length && keys.every(k => Object.hasOwn(r, k)) && r.operation === original.operation &&
      sameFactPayloadSemantics(r.payload_semantic, original.payload) && record(r.stable_anchor) && record(r.binding) &&
      record(r.binding.body_material) && record(r.inspection) && Array.isArray(r.raw_source_basis) && validReads(r.required_source_read_set) &&
      same(r.required_source_read_set, original.source_read_set) && Array.isArray(r.sources) && record(r.authority_snapshot) && record(r.policy_snapshot) &&
      uuid(r.owner_id) && r.visibility === original.payload.visibility && r.current_issue_revision === original.payload.expected_issue_revision &&
      r.binding.kind === (original.operation === observationOperation ? "observation" : "review") && uuid(r.binding.current_issue_version_id) &&
      r.binding.body_material.kind === r.binding.kind && record(r.binding.body_material.scope) && r.binding.body_material.scope.product_id === original.product_id &&
      r.binding.body_material.issue_id === original.payload.issue_id && r.binding.body_material.capa_id === original.payload.capa_id;
}
export function factPrepared(value: unknown, original: FactCommand, now = Date.now()): FactPrepared | null {
  const tier = original.operation === observationOperation ? "T1" : "T2";
  if (!record(value) || !validFactCommand(value.command) || !sameFactCommand(value.command, original) ||
      !proofClockCurrent(tier, value.expires_at, now) || !record(value.review)) return null;
  const token = tier === "T1" ? "confirmation_token" : "approval_token";
  if ((tier === "T2" ? value.write_tier !== "T2" || value.named_decision !== true :
    Object.hasOwn(value, "write_tier") && value.write_tier !== "T1" || Object.hasOwn(value, "named_decision") && value.named_decision !== false) ||
    !Object.hasOwn(value.command.payload, token)) return null;
  if (!reviewedFactMatches(value.review, original)) return null;
  return snapshot({ ...value, write_tier: tier, named_decision: tier === "T2" } as unknown as FactPrepared);
}
export function newFactCommand(host: FactHost, operation: FactOperation, payload: FactPayload, commandId: string, key: string): FactCommand {
  if (!factCanPrepare(host, operation) || !validFactPayload(operation, payload) ||
      !same(payload, tokenlessFactPayload(payload)) || payload.issue_id !== host.binding.issue_id || payload.capa_id !== host.binding.capa_id ||
      payload.expected_issue_revision !== host.binding.current_issue.revision || payload.visibility !== host.binding.visibility || !factIdentity(host))
    throw new Error("当前固定范围、受众或本操作专业能力尚未核对。");
  const rule = host.rules.find(r => same(r.ref, payload.rule));
  if (!rule) throw new Error("请选当前可读的真实固定规则。");
  const selectedSources: FactSource[] = [...payload.sources, payload.at.source];
  if (operation === observationOperation && "records" in payload) {
    if (!same(payload.previous, rule.previous) || !payload.target_keys.every(k => rule.target_keys.includes(k)) ||
        !payload.records.every(r => host.records.some(choice => same(choice.record, r) && (host.binding.visibility === "private" || choice.visibility === "category")))) throw new Error("观察目标或原记录已变化，不能改写原值。");
    selectedSources.push(...payload.coverage_sources, ...payload.records.flatMap(r => r.sources));
  } else if (operation === reviewOperation && "candidate" in payload) {
    if (!same(payload.candidate, host.candidate) || !payload.observations.every(ref => host.observations.some(r => same(r, ref))) ||
        !payload.pair_applicability.every(p => host.pairs.some(choice => same(choice.mapping, p.mapping) && same(choice.method, p.method) && same(choice.criterion, p.criterion) &&
          (host.binding.visibility === "private" || choice.visibility === "category"))) ||
        !payload.action_fulfillment.every(a => host.actions.some(choice => choice.action_id === a.action_id &&
          (host.binding.visibility === "private" || choice.visibility === "category")))) throw new Error("复核对象或真实配对已变化，请重新核对。");
    selectedSources.push(...payload.pair_applicability.flatMap(p => [...p.sources, ...(p.method ? [p.method] : []), ...(p.criterion ? [p.criterion] : [])]),
      ...payload.action_fulfillment.flatMap(a => a.sources));
  } else throw new Error("操作与实际材料不匹配。");
  if (!selectedSources.every(s => host.sources.some(choice => same(choice.source, s) &&
      (host.binding.visibility === "private" || choice.visibility === "category")))) throw new Error("原来源不在当前可读选择中，或不能扩大受众。");
  const reads = new Map(host.operations[operation].required_source_read_set.map(r => [r.artifact_id, r.expected_revision]));
  for (const s of selectedSources) {
    if (reads.has(s.id) && reads.get(s.id) !== s.revision) throw new Error("来源固定版本冲突，请重新读取。");
    reads.set(s.id, s.revision);
  }
  const command = { command_id: commandId, idempotency_key: key, product_id: host.binding.scope.product_id,
    expected_revision: host.product_revision, operation, payload, source_read_set: [...reads].map(([artifact_id, expected_revision]) => ({ artifact_id, expected_revision })) };
  if (!validFactCommand(command)) throw new Error("完整原请求或来源超过当前范围，不能提交。");
  return snapshot(command);
}
/** Sources are whole server-owned refs. UI never computes or replaces their position. */
export function selectFactSources(host: FactHost, selected: string[]): FactSource[] {
  if (new Set(selected).size !== selected.length) throw new Error("请勿重复选择原文出处。");
  return selected.map(k => {
    const choice = host.sources.find(c => factSourceKey(c.source) === k);
    if (!choice) throw new Error("精确原文选项已变化，请重新选择。");
    return choice.source;
  });
}
