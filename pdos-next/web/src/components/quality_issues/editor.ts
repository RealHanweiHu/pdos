import { failureProblem, operationProblem, type Context, type FailureRef, type Issue, type Operation, type QualityIntent, type SourceRef } from "./contracts";

export type EditorFields = {
  text: string; ownerId: string; sourceId: string; selectedId: string;
  occurredAt: string; timezone: string; actionText: string; actionKind: "corrective" | "preventive";
  method: string; acceptance: string; observationUntil: string; effectiveness: "effective" | "ineffective";
  evidenceIds: string[];
};
export const EMPTY_FIELDS: EditorFields = { text: "", ownerId: "", sourceId: "", selectedId: "", occurredAt: "", timezone: "", actionText: "", actionKind: "corrective", method: "", acceptance: "", observationUntil: "", effectiveness: "effective", evidenceIds: [] };
export type EditorResult = { intent: QualityIntent | null; problem: string | null };
export function zonedTime(value: string): boolean { return Number.isFinite(Date.parse(value)) && /(Z|[+-]\d{2}:\d{2})$/i.test(value); }
export function editorIntent(operation: Operation, fields: EditorFields, issue: Issue | null, failures: FailureRef[], mergeCandidates: Issue[], context: Context): EditorResult {
  const blocked = (problem: string): EditorResult => ({ intent: null, problem });
  const permission = operationProblem(operation, context);
  if (permission) return blocked(permission);
  if (!fields.text.trim()) return blocked("请填写本次办理说明或具名结论。");
  if (operation === "quality.issue.create") {
    const failure = failures.find(value => value.failureKey === fields.selectedId);
    if (!failure) return blocked("请选择服务器核验的精确失败测量。");
    const problem = failureProblem(failure);
    if (problem) return blocked(problem);
    if (!failure.eventId) return blocked("测试结果来源尚未接齐，当前不能建单。");
    return { intent: { operation, failureKey: failure.failureKey, runId: failure.run.id, measurementId: failure.measurement.id, eventId: failure.eventId, title: fields.text.trim() }, problem: null };
  }
  if (!issue) return blocked("请先读取服务器问题记录。");
  if (issue.mergedInto) return blocked("原问题已归并，请从目标问题继续办理；历史仍保留。");
  const target = { issue: { id: issue.id, revision: issue.revision } };
  const result = (intent: QualityIntent): EditorResult => ({ intent, problem: null });
  if (operation === "quality.issue.merge") {
    const source = mergeCandidates.find(value => value.id === fields.selectedId);
    if (!source || source.id === issue.id || source.mergedInto) return blocked("请选择一个当前可见且未归并的原问题。");
    if (source.audience.some(audience => !issue.audience.includes(audience)) || issue.audience.some(audience => !source.audience.includes(audience))) return blocked("归并受众存在差异，须服务器处理冲突；不能扩大任一原问题受众。");
    return result({ ...target, operation, sourceIssues: [{ id: source.id, revision: source.revision }], reason: fields.text.trim() });
  }
  if (operation === "quality.issue.triage" || operation === "quality.issue.recheck") return result({ ...target, operation, reason: fields.text.trim() });
  if (issue.requiresRecheck || issue.failures.some(failure => [failure.source, failure.method, failure.criterion].some(source => source.status !== "current"))) return blocked("来源、配置或现有判断待重核；先记录重核需求。");
  if (operation === "quality.issue.close") {
    if (issue.status !== "awaiting_verification" || !issue.capa?.effectiveness || issue.capa.effectiveness.result !== "effective" || !issue.capa.effectiveness.independent || !issue.capa.effectiveness.verificationRuns.length || issue.capa.actions.some(action => !action.completed)) return blocked("须措施完成且已有服务器核验的独立有效性决定，才能具名关闭。");
    return result({ ...target, operation, text: fields.text.trim() });
  }
  const source = context.decisionSources.find(value => sourceKey(value) === fields.sourceId && value.status === "current");
  if (operation === "quality.capa.effectiveness.decide") {
    if (!issue.capa || issue.status !== "awaiting_verification") return blocked("CAPA 尚未进入有效性复核阶段。");
    const evidenceIds = [...new Set(fields.evidenceIds)].sort();
    const evidence = evidenceIds.map(id => context.verificationEvidence.find(value => value.id === id && value.current && value.independent));
    if (!evidence.length || evidence.some(value => !value || !context.independentVerificationRuns.some(run => run.id === value.run.id && run.revision === value.run.revision))) return blocked("请选择服务器已核验的独立复验依据；执行人自证不能替代。");
    return result({ ...target, operation, result: fields.effectiveness, text: fields.text.trim(), evidenceIds });
  }
  if (!source) return blocked("请选择服务器当前可读的固定来源版本。");
  if (operation === "quality.issue.root_cause.decide") return result({ ...target, operation, text: fields.text.trim(), sources: [source] });
  if (!context.accountablePeople.some(person => person.id === fields.ownerId)) return blocked("请选择服务器可用的具名执行责任人。");
  if (operation === "quality.capa.draft") {
    if (!context.draftIds) return blocked("草稿办理入口待接入。");
    if (!fields.actionText.trim() || !fields.method.trim() || !fields.acceptance.trim() || !zonedTime(fields.observationUntil)) return blocked("CAPA 须明确措施、复核方法、接受判据和含时区的观察截至时间。");
    if (!issue.failures.length) return blocked("CAPA 缺固定失败范围。");
    return result({ ...target, operation, capaId: context.draftIds.capaId, hypotheses: [{ text: fields.text.trim(), sources: [source] }], actions: [{ id: context.draftIds.actionId, kind: fields.actionKind, text: fields.actionText.trim(), executorId: fields.ownerId }], requirement: { method: fields.method.trim(), acceptance: fields.acceptance.trim(), observationUntil: fields.observationUntil, requiredFailureIds: issue.failures.map(value => value.failureKey) } });
  }
  if (!zonedTime(fields.occurredAt)) return blocked("真实措施发生时间须含 UTC 或时区偏移。");
  try { if (!fields.timezone.trim()) throw new Error(); new Intl.DateTimeFormat("zh-CN", { timeZone: fields.timezone }); }
  catch { return blocked("请保留有效的原始 IANA 时区。"); }
  const id = operation === "quality.issue.containment.record" ? context.draftIds?.containmentId : issue.capa?.actions.find(action => action.id === fields.selectedId && !action.completed)?.id;
  if (!id) return blocked("当前没有可办理的措施记录或记录入口未接入。");
  const action = { id, text: fields.text.trim(), executorId: fields.ownerId, evidence: [source], at: { occurredAt: fields.occurredAt, originalTimezone: fields.timezone, source } };
  return operation === "quality.issue.containment.record" ? result({ ...target, operation, action }) : result({ ...target, operation: "quality.capa.actions.complete", completions: [action] });
}
export function sourceKey(source: SourceRef): string { return `${source.kind}:${source.id}:${source.revision}:${source.position}`; }
