import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ spaceId: string; operation: string }> };
const operations = ["options", "study-create", "study-history", "consent", "sample-preview", "sample-save", "sample-history", "sample-read", "summary"];
export async function POST(request: Request, context: Context) {
  const { spaceId, operation } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(spaceId) || !operations.includes(operation)) return sessionError(404, "UNKNOWN_OPERATION", "立项前投入观察入口不存在");
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "LOGIN_REQUIRED", "需要登录");
  try {
    const body = await readBoundedJson(request, 262_144);
    return forwardJson(await pdosApiFetch("/api/product-work/spaces/" + spaceId + "/research-measurement/" + operation, { method: "POST", headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" }, body: JSON.stringify(body) }, 15_000));
  } catch (error) {
    return error instanceof InvalidRequestBodyError ? sessionError(400, "INVALID_REQUEST", "请提供有效且大小适当的观察资料") : sessionError(503, "RESEARCH_MEASUREMENT_UNAVAILABLE", "投入观察暂不可用，请按原请求重试");
  }
}
