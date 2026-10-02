import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";
type Context = { params: Promise<{ projectId: string; runId: string }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
async function forward(request: Request, context: Context, method: "POST") {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const { projectId, runId } = await context.params;
  if (!uuid.test(runId)) return sessionError(400, "INVALID_RUN_ID", "请选择有效的原运行");
  try {
    const body = method === "POST" ? await readBoundedJson(request) : undefined;
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/ai-issue-applications/${encodeURIComponent(runId)}/withdraw`, { method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body: body ? JSON.stringify(body) : undefined }));
  } catch (failure) {
    if (failure instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST", "请提交完整的撤回请求");
    return sessionError(503, "ISSUE_APPLICATION_UNAVAILABLE", "撤回回执暂不可用，请沿原请求核对结果");
  }
}
export async function POST(request: Request, context: Context) { return forward(request, context, "POST"); }
