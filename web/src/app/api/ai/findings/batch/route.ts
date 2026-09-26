import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";
export async function POST(request: Request) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const body = await readBoundedJson(request, 2_000_000);
    return forwardJson(await pdosApiFetch("/api/ai/findings/batch", { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(body) }));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST", "批量内容过大或格式不正确，请缩小本组范围");
    return sessionError(503, "FINDING_BATCH_UNAVAILABLE", "批次结果尚未确认，请读取原请求回执");
  }
}
