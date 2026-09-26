import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string; specificationId: string }> };
async function forward(request: Request, context: Context) {
  const { projectId, specificationId } = await context.params;
  if (![projectId, specificationId].every(id => /^[0-9a-f-]{36}$/i.test(id))) return sessionError(400, "INVALID_REQUEST", "规格编号无效");
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "请先登录");
  const before = request.method === "GET" ? new URL(request.url).searchParams.get("before_id") : null;
  if (before && !/^[1-9][0-9]*$/.test(before)) return sessionError(400, "INVALID_REQUEST", "历史分页编号无效");
  try {
    const body = request.method === "POST" ? JSON.stringify(await readBoundedJson(request)) : undefined;
    return forwardJson(await pdosApiFetch(`/api/projects/${projectId}/product-engineering/specifications/${specificationId}/owner-transfer${before ? `?before_id=${before}` : ""}`, {
      method: request.method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body,
    }));
  } catch (error) {
    return sessionError(error instanceof InvalidRequestBodyError ? 400 : 503, "SPECIFICATION_TRANSFER_UNAVAILABLE", "规格接续结果待确认，请按原请求重试");
  }
}
export const GET = forward;
export const POST = forward;
