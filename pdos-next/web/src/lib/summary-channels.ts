import type { WorkspaceApi } from "./automation-rules";

export type SummaryChannelOptions = { version: "personal-summary-channels/v1"; principal_id: string; configured: boolean; bindings: { binding_id: string; epoch: number; application_id: string; application_revision: number }[] };
export type SummaryDeliveryReceipt = { delivery_id: string; run_id: string; state: "planned" | "sending" | "delivered" | "unknown" | "blocked" | "cancelled"; attempts: number; error_code: string | null };
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const uuid = (v: unknown): v is string => typeof v === "string" && /^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/i.test(v);
export async function readSummaryChannels(api: WorkspaceApi, principalId: string): Promise<SummaryChannelOptions> {
  const v = await api<unknown>("v1/personal/inbox/summary-channels");
  if (!object(v) || v.version !== "personal-summary-channels/v1" || v.principal_id !== principalId || typeof v.configured !== "boolean" || !Array.isArray(v.bindings) || !v.bindings.every(b => object(b) && uuid(b.binding_id) && uuid(b.application_id) && Number.isSafeInteger(b.epoch) && Number(b.epoch) > 0 && Number.isSafeInteger(b.application_revision) && Number(b.application_revision) > 0)) throw new Error("本人摘要投递绑定尚未核实。");
  return v as SummaryChannelOptions;
}
export function summaryReceipt(v: unknown): v is SummaryDeliveryReceipt { return object(v) && uuid(v.delivery_id) && uuid(v.run_id) && ["planned", "sending", "delivered", "unknown", "blocked", "cancelled"].includes(String(v.state)) && Number.isSafeInteger(v.attempts) && Number(v.attempts) >= 0 && (v.error_code === null || typeof v.error_code === "string"); }
export async function readSummaryReceipts(api: WorkspaceApi, principalId: string): Promise<SummaryDeliveryReceipt[]> {
  const v = await api<unknown>("v1/personal/inbox/summary-deliveries");
  if (!object(v) || v.principal_id !== principalId || !Array.isArray(v.items) || !v.items.every(summaryReceipt)) throw new Error("本人摘要投递回执尚未核实。");
  return v.items;
}
export async function reconcileSummaryReceipt(api: WorkspaceApi, deliveryId: string): Promise<SummaryDeliveryReceipt> {
  if (!uuid(deliveryId)) throw new Error("请从原摘要投递回执继续。");
  const v = await api<unknown>(`v1/personal/inbox/summary-deliveries/${deliveryId}/reconcile`, {});
  if (!summaryReceipt(v) || v.delivery_id !== deliveryId) throw new Error("尚未核对到原投递回执，可稍后继续查询。");
  return v;
}
