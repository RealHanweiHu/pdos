import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
async function forward(request: Request, context: Context, method: "GET" | "POST") {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const search = new URL(request.url).searchParams;
  const before = search.get("before_id"), limit = search.get("limit") ?? "20";
  if ((before !== null && !uuid.test(before)) || !/^[1-9][0-9]*$/.test(limit) || Number(limit) > 20 || search.getAll("before_id").length > 1 || search.getAll("limit").length > 1) return sessionError(400, "INVALID_OBSERVATION_CURSOR", "请选择有效的观察历史位置");
  const query = new URLSearchParams({ limit });
  if (before !== null) query.set("before_id", before);
  try {
    const { projectId } = await context.params;
    const body = method === "POST" ? await readBoundedJson(request) : undefined;
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/ai-issue-observations${method === "GET" ? `?${query}` : ""}`, { method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body: body ? JSON.stringify(body) : undefined }));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST", "请提交完整的观察窗口");
    return sessionError(503, "ISSUE_OBSERVATION_UNAVAILABLE", "观察记录暂不可用，保存结果未明确时请沿原请求核对");
  }
}
export function GET(request: Request, context: Context) { return forward(request, context, "GET"); }
export function POST(request: Request, context: Context) { return forward(request, context, "POST"); }
