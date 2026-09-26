import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string; gateId: string }> };

async function forward(request: Request, context: Context, method: "GET" | "POST") {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const { projectId, gateId } = await context.params;
    const query = new URLSearchParams();
    const before = new URL(request.url).searchParams.get("before");
    if (method === "GET" && before) query.set("before", before);
    const roundId = new URL(request.url).searchParams.get("round_id");
    if (method === "GET" && roundId) query.set("round_id", roundId);
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
    const init: RequestInit = { method, headers };
    if (method === "POST" && request.headers.get("content-type")?.includes("application/json")) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(await readBoundedJson(request));
    }
    return forwardJson(await pdosApiFetch(
      `/api/projects/${encodeURIComponent(projectId)}/gates/${encodeURIComponent(gateId)}/rounds${query.size ? `?${query}` : ""}`, init,
    ));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST", "请提交有效分派表单");
    return sessionError(503, "GATE_SERVICE_UNAVAILABLE", "Gate service unavailable");
  }
}
export const POST = (request: Request, context: Context) => forward(request, context, "POST");
export const GET = (request: Request, context: Context) => forward(request, context, "GET");
