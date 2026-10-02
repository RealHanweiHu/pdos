import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function positive(value: string): boolean { return /^[1-9][0-9]*$/.test(value) && Number.isSafeInteger(Number(value)); }
export async function GET(request: Request, context: Context) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const params = new URL(request.url).searchParams, query = new URLSearchParams();
  for (const key of ["event_row_id", "before_id", "run_id"]) {
    const value = params.get(key);
    if (value === null) continue;
    if (params.getAll(key).length !== 1 || !(key === "event_row_id" ? positive(value) : uuid.test(value))) return sessionError(400, "INVALID_RUN_QUERY", "运行查询位置无效，请刷新重试");
    query.set(key, value);
  }
  if (params.has("attention")) {
    if (params.getAll("attention").length !== 1 || params.get("attention") !== "true" || query.has("event_row_id") || query.has("run_id")) return sessionError(400, "INVALID_RUN_QUERY", "例外查询条件无效");
    query.set("attention", "true");
  }
  if (query.has("run_id") && query.size > 1) return sessionError(400, "INVALID_RUN_QUERY", "指定运行不能同时使用其他查询位置");
  try {
    const { projectId } = await context.params;
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/ai-issue-event-runs${query.size ? `?${query}` : ""}`, { method: "GET", headers: { Authorization: `Bearer ${token}` } }));
  } catch { return sessionError(503, "ISSUE_EVENT_RUNS_UNAVAILABLE", "运行记录暂不可用，请稍后重试"); }
}
export async function POST(request: Request, context: Context) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const body = await readBoundedJson(request);
    const { projectId } = await context.params;
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/ai-issue-event-runs`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(body) }));
  } catch (failure) {
    if (failure instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST", "请提交完整的生成请求");
    return sessionError(503, "ISSUE_EVENT_RUNS_UNAVAILABLE", "生成回执暂不可用，请沿原请求核对结果");
  }
}
