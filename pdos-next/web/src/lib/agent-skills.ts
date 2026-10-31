export type AgentSkill = {
  skill_key: string; purpose: string; skill_version: string | null; skill_digest: string | null;
  available: boolean; operations: string[]; enabled: boolean; revision: number; receipt_id: string | null;
  qualification_record: "recorded" | "not_recorded" | "revoked";
};
export type SkillReading = { items: AgentSkill[]; can_edit: boolean; category_revision: number };
export type SkillCommand = {
  category_id: string; product_id: null; command_id: string; idempotency_key: string;
  operation: "ai.skill.enable"; expected_revision: number; source_read_set: [];
  payload: { skill_key: string; expected_revision: number; enabled: boolean;
    skill_version: string | null; skill_digest: string | null; confirmation_token: string };
};
export type SkillPreview = { command: SkillCommand; expires_at: string; review: {
  skill_key: string; previous_enabled: boolean; enabled: boolean; next_revision: number;
  skill_version: string | null; scope: "tenant"; qualification_changed: false;
} };
export type SkillReceipt = { id: string; operation: string; category_id: string; writer_id: string;
  requester_id: string; agent_run_id: string | null; subject_type: string; subject_revision: number;
  result: { skill_key: string; enabled: boolean; qualification_changed: boolean } };

const titles: Record<string, string> = { category_framing: "品类边界澄清", competitor_comparison: "竞品比较", derivative_diff: "派生差异分析", gap_check: "资料查漏", jtbd: "用户任务分析", opportunity_scoring: "机会评估", option_comparison: "方案比较", price_band: "价格带分析", proposal_drafting: "立项提案起草", public_research: "公开研究", review_pain_clustering: "用户痛点归类", rfq_extraction: "客户要求抽取" };
export function skillTitle(key: string) { return ({ build_execution: "试制与制造准备", quality_issue: "质量问题与整改", test_verification: "测试与验证", change_control: "变更控制", release_handover: "发布与交接", work_management: "项目行动与承诺", ...titles } as Record<string, string>)[key] ?? key; }
export function skillPendingKey(principalId: string, categoryId: string) { return `pdos-skill-toggle:v1:${principalId}:${categoryId}`; }

export function parseSkillPending(raw: string, categoryId: string): SkillCommand {
  const value = JSON.parse(raw) as SkillCommand;
  const keys = ["category_id", "product_id", "command_id", "idempotency_key", "operation", "expected_revision", "source_read_set", "payload"];
  const payloadKeys = ["skill_key", "expected_revision", "enabled", "skill_version", "skill_digest", "confirmation_token"];
  const revision = (number: unknown) => Number.isSafeInteger(number) && (number as number) >= 0;
  if (!value || typeof value !== "object" || Object.keys(value).length !== keys.length || Object.keys(value).some(key => !keys.includes(key))
    || value.category_id !== categoryId || value.product_id !== null || value.operation !== "ai.skill.enable"
    || typeof value.command_id !== "string" || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value.command_id) || typeof value.idempotency_key !== "string" || value.idempotency_key.length < 8 || value.idempotency_key.length > 160
    || !revision(value.expected_revision) || value.expected_revision < 1 || !Array.isArray(value.source_read_set) || value.source_read_set.length
    || !value.payload || Object.keys(value.payload).length !== payloadKeys.length || Object.keys(value.payload).some(key => !payloadKeys.includes(key))
    || typeof value.payload.skill_key !== "string" || !value.payload.skill_key || value.payload.skill_key.length > 160
    || !revision(value.payload.expected_revision) || typeof value.payload.enabled !== "boolean"
    || !(value.payload.skill_version === null || typeof value.payload.skill_version === "string" && !!value.payload.skill_version && value.payload.skill_version.length <= 160)
    || !(value.payload.skill_digest === null || typeof value.payload.skill_digest === "string" && /^[a-f0-9]{64}$/.test(value.payload.skill_digest))
    || (value.payload.skill_version === null) !== (value.payload.skill_digest === null)
    || typeof value.payload.confirmation_token !== "string" || value.payload.confirmation_token.length < 20 || value.payload.confirmation_token.length > 128) throw new Error("本地原技能请求无法读取，请核对当前状态后处理恢复记录。");
  return value;
}

export function matchSkillReceipt(receipt: SkillReceipt, original: SkillCommand, principalId: string, categoryId: string) {
  return receipt.operation === "ai.skill.enable" && receipt.subject_type === "skill_enablement" && receipt.category_id === categoryId
    && receipt.writer_id === principalId && receipt.requester_id === principalId && receipt.agent_run_id === null
    && receipt.subject_revision === original.payload.expected_revision + 1
    && receipt.result?.skill_key === original.payload.skill_key && receipt.result.enabled === original.payload.enabled
    && receipt.result.qualification_changed === false;
}
