export const dimensions = { coverage: "材料覆盖", citations: "引用可核对", units_conditions: "单位与工况", unknowns: "未知保留", scope: "范围边界", length: "输出长度" } as const;
export const assessments = { unknown: "尚未评价", acceptable: "可接受", issues: "存在问题", not_applicable: "不适用" } as const;
export const severities = { unknown: "尚未判断", none: "未发现错误", minor: "轻微错误", major: "较大错误", critical: "严重错误（暂停 T0）" } as const;
export type ReviewCase = { source_ref: string; material_kind: "own" | "synthetic"; conclusion: string; severity: keyof typeof severities; criteria: Record<keyof typeof dimensions, keyof typeof assessments> };
export function blankReview(): ReviewCase { return { source_ref: "", material_kind: "own", conclusion: "", severity: "unknown", criteria: { coverage: "unknown", citations: "unknown", units_conditions: "unknown", unknowns: "unknown", scope: "unknown", length: "unknown" } }; }
export type QualificationReading = {
  skill_key: string; skill_version: string | null; skill_digest: string | null; tool_digest: string | null; model_digest: string | null;
  model_label: string | null; model_version: string | null; model_enabled: boolean; pilot: boolean; draft_operations: string[];
  enabled: boolean; revision: number; can_edit: boolean; category_revision: number;
  qualification: { state: string; id: string | null; reviewed_by_name: string | null; reviewed_at: string | null; case_count: number; receipt_id: string | null };
  reviews: { id: string; skill_version: string; model_version: string; created_at: string; receipt_id: string; cases: ReviewCase[]; current: boolean }[];
  next_cursor: string | null;
};
export type CaseReference = { batch_id: string; index: number };
export type ReviewPayload = { skill_key: string; skill_digest: string; tool_digest: string; model_digest: string; cases: ReviewCase[]; personally_reviewed: true; confirmation_token?: string };
export type QualificationPayload = { skill_key: string; expected_revision: number; decision: "批准" | "撤销"; reason: string; case_refs: CaseReference[]; skill_digest?: string; tool_digest?: string; model_digest?: string; approval_token?: string };
export type QualificationCommand = { category_id: string; product_id: null; command_id: string; idempotency_key: string; expected_revision: number; source_read_set: []; } & ({ operation: "ai.skill.review.record"; payload: ReviewPayload } | { operation: "ai.skill.qualify"; payload: QualificationPayload });
export type QualificationReceipt = { id: string; operation: string; category_id: string; writer_id: string; requester_id: string; agent_run_id: string | null; subject_type: string; subject_revision: number; result: { skill_key: string; decision?: string; next_revision?: number; case_count: number; quality_paused?: boolean } };
export type QualificationPreview = { command: QualificationCommand; expires_at: string | null; write_tier?: "T2"; review: { skill_key: string; skill_version?: string; model_label?: string; model_version?: string; effect: string; decision?: string; reason?: string; case_count: number; cases?: ReviewCase[] } };
export const qualificationPendingKey = (principalId: string, categoryId: string) => `pdos-skill-qualification:v1:${principalId}:${categoryId}`;
export function parseQualificationPending(raw: string, category: string): QualificationCommand {
  const value = JSON.parse(raw) as QualificationCommand;
  const uuid = (v: unknown) => typeof v === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(v);
  const revision = (v: unknown) => Number.isSafeInteger(v) && (v as number) >= 0;
  const keys = ["category_id", "product_id", "command_id", "idempotency_key", "operation", "expected_revision", "source_read_set", "payload"];
  if (!value || Object.keys(value).length !== keys.length || Object.keys(value).some(key => !keys.includes(key)) || value.category_id !== category || value.product_id !== null || !uuid(value.command_id) || typeof value.idempotency_key !== "string" || value.idempotency_key.length < 8 || value.idempotency_key.length > 160 || !revision(value.expected_revision) || value.expected_revision < 1 || !Array.isArray(value.source_read_set) || value.source_read_set.length || !value.payload || typeof value.payload.skill_key !== "string" || !value.payload.skill_key || value.payload.skill_key.length > 160) throw new Error("原审阅请求无法读取，请保留恢复记录并核对当前状态。");
  const payload = value.payload;
  if (value.operation === "ai.skill.review.record") {
    const p = value.payload;
    if (p.personally_reviewed !== true || !Array.isArray(p.cases) || p.cases.length < 1 || p.cases.length > 20 || typeof p.confirmation_token !== "string" || p.confirmation_token.length < 20) throw new Error("原案例审阅确认不完整。");
  } else if (value.operation === "ai.skill.qualify") {
    const p = value.payload;
    if (!revision(p.expected_revision) || !["批准", "撤销"].includes(p.decision) || typeof p.reason !== "string" || !p.reason.trim() || !Array.isArray(p.case_refs) || p.case_refs.length > 20 || p.case_refs.some(ref => !uuid(ref.batch_id) || !revision(ref.index) || ref.index > 19) || typeof p.approval_token !== "string" || p.approval_token.length < 20 || p.decision === "批准" && p.case_refs.length < 10) throw new Error("原具名资格决定不完整。");
  } else throw new Error("原请求不属于案例审阅或资格决定。");
  if (value.operation === "ai.skill.review.record" || value.payload.decision === "批准") {
    for (const field of ["skill_digest", "tool_digest", "model_digest"] as const) if (typeof payload[field] !== "string" || !/^[a-f0-9]{64}$/.test(payload[field]!)) throw new Error("原技能或模型绑定不完整。");
  }
  return value;
}
export function matchesQualificationReceipt(receipt: QualificationReceipt, command: QualificationCommand, principal: string, category: string) {
  return receipt.operation === command.operation && receipt.category_id === category && receipt.writer_id === principal && receipt.requester_id === principal && receipt.agent_run_id === null && receipt.subject_revision === 1 && receipt.result?.skill_key === command.payload.skill_key && (command.operation === "ai.skill.review.record" ? receipt.subject_type === "skill_review" && receipt.result.case_count === command.payload.cases.length : receipt.subject_type === "skill_qualification" && receipt.result.decision === command.payload.decision && receipt.result.next_revision === command.payload.expected_revision + 1);
}
