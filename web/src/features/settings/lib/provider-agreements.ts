export const agreementCategories = {
  public: "公开资料", synthetic: "合成资料", internal: "内部资料",
  customer: "客户身份与资料", customer_original: "客户原件全文",
} as const;
export type AgreementCategory = keyof typeof agreementCategories;
export type AgreementRequest = {
  provider: string; expected_revision: number; signed_on: string; expires_at: string;
  data_categories: AgreementCategory[]; retention_terms: string; training_terms: string;
  prompt_cache_allowed?: boolean | null;
  active: boolean; decision: "批准"; idempotency_key: string;
};
export type Agreement = Omit<AgreementRequest, "expected_revision" | "decision" | "idempotency_key"> & {
  id: string; revision: number; registered_by: string; registered_by_name: string | null;
  receipt_id: string | null; status: "active" | "inactive" | "expired" | "not_started";
};
export type AgreementReading = { items: Agreement[]; can_edit: boolean; next_cursor: string | null; as_of: string };
export type AgreementReceipt = {
  id: string; category_id: string; operation: string; subject_type: string; subject_id: string;
  subject_revision: number; writer_id: string; requester_id: string; agent_run_id: string | null;
  result: { provider: string; revision: number; tier: string; decided_by: string; decision: string; prompt_cache_allowed?: boolean | null };
};

export function validateAgreement(value: AgreementRequest, instant = Date.now()): string | null {
  if (!/^[A-Za-z0-9][A-Za-z0-9:_.@/-]{0,159}$/.test(value.provider)) return "请填写与服务端配置一致的服务商标识。";
  if (!Number.isSafeInteger(value.expected_revision) || value.expected_revision < 0) return "请重新读取当前协议版本。";
  if (!value.data_categories.length || value.data_categories.some(key => !Object.hasOwn(agreementCategories, key))) return "请选择协议明确允许的数据类别。";
  if (value.retention_terms.trim().length < 3 || value.training_terms.trim().length < 3) return "请按已签约协议填写留存和训练条款。";
  if (value.prompt_cache_allowed != null && typeof value.prompt_cache_allowed !== "boolean") return "请明确选择是否允许提示缓存。";
  const signed = Date.parse(value.signed_on), expires = Date.parse(value.expires_at);
  if (!Number.isFinite(signed) || !Number.isFinite(expires) || signed > instant || expires <= instant || expires <= signed) return "请核对签约时间和未来的到期时间。";
  return null;
}

export function agreementPendingKey(principalId: string, categoryId: string) {
  return `pdos-provider-agreement:v1:${principalId}:${categoryId}`;
}

export function parseAgreementPending(raw: string): AgreementRequest {
  const value = JSON.parse(raw) as Record<string, unknown>;
  const keys = ["provider", "expected_revision", "signed_on", "expires_at", "data_categories", "retention_terms", "training_terms", "active", "decision", "idempotency_key"];
  if (!value || typeof value !== "object" || keys.some(key => !Object.hasOwn(value, key)) || Object.keys(value).some(key => !keys.includes(key) && key !== "prompt_cache_allowed")
    || typeof value.provider !== "string" || typeof value.signed_on !== "string" || typeof value.expires_at !== "string"
    || typeof value.retention_terms !== "string" || typeof value.training_terms !== "string"
    || typeof value.active !== "boolean" || value.decision !== "批准" || typeof value.idempotency_key !== "string"
    || value.idempotency_key.length < 8 || value.idempotency_key.length > 160
    || !Array.isArray(value.data_categories) || value.data_categories.some(key => typeof key !== "string" || !Object.hasOwn(agreementCategories, key))) throw new Error("本地原登记请求无法读取，请核对当前登记后处理恢复记录。");
  // An expired original still needs recovery; never change its approved dates or key.
  const request = value as AgreementRequest;
  if (validateAgreement(request, Date.parse(request.signed_on)) !== null) throw new Error("本地原登记请求无效，请核对当前登记后处理恢复记录。");
  return request;
}

export function matchAgreementReceipt(receipt: AgreementReceipt, request: AgreementRequest, principalId: string, categoryId: string) {
  return receipt.operation === "provider.agreement.register" && receipt.subject_type === "provider_agreement"
    && receipt.category_id === categoryId && receipt.writer_id === principalId && receipt.requester_id === principalId
    && receipt.agent_run_id === null && receipt.subject_revision === request.expected_revision + 1
    && receipt.result?.provider === request.provider && receipt.result.revision === request.expected_revision + 1
    && receipt.result.tier === "T2" && receipt.result.decided_by === principalId && receipt.result.decision === "批准"
    && (receipt.result.prompt_cache_allowed ?? null) === (request.prompt_cache_allowed ?? null);
}
