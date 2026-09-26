import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string; operation: string }> };
export async function POST(request: Request, context: Context) {
  const { projectId, operation } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(projectId) || !["options", "create", "revoke", "history", "calls"].includes(operation)) return sessionError(404, "UNKNOWN_OPERATION", "接口管理入口不存在");
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "LOGIN_REQUIRED", "需要登录");
  try {
    const body = await readBoundedJson(request);
    return forwardJson(await pdosApiFetch("/api/projects/" + projectId + "/open-api/" + operation, {
      method: "POST", headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" }, body: JSON.stringify(body),
    }));
  } catch (error) { return error instanceof InvalidRequestBodyError ? sessionError(400, "INVALID_REQUEST", "请提供有效的授权范围") : sessionError(503, "OPEN_API_ADMIN_UNAVAILABLE", "接口管理暂不可用，请按原请求重试"); }
}
