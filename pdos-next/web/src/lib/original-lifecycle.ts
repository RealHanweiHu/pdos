export type LifecycleAction = "quarantine" | "restore";
export type LifecycleIntent = {
  id: string; action: string; state: string; revision: number; recovery_required: boolean;
  created_at: string | null; updated_at: string | null; reason: string;
  can_cancel: boolean; can_reconcile: boolean;
};
export type LifecycleItem = {
  id: string; title: string; filename: string; revision: number; registered: boolean | null;
  upload_state: string; parse_state: string; retention_until: string | null; manual_hold: boolean | null;
  disposition: string; pending_intent_id: string | null; reference_count: number | null;
  formal_history: boolean | null; coverage_complete: boolean; registration_state: string; byte_status: string;
  reasons: string[]; can_quarantine: boolean; can_restore: boolean; can_record_protection: boolean;
  can_abandon_upload: boolean; upload_attempt_id: string | null; upload_attempt_revision: number | null;
  policy_version: string | null; intents: LifecycleIntent[];
};
export type LifecyclePolicy = { version: string; profile: "local-synthetic" | "configured"; failed_upload_grace_seconds: number; quarantine_grace_seconds: number };
export type LifecycleInventory = { items: LifecycleItem[]; policy: LifecyclePolicy | null; coverage_complete: boolean };
export type LifecycleCandidate = {
  candidate_id: string; action: LifecycleAction; object_id: string; digest: string;
  eligible: boolean; reasons: string[]; captured_at: string; not_before: string | null;
  lifecycle_revision?: number; object_version?: number; policy_version?: string;
   content_sha256?: string; size_bytes?: number; media_type?: string;
  inventory_revision?: string; reference_read_version?: string; policy_digest?: string;
};
export type LifecycleOperation = "evidence.lifecycle.quarantine" | "evidence.lifecycle.restore" | "evidence.lifecycle.cancel" | "evidence.lifecycle.protection.record" | "evidence.lifecycle.upload.abandon";
export type LifecyclePayload = { candidate_id: string; digest: string; reason: string; confirmation_token?: string | null }
  | { intent_id: string; expected_revision: number; reason: string; confirmation_token?: string | null }
  | { object_id: string; expected_revision: number; manual_hold: boolean; retention_until: string; reason: string; confirmation_token?: string | null }
  | { object_id: string; expected_revision: number; reason: string; confirmation_token?: string | null };
export type LifecycleCommand = { command_id: string; idempotency_key: string; operation: LifecycleOperation; product_id: string; expected_revision: number; source_read_set: []; payload: LifecyclePayload };
type PayloadFields<T> = T extends unknown ? Omit<T, "reason" | "confirmation_token"> : never;
export type LifecycleFields = PayloadFields<LifecyclePayload>;
export type LifecycleReview = { before: Record<string, unknown>; after: Record<string, unknown>; effect: string; operation?: string; reason?: string };
export type LifecyclePreview = { command: LifecycleCommand; expires_at: string; review: LifecycleReview };
export type LifecyclePending = { stage: "candidate"; itemId: string; action: LifecycleAction; scope: string }
  | { stage: "preview" | "execute"; command: LifecycleCommand; itemId: string; scope: string }
  | { stage: "reconcile"; itemId: string; intentId: string; scope: string };

