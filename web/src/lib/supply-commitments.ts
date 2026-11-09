// D47 supplier commitments (F25, AT-20): a supplier's claim, never stock or an arrival.
import type { SourceRead } from "@/lib/project-plan-view";

export type CommitmentFollowUp = { status: "pending" | "check_due" | "date_unknown" | "closed"; check_due: boolean | null; reason: string };
export type CommitmentBody = {
  commitment_id: string; revision: number; state: "open" | "closed"; build_id: string; material_id: string;
  supplier_ref: string; quantity: string | null; unit: string | null; promised_at: string | null; check_at: string | null;
  original_timezone: string; text: string; responsible_id: string; time_basis: "human_recorded" | "source_claim";
  statement: string | null; last_closure: { result: string; recorded_at: string } | null;
};
export type CommitmentHistory = { id: string; revision: number; action: "create" | "revise" | "close" | "reopen"; state: string; promised_at: string | null; quantity: string | null; unit: string | null; time_basis: string; recorded_at: string; ai_written: boolean };
export type CommitmentView = {
  id: string; commitment_id: string; revision: number; state: "open" | "closed"; build_id: string; material_id: string;
  requester_id: string; ai_written: boolean; source_status: string; body: CommitmentBody; follow_up: CommitmentFollowUp; history: CommitmentHistory[];
};
export type CommitmentLine = {
  item_id: string; material_id: string | null; unit: string | null; required_quantity: string | null;
  commitments: string[]; open_commitments: number; check_due: number;
  actual: { on_hand: Record<string, string | number>; received: Record<string, string | number> };
};
export type CommitmentBoard = {
  build: { id: string; revision: number; name: string; project_id: string; owner_id: string; visibility: string };
  as_of: string; demand_status: string; lines: CommitmentLine[]; commitments: CommitmentView[]; has_more: boolean;
  supply_snapshot_id: string | null; kit_rule: string;
};
export type PromiseDraft = { materialId: string; supplierRef: string; quantity: string; unit: string; promisedLocal: string; text: string; statement: string };
export type CommitmentRecord =
  | { action: "create"; build_id: string; expected_build_revision: number; material_id: string; supplier_ref: string; quantity: string | null; unit: string | null; promised_at: string | null; original_timezone: string; text: string }
  | { action: "revise"; quantity: string | null; unit: string | null; promised_at: string | null; original_timezone: string; text: string }
  | { action: "close"; result: string }
  | { action: "reopen" };
export type CommitmentPayload = { commitment?: { id: string; revision: number }; sources: []; statement: string; reason?: string; record: CommitmentRecord };
export type CommitmentCommand = { command_id: string; idempotency_key: string; product_id: string; expected_revision: number; operation: "supply.commitment.record"; source_read_set: SourceRead[]; payload: CommitmentPayload };

export const blankPromise = (): PromiseDraft => ({ materialId: "", supplierRef: "", quantity: "", unit: "", promisedLocal: "", text: "", statement: "" });
export const followUpNames: Record<CommitmentFollowUp["status"], string> = { pending: "未到检查日", check_due: "已到检查日", date_unknown: "未给承诺日期", closed: "已关闭跟进" };
export const actionNames: Record<CommitmentHistory["action"], string> = { create: "登记", revise: "改期或改量", close: "关闭", reopen: "重开" };
export const basisNames: Record<CommitmentBody["time_basis"], string> = { human_recorded: "本人陈述或本人引用", source_claim: "原文声称（小Pai 引用）" };

export function localZone(): string {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai"; } catch { return "Asia/Shanghai"; }
}

// A datetime-local value carries no zone: the browser interprets it in its own zone.
export function promisedInstant(local: string): string | null {
  if (!local.trim()) return null;
  const value = new Date(local);
  if (Number.isNaN(value.getTime())) throw new Error("承诺日期无法识别，请重新选择。");
  return value.toISOString();
}

function promise(draft: PromiseDraft, zone: string) {
  const text = draft.text.trim(), quantity = draft.quantity.trim(), unit = draft.unit.trim();
  if (!text) throw new Error("请写下供方承诺的原话或要点。");
  if (quantity && !/^\d+(?:\.\d{1,8})?$/.test(quantity)) throw new Error("承诺数量须为非负数字；未知时留空。");
  if (quantity && !unit) throw new Error("已知承诺数量须写单位；未知数量请留空。");
  return { quantity: quantity || null, unit: quantity ? unit : unit || null, promised_at: promisedInstant(draft.promisedLocal), original_timezone: zone, text };
}

