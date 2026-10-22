export const budgetIntegerMax = 2147483647;
export type BudgetLimits = { limit_micro_usd: number; input_token_limit: number; output_token_limit: number; call_limit: number };
export type AgentBudget = BudgetLimits & { id: string; revision: number; active: boolean; created_at: string; receipt_id: string | null;
  calls: number; held_micro_usd: number; spent_micro_usd: number; held_input_tokens: number; used_input_tokens: number; held_output_tokens: number; used_output_tokens: number };
export type BudgetReading = { can_edit: boolean; category_revision: number; requester_id: string; active_digest: string; control_revision: number;
  selected_budget_id: string | null; active_budgets: AgentBudget[]; items: AgentBudget[]; next_cursor: string | null };
export type BudgetCommand = { category_id: string; product_id: null; command_id: string; idempotency_key: string;
  operation: "ai.budget.configure"; expected_revision: number; source_read_set: [];
  payload: { action: "allocate" | "stop"; expected_active_digest: string; limits: BudgetLimits | null; confirmation_token: string } };
export type BudgetReview = { action: "allocate" | "stop"; scope: "requester"; requester_id: string; expected_active_digest: string;
  control_revision: number; next_revision: number;
  limits: BudgetLimits | null; retired_budgets: { id: string; previous_revision: number; next_revision: number }[]; existing_usage_preserved: true };
export type BudgetPreview = { command: BudgetCommand; expires_at: string; review: BudgetReview };
export type BudgetReceipt = { id: string; operation: string; subject_type: string; subject_id: string; subject_revision: number;
  category_id: string; writer_id: string; requester_id: string; agent_run_id: string | null; result: BudgetReview & { allocated_budget_id: string | null } };

export function dollars(micro: number) {
  const value = BigInt(micro), scale = BigInt(1000000), fraction = String(value % scale).padStart(6, "0").replace(/0+$/, "");
  return `${value / scale}${fraction ? `.${fraction}` : ""}`;
}
export function microDollars(value: string) {
  const match = /^(0|[1-9]\d*)(?:\.(\d{1,6}))?$/.exec(value.trim());
  if (!match) throw new Error("请填写非负 USD 金额，最多六位小数。");
  const amount = BigInt(match[1]) * BigInt(1000000) + BigInt((match[2] ?? "").padEnd(6, "0"));
  if (amount > BigInt(budgetIntegerMax)) throw new Error("金额超出当前可记录范围。");
  return Number(amount);
}
export function validLimits(value: unknown): value is BudgetLimits {
  if (!value || typeof value !== "object") return false;
  const fields = ["limit_micro_usd", "input_token_limit", "output_token_limit", "call_limit"];
  return Object.keys(value).length === fields.length && fields.every(key => {
    const number = (value as Record<string, unknown>)[key];
    return typeof number === "number" && Number.isSafeInteger(number) && number >= (key === "limit_micro_usd" ? 0 : 1) && number <= budgetIntegerMax;
  });
}
export function budgetPendingKey(principalId: string, categoryId: string) { return `pdos-budget-control:v1:${principalId}:${categoryId}`; }
export function parseBudgetPending(raw: string, categoryId: string): BudgetCommand {
  const value = JSON.parse(raw) as BudgetCommand, uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
  const keys = ["category_id", "product_id", "command_id", "idempotency_key", "operation", "expected_revision", "source_read_set", "payload"];
  const payloadKeys = ["action", "expected_active_digest", "limits", "confirmation_token"];
  if (!value || typeof value !== "object" || Object.keys(value).length !== keys.length || Object.keys(value).some(key => !keys.includes(key))
    || value.category_id !== categoryId || value.product_id !== null || value.operation !== "ai.budget.configure"
    || typeof value.command_id !== "string" || !uuid.test(value.command_id) || typeof value.idempotency_key !== "string" || value.idempotency_key.length < 8 || value.idempotency_key.length > 160
    || !Number.isSafeInteger(value.expected_revision) || value.expected_revision < 1 || !Array.isArray(value.source_read_set) || value.source_read_set.length
    || !value.payload || Object.keys(value.payload).length !== payloadKeys.length || Object.keys(value.payload).some(key => !payloadKeys.includes(key))
    || !["allocate", "stop"].includes(value.payload.action) || typeof value.payload.expected_active_digest !== "string" || !/^[a-f0-9]{64}$/.test(value.payload.expected_active_digest)
    || (value.payload.action === "allocate" ? !validLimits(value.payload.limits) : value.payload.limits !== null)
    || typeof value.payload.confirmation_token !== "string" || value.payload.confirmation_token.length < 20 || value.payload.confirmation_token.length > 128) throw new Error("本地原预算请求无法读取，请核对当前预算后处理恢复记录。");
  return value;
}
export function matchBudgetReceipt(receipt: BudgetReceipt, original: BudgetCommand, principalId: string, categoryId: string) {
  const result = receipt.result, limits = original.payload.limits;
  return receipt.operation === "ai.budget.configure" && receipt.subject_type === "agent_budget" && receipt.category_id === categoryId
    && receipt.writer_id === principalId && receipt.requester_id === principalId && receipt.agent_run_id === null
    && result?.scope === "requester" && result.requester_id === principalId && result.existing_usage_preserved === true
    && result.action === original.payload.action && result.expected_active_digest === original.payload.expected_active_digest
    && (limits ? validLimits(result.limits) && (Object.keys(limits) as (keyof BudgetLimits)[]).every(key => limits[key] === result.limits![key]) : result.limits === null)
    && Number.isSafeInteger(result.next_revision) && result.next_revision > result.control_revision && receipt.subject_revision === result.next_revision
    && (original.payload.action === "allocate" ? result.allocated_budget_id === receipt.subject_id
      : result.allocated_budget_id === null && result.retired_budgets?.some(row => row.id === receipt.subject_id && row.next_revision === receipt.subject_revision));
}
