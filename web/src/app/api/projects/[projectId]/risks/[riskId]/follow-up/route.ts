import { currentSessionToken, forwardJson, pdosApiFetch, sessionError, readBoundedJson, InvalidRequestBodyError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string; riskId: string }> };
async function forward(request: Request, context: Context, method: "GET" | "POST") {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const { projectId, riskId } = await context.params;
  const query = new URLSearchParams();
  const requestId = new URL(request.url).searchParams.get("request_id");
  if (method === "GET" && requestId) query.set("request_id", requestId);
  try {
    return forwardJson(await pdosApiFetch(
      `/api/projects/${encodeURIComponent(projectId)}/risks/${encodeURIComponent(riskId)}/follow-up?${query}`,
      { method, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, cache: "no-store",
        body: method === "POST" ? JSON.stringify(await readBoundedJson(request)) : undefined },
    ));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST", "无效任务安排");
    return sessionError(503, "RISK_SERVICE_UNAVAILABLE", "风险处理任务暂不可用");
  }
}
export function GET(request: Request, context: Context) { return forward(request, context, "GET"); }
export function POST(request: Request, context: Context) { return forward(request, context, "POST"); }