function envelope(productId: string, revision: number, payload: CommitmentPayload): CommitmentCommand {
  return { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), product_id: productId, expected_revision: revision, operation: "supply.commitment.record", source_read_set: [], payload };
}

function statementOf(draft: { statement: string }) {
  const statement = draft.statement.trim();
  if (!statement) throw new Error("请写明依据：例如“我与供方电话确认”。没有依据不能登记。");
  return statement;
}

export function createCommand(draft: PromiseDraft, build: { id: string; revision: number }, product: { id: string; revision: number }, zone = localZone()): CommitmentCommand {
  if (!draft.materialId) throw new Error("请选择本轮固定需求中的物料。");
  const supplier = draft.supplierRef.trim();
  if (!supplier) throw new Error("请填写外部供方标识（照来源原样，不建供应商档案）。");
  return envelope(product.id, product.revision, { sources: [], statement: statementOf(draft), record: { action: "create", build_id: build.id, expected_build_revision: build.revision, material_id: draft.materialId, supplier_ref: supplier, ...promise(draft, zone) } });
}

export function reviseCommand(item: CommitmentView, draft: PromiseDraft, product: { id: string; revision: number }, zone = localZone()): CommitmentCommand {
  return envelope(product.id, product.revision, { commitment: { id: item.commitment_id, revision: item.revision }, sources: [], statement: statementOf(draft), record: { action: "revise", ...promise(draft, zone) } });
}

export function closeCommand(item: CommitmentView, result: string, statement: string, product: { id: string; revision: number }): CommitmentCommand {
  if (!result.trim()) throw new Error("请写明关闭原因，例如已登记到货或供方取消。");
  return envelope(product.id, product.revision, { commitment: { id: item.commitment_id, revision: item.revision }, sources: [], statement: statementOf({ statement }), record: { action: "close", result: result.trim() } });
}

export function reopenCommand(item: CommitmentView, reason: string, statement: string, product: { id: string; revision: number }): CommitmentCommand {
  if (!reason.trim()) throw new Error("重开须写明原因。");
  return envelope(product.id, product.revision, { commitment: { id: item.commitment_id, revision: item.revision }, sources: [], statement: statementOf({ statement }), reason: reason.trim(), record: { action: "reopen" } });
}

export function draftFrom(item: CommitmentView): PromiseDraft {
  const at = item.body.promised_at ? new Date(item.body.promised_at) : null;
  const local = at ? new Date(at.getTime() - at.getTimezoneOffset() * 60000).toISOString().slice(0, 16) : "";
  return { materialId: item.material_id, supplierRef: item.body.supplier_ref, quantity: item.body.quantity ?? "", unit: item.body.unit ?? "", promisedLocal: local, text: item.body.text, statement: "" };
}

export function quantityText(quantity: string | null, unit: string | null): string {
  if (quantity == null) return "数量未知";
  const value = quantity.includes(".") ? quantity.replace(/0+$/, "").replace(/\.$/, "") : quantity;
  return `${value} ${unit ?? ""}`.trim();
}

export function actualText(values: Record<string, string | number>): string {
  const entries = Object.entries(values);
  if (!entries.length) return "尚无记录";
  return entries.map(([unit, amount]) => unit === "unknown" ? `${amount} 条数量未知` : quantityText(String(amount), unit)).join("；");
}

export function timeText(value: string | null, zone: string): string {
  if (!value) return "未给出";
  try { return new Intl.DateTimeFormat("zh-CN", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value)); } catch { return value; }
}

export function canMaintain(item: CommitmentView, principalId: string, build: { owner_id: string }, projectOwnerId?: string | null): boolean {
  return [item.body.responsible_id, build.owner_id, projectOwnerId].includes(principalId);
}

export function checkBoard(value: unknown, buildId: string): asserts value is CommitmentBoard {
  const board = value as CommitmentBoard;
  if (!board || typeof board !== "object" || board.build?.id !== buildId || !Array.isArray(board.lines) || !Array.isArray(board.commitments) || typeof board.kit_rule !== "string")
    throw new Error("供方承诺暂时无法按本轮读取，请刷新。");
}
