import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ spaceId: string; operation: string }> };
const operations = ["options", "create", "history", "read", "delivery-preview", "delivery-save", "reception-preview", "reception-save", "close-preview", "close", "summary", "study-summary"];
export async function POST(request: Request, context: Context) {
  const { spaceId, operation } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(spaceId) || !operations.includes(operation)) return sessionError(404, "UNKNOWN_OPERATION", "立项前多人观察入口不存在");
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "LOGIN_REQUIRED", "需要登录");
  try {
    const body = await readBoundedJson(request, 65_536);
    return forwardJson(await pdosApiFetch("/api/product-work/spaces/" + spaceId + "/research-workpacks/" + operation, { method: "POST", headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" }, body: JSON.stringify(body) }, 15_000));
  } catch (error) {
    return error instanceof InvalidRequestBodyError ? sessionError(400, "INVALID_REQUEST", "请提供有效的团队观察资料") : sessionError(503, "RESEARCH_WORKPACKS_UNAVAILABLE", "立项前团队观察暂不可用，请按原请求重试");
  }
}