export const lifecycleActionNames: Record<string, string> = { quarantine: "隔离访问位置", restore: "恢复访问位置", cancel: "取消尚未执行的意图", protection: "记录人工保留", abandon: "终止未完成上传" };
export const intentStateNames: Record<string, string> = { pending: "意图已登记 · 尚未执行", in_flight: "正在核对实际动作", unknown: "实际结果未知 · 仅核对原意图", applied: "实际动作已核实完成", not_applied: "已核实未执行", cancelled: "尚未执行的意图已取消" };
export const lifecycleUploadNames: Record<string, string> = { pending: "上传未完成", succeeded: "上传已完成", failed: "上传已失败", abandoned: "未完成上传已具名终止", unknown: "上传结果尚未知" };
export const lifecycleParseNames: Record<string, string> = { not_requested: "尚未请求解析", queued: "等待解析", running: "正在解析", parsed: "已形成定位文字", failed: "解析失败 · 保留原件", needs_ocr: "需要文字识别", unknown: "解析状态未知" };
export const dispositionNames: Record<string, string> = { active: "正常访问位置 · 字节仍保留", quarantined: "访问位置已隔离 · 字节仍保留", purged: "收到不可用位置记录 · 需核对", unknown: "字节位置尚未知 · 不推定删除" };
const reasonNames: Record<string, string> = {
  reference_unknown: "完整引用范围未知，保持保护。", referenced: "已有业务引用，不能按孤儿回收。", formal_history: "涉及正式历史，保持保护。",
  hold_unknown: "人工保留状态未知，保持保护。", manual_hold: "有人工暂缓处理要求，保持保护。", registration_unknown: "登记状态未知，不能判为孤儿。",
  registered_original: "已登记原件受保护，解析失败也不是孤儿文件。", upload_not_terminal: "上传尚未形成明确终态，不能判为孤儿。",
  upload_time_unknown: "上传终态时点未知，保持保护。", parse_unknown: "解析状态尚未知。", parse_in_progress: "解析仍在进行，保持保护。",
  derivation_present: "已有派生文字或文字识别需求，保持保护。", retention_unknown: "保留期限尚未核实，保持保护。",
  retention_not_elapsed: "仍在保留期限内，保持保护。", state_unknown: "字节位置尚未知，需要核对。", wrong_disposition: "当前访问位置不适用此动作。",
  effect_pending: "已有未确定的生命周期意图，请先核对原意图。", quarantine_time_unknown: "隔离时点未知，需要核对。",
  fact_time_invalid: "事实时点不符合当前核对要求。", facts_stale: "保护事实已变化，请刷新核对。",
  LIFECYCLE_TRANSPORT_UNAVAILABLE: "真实可逆存储操作当前不可用，不能视为隔离或恢复成功。", REFERENCE_COVERAGE_UNPROVEN: "完整引用范围尚未证实，保持保护。",
};
export const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const stringOrNull = (value: unknown) => typeof value === "string" ? value : null;
const booleanOrNull = (value: unknown) => typeof value === "boolean" ? value : null;
const positiveInteger = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const stringList = (value: unknown) => Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
export function lifecycleReason(value: string): string { return reasonNames[value] ?? "当前保护事实或操作依据仍需核对。"; }
export function lifecycleTime(value: string | null | undefined): string { return value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "尚未核实"; }
export function awareTimestamp(value: string): boolean { return /T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/i.test(value) && Number.isFinite(Date.parse(value)); }
export function canonicalLifecycleTime(value: unknown): string | null {
  if (typeof value !== "string" || !awareTimestamp(value)) return null;
  const fraction = value.match(/\.(\d+)(?=Z|[+-]\d{2}:\d{2}$)/i)?.[1] ?? "";
  if (fraction.length > 6) return null;
  const wholeSecond = new Date(Date.parse(value.replace(/\.\d+(?=Z|[+-]\d{2}:\d{2}$)/i, ""))).toISOString();
  const microseconds = fraction.padEnd(6, "0").replace(/0+$/, "");
  return wholeSecond.replace(/\.000Z$/, `${microseconds ? `.${microseconds}` : ""}Z`);
}
export function normalizeInventory(value: unknown): LifecycleInventory {
  if (!isRecord(value) || !Array.isArray(value.items)) throw new Error("尚未取得完整的原件库存，请刷新核对。");
  const items: LifecycleItem[] = value.items.map(raw => {
    if (!isRecord(raw) || typeof raw.id !== "string" || !raw.id || typeof raw.title !== "string" || !positiveInteger(raw.revision)) throw new Error("原件库存记录尚不完整，请刷新核对。");
    const intents = Array.isArray(raw.intents) ? raw.intents.filter(isRecord).filter(row => typeof row.id === "string" && positiveInteger(row.revision)).map(row => ({
      id: String(row.id), revision: Number(row.revision), action: typeof row.action === "string" ? row.action : "unknown", state: typeof row.state === "string" ? row.state : "unknown",
      recovery_required: row.recovery_required === true, created_at: stringOrNull(row.created_at), updated_at: stringOrNull(row.updated_at), reason: typeof row.reason === "string" ? row.reason : "",
      can_cancel: row.can_cancel === true, can_reconcile: row.can_reconcile === true,
    })) : [];
    return {
      id: raw.id, title: raw.title, filename: typeof raw.filename === "string" ? raw.filename : "文件名尚未知", revision: raw.revision,
      registered: booleanOrNull(raw.registered), upload_state: typeof raw.upload_state === "string" ? raw.upload_state : "unknown", parse_state: typeof raw.parse_state === "string" ? raw.parse_state : "unknown",
      retention_until: stringOrNull(raw.retention_until), manual_hold: booleanOrNull(raw.manual_hold), disposition: typeof raw.disposition === "string" ? raw.disposition : "unknown",
      pending_intent_id: stringOrNull(raw.pending_intent_id), reference_count: typeof raw.reference_count === "number" && Number.isSafeInteger(raw.reference_count) && raw.reference_count >= 0 ? raw.reference_count : null,
      formal_history: booleanOrNull(raw.formal_history), coverage_complete: raw.coverage_complete === true,
      registration_state: typeof raw.registration_state === "string" ? raw.registration_state : "unknown", byte_status: typeof raw.byte_status === "string" ? raw.byte_status : "unknown",
      reasons: stringList(raw.reasons), can_quarantine: raw.can_quarantine === true, can_restore: raw.can_restore === true, can_record_protection: raw.can_record_protection === true,
      can_abandon_upload: raw.can_abandon_upload === true, upload_attempt_id: stringOrNull(raw.upload_attempt_id), upload_attempt_revision: positiveInteger(raw.upload_attempt_revision) ? raw.upload_attempt_revision : null,
      policy_version: stringOrNull(raw.policy_version), intents,
    };
  });
  const rawPolicy = value.policy;
  const policy = isRecord(rawPolicy) && typeof rawPolicy.version === "string" && ["local-synthetic", "configured"].includes(String(rawPolicy.profile))
    && typeof rawPolicy.failed_upload_grace_seconds === "number" && rawPolicy.failed_upload_grace_seconds > 0
    && typeof rawPolicy.quarantine_grace_seconds === "number" && rawPolicy.quarantine_grace_seconds > 0 ? rawPolicy as unknown as LifecyclePolicy : null;
  return { items, policy, coverage_complete: value.coverage_complete === true };
}
export function validLifecycleCandidate(value: unknown, item: LifecycleItem, action: LifecycleAction): value is LifecycleCandidate {
  return isRecord(value) && typeof value.candidate_id === "string" && !!value.candidate_id && value.action === action && value.object_id === item.id
    && typeof value.digest === "string" && /^[0-9a-f]{64}$/.test(value.digest) && typeof value.eligible === "boolean"
    && Array.isArray(value.reasons) && value.reasons.every(reason => typeof reason === "string") && typeof value.captured_at === "string" && awareTimestamp(value.captured_at)
    && (value.not_before === null || typeof value.not_before === "string" && awareTimestamp(value.not_before))
    && (value.lifecycle_revision === undefined || value.lifecycle_revision === item.revision);
}
function stable(value: unknown): unknown { return Array.isArray(value) ? value.map(stable) : isRecord(value) ? Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])])) : value; }
export const sameLifecycleValue = (left: unknown, right: unknown): boolean => JSON.stringify(stable(left)) === JSON.stringify(stable(right));
export function lifecycleScope(productId: string, productRevision: number, item: LifecycleItem): string {
  return JSON.stringify(stable({ productId, productRevision, itemId: item.id, revision: item.revision, registered: item.registered, retention_until: item.retention_until, manual_hold: item.manual_hold,
    disposition: item.disposition, pending_intent_id: item.pending_intent_id, reference_count: item.reference_count, formal_history: item.formal_history, coverage_complete: item.coverage_complete,
    policy_version: item.policy_version, can_quarantine: item.can_quarantine, can_restore: item.can_restore, can_record_protection: item.can_record_protection,
    can_abandon_upload: item.can_abandon_upload, upload_attempt_revision: item.upload_attempt_revision, intents: item.intents.map(intent => [intent.id, intent.revision, intent.state, intent.can_cancel, intent.can_reconcile]) }));
}
export function lifecycleCommand(productId: string, productRevision: number, item: LifecycleItem, operation: LifecycleOperation, fields: LifecycleFields, reason: string, commandId: string, requestKey: string): LifecycleCommand {
  const cleaned = reason.trim(), minimumReasonLength = operation === "evidence.lifecycle.upload.abandon" ? 4 : 1;
  if (cleaned.length < minimumReasonLength || cleaned.length > 2000) throw new Error(`请填写 ${minimumReasonLength}–2000 字的具名核对原因。`);
  if (!positiveInteger(productRevision)) throw new Error("型号版本尚未取得，请刷新核对。");
  if (operation === "evidence.lifecycle.quarantine" && !item.can_quarantine || operation === "evidence.lifecycle.restore" && !item.can_restore || operation === "evidence.lifecycle.protection.record" && !item.can_record_protection || operation === "evidence.lifecycle.upload.abandon" && !item.can_abandon_upload) throw new Error("服务器当前不允许此动作，请刷新核对权限与保护事实。");
  if (operation === "evidence.lifecycle.cancel") {
    if (!("intent_id" in fields) || !item.intents.some(intent => intent.id === fields.intent_id && intent.revision === fields.expected_revision && intent.can_cancel)) throw new Error("服务器当前不允许取消此固定意图，请刷新核对。");
  } else if (operation === "evidence.lifecycle.protection.record") {
    if (!("manual_hold" in fields) || fields.object_id !== item.id || fields.expected_revision !== item.revision || typeof fields.manual_hold !== "boolean" || !canonicalLifecycleTime(fields.retention_until)) throw new Error("人工保留须绑定当前原件版本、明确暂缓选择和带时区的真实期限；时间小数最多六位。");
  } else if (operation === "evidence.lifecycle.upload.abandon") {
    if (!("object_id" in fields) || fields.object_id !== item.id || fields.expected_revision !== item.upload_attempt_revision || !item.upload_attempt_id) throw new Error("请核对当前上传登记与版本后再终止。");
  } else if (!("candidate_id" in fields) || !fields.candidate_id || !/^[0-9a-f]{64}$/.test(fields.digest)) throw new Error("请先取得绑定当前原件的服务器候选。");
  return { command_id: commandId, idempotency_key: requestKey, operation, product_id: productId, expected_revision: productRevision, source_read_set: [], payload: { ...fields, reason: cleaned } as LifecyclePayload };
}
export function validLifecyclePreview(value: unknown, original: LifecycleCommand, item: LifecycleItem, now = Date.now()): value is LifecyclePreview {
  if (!isRecord(value) || !isRecord(value.command) || !isRecord(value.command.payload) || !isRecord(value.review) || !isRecord(value.review.before) || !isRecord(value.review.after)
    || typeof value.review.effect !== "string" || !value.review.effect.trim() || typeof value.expires_at !== "string" || !awareTimestamp(value.expires_at) || Date.parse(value.expires_at) <= now) return false;
  const command = value.command, fields = command.payload; if (!isRecord(fields)) return false;
  const payload = { ...fields }; delete payload.confirmation_token;
  const originalPayload = { ...original.payload };
  if (original.operation === "evidence.lifecycle.protection.record") {
    const receivedTime = canonicalLifecycleTime(payload.retention_until), requestedTime = "retention_until" in originalPayload ? canonicalLifecycleTime(originalPayload.retention_until) : null;
    if (!receivedTime || !requestedTime || receivedTime !== requestedTime) return false;
    payload.retention_until = receivedTime;
    if ("retention_until" in originalPayload) originalPayload.retention_until = requestedTime;
  }
  if (!["command_id", "idempotency_key", "operation", "product_id", "expected_revision"].every(key => command[key] === original[key as keyof LifecycleCommand])
    || !sameLifecycleValue(command.source_read_set, original.source_read_set) || typeof fields.confirmation_token !== "string" || !fields.confirmation_token
    || !sameLifecycleValue(payload, originalPayload) || value.review.operation !== undefined && value.review.operation !== original.operation) return false;
  const before = value.review.before, after = value.review.after, input = original.payload;
  if ("candidate_id" in input) return before.object_id === item.id && before.candidate_id === input.candidate_id && before.digest === input.digest && before.eligible === true && before.action === original.operation.split(".").at(-1) && after.action === before.action && after.status === "pending" && after.reason === input.reason && after.physical_effect_applied === false;
  if ("intent_id" in input) return before.object_id === item.id && before.intent_id === input.intent_id && before.revision === input.expected_revision && before.attempted === false && after.state === "cancelled" && after.reason === input.reason && after.physical_effect_applied === false;
  if ("manual_hold" in input) return before.object_id === input.object_id && before.revision === input.expected_revision && after.object_id === input.object_id && after.manual_hold === input.manual_hold && canonicalLifecycleTime(after.retention_until) === canonicalLifecycleTime(input.retention_until) && after.reason === input.reason;
  return before.id === input.object_id && before.revision === input.expected_revision && before.status === "reserved" && after.status === "abandoned" && after.reason === input.reason;
}
export function validLifecycleReceipt(value: unknown, command: LifecycleCommand, item: LifecycleItem): boolean {
  if (!isRecord(value) || typeof value.id !== "string" || !value.id || typeof value.subject_id !== "string" || !value.subject_id || value.operation !== command.operation) return false;
  if (command.operation === "evidence.lifecycle.protection.record") return value.subject_type === "original_lifecycle_object" && value.subject_id === item.id;
  if (command.operation === "evidence.lifecycle.upload.abandon") return value.subject_type === "upload_attempt" && value.subject_id === item.upload_attempt_id;
  return value.subject_type === "original_lifecycle_intent" && (!("intent_id" in command.payload) || value.subject_id === command.payload.intent_id);
}
export function lifecycleFailure(failure: unknown): { status?: number; message: string } {
  const value = isRecord(failure) ? failure : {}, status = typeof value.status === "number" ? value.status : undefined;
  const known = typeof value.code === "string" ? reasonNames[value.code] : undefined;
  return { status, message: known ?? (status === 401 || status === 403 ? "当前会话或原件范围不可用，请核对授权后刷新。" : [400, 404, 409, 410, 422].includes(status ?? 0) ? "当前事实、权限或候选已变化，请刷新后重新核对；未按旧依据继续操作。" : "尚未取得确定回执，请保留原请求核对结果。") };
}
