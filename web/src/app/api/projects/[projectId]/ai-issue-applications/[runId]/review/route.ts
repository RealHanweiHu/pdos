import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";
type Context = { params: Promise<{ projectId: string; runId: string }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
async function forward(request: Request, context: Context, method: "GET" | "POST") {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const { projectId, runId } = await context.params;
  if (!uuid.test(runId)) return sessionError(400, "INVALID_RUN_ID", "请选择有效的原运行");
  const search = new URL(request.url).searchParams;
  const before = search.get("before_version");
  if (search.getAll("before_version").length > 1 || (before !== null && (!/^[1-9][0-9]*$/.test(before) || !Number.isSafeInteger(Number(before))))) return sessionError(400, "INVALID_REVIEW_VERSION", "请选择有效的处置历史位置");
  if (method === "POST" && before !== null) return sessionError(400, "INVALID_REVIEW_VERSION", "处置请求不能携带历史分页位置");
  const suffix = method === "GET" && before !== null ? `?before_version=${before}` : "";
  try {
    const body = method === "POST" ? await readBoundedJson(request) : undefined;
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/ai-issue-applications/${encodeURIComponent(runId)}/review${suffix}`, { method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body: body ? JSON.stringify(body) : undefined }));
  } catch (failure) {
    if (failure instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST", "请提交完整的建议处置请求");
    return sessionError(503, "ISSUE_APPLICATION_UNAVAILABLE", "办理回执暂不可用，请沿原请求核对结果");
  }
}
export async function GET(request: Request, context: Context) { return forward(request, context, "GET"); }
export async function POST(request: Request, context: Context) { return forward(request, context, "POST"); }
