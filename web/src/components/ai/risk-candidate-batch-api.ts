import { isRecord, responseBody } from "@/components/workspace-api";

export type RiskBatchRequest = {
  request_id: string;
  items: { risk_id: string; expected_updated_at: string }[];
};
export type RiskBatchReceipt = {
  request_id: string; project_id: string; actor_user_id: string; created_at: string; replayed: boolean;
  results: { risk_id: string; title: string; description: string | null; score: number; updated_at: string }[];
  current: { id: string; draft_state: string; status: string; updated_at: string }[];
};
export class RiskBatchError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function riskBatch(projectId: string, request: RiskBatchRequest | string): Promise<RiskBatchReceipt> {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/risk-candidates/batches${typeof request === "string" ? `/${encodeURIComponent(request)}` : ""}`, {
    method: typeof request === "string" ? "GET" : "POST", cache: "no-store", credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: typeof request === "string" ? undefined : JSON.stringify(request),
  });
  const body = await responseBody(response);
  if (!response.ok) {
    const detail = isRecord(body) && isRecord(body.detail) ? body.detail : body;
    throw new RiskBatchError(isRecord(detail) && typeof detail.message === "string" ? detail.message : "风险确认回执暂不可用", response.status);
  }
  if (!isRecord(body) || body.project_id !== projectId ||
      body.request_id !== (typeof request === "string" ? request : request.request_id) ||
      typeof body.actor_user_id !== "string" || typeof body.created_at !== "string" ||
      typeof body.replayed !== "boolean" || !Array.isArray(body.results) || !Array.isArray(body.current) ||
      !body.results.every((v) => isRecord(v) && typeof v.risk_id === "string" && typeof v.title === "string" &&
        (v.description === null || typeof v.description === "string") && typeof v.score === "number" && typeof v.updated_at === "string") ||
      !body.current.every((v) => isRecord(v) && typeof v.id === "string" && typeof v.draft_state === "string" &&
        typeof v.status === "string" && typeof v.updated_at === "string")) throw new Error("确认回执格式异常，请用原请求编号回查");
  return body as RiskBatchReceipt;
}

export async function rescanRiskCandidates(projectId: string) {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/risk-candidates/scan`, {
    method: "POST", cache: "no-store", credentials: "same-origin",
  });
  if (!response.ok) throw new Error("重新扫描失败，请稍后重试");
}
