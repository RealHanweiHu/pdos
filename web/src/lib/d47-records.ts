// D47 (P95–P97, P100) shared view helpers for the named-person record chains.
export type VersionRef = { id: string; revision: number };
export type HistoryRow = { id: string; record_id: string; revision: number; action: string; state: string; actor_id: string; recorded_at: string; body: Record<string, unknown> };
export type ExactSourceRef = { id: string; revision: number; kind: "artifact"; position: string };

export const actionNames: Record<string, string> = {
  create: "建立", revise: "修订", confirm: "确认", dispute: "提出异议", accept: "接受", reject: "拒绝", revoke: "撤销", approve: "批准",
};
export const confirmationNames: Record<string, string> = { pending: "待确认", confirmed: "已确认", disputed: "有异议", superseded: "已取代" };
export const fixtureStateNames: Record<string, string> = { accepted: "已验收", rejected: "未通过", revoked: "已撤销" };
export const alternateStateNames: Record<string, string> = { approved: "已批准", revoked: "已撤销" };
export const scopeNames: Record<string, string> = {
  appearance: "外观", dimensions: "尺寸", performance: "性能", packaging_labeling: "包装标识", certification_docs: "认证资料",
};
export const scopeStateNames: Record<string, string> = {
  accepted: "承认", conditionally_accepted: "条件承认", not_accepted: "未承认", not_applicable: "不涉及",
};
export const acceptanceStateNames: Record<string, string> = { accepted: "全部承认", conditional: "条件承认", not_accepted: "有未承认项" };
export const outcomeNames: Record<string, string> = { effective: "有效（关闭问题）", ineffective: "无效（回到措施中）", extend_observation: "延长观察" };

export function lines(text: string): string[] { return text.split(/\r?\n/); }

export async function sha256Hex(text: string): Promise<string> {
  const data = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(hash)).map(byte => byte.toString(16).padStart(2, "0")).join("");
}

// The server rechecks the exact line and quote digest; the page only names them.
export async function exactSource(source: { id: string; revision: number; content: string }, line: number): Promise<ExactSourceRef> {
  const text = lines(source.content)[line - 1];
  if (text === undefined || !text.trim()) throw new Error("所选行在原文中不存在或为空。");
  return { id: source.id, revision: source.revision, kind: "artifact", position: `line:${line};quote_sha256:${await sha256Hex(text)}` };
}

export function isoFromLocal(local: string): string | null {
  if (!local.trim()) return null;
  const value = new Date(local);
  if (Number.isNaN(value.getTime())) throw new Error("日期无法识别，请重新选择。");
  return value.toISOString();
}

export function timeText(value: string | null | undefined): string {
  if (!value) return "未设";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

export function splitLines(text: string): string[] { return text.split(/\n/).map(item => item.trim()).filter(Boolean); }
