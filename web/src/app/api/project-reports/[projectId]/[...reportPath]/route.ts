import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string; reportPath: string[] }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
async function forward(method: "GET" | "POST", request: Request, context: Context) {
  const { projectId, reportPath } = await context.params;
  const customer = reportPath[0] === "customer";
  const path = customer ? reportPath.slice(1) : reportPath;
  const download = method === "GET" && path.length === 2 && uuid.test(path[0]) && (path[1] === "download" || (!customer && path[1] === "bundle-download"));
  if (!uuid.test(projectId) || (!download && !(method === "POST" && path.length === 1 && (customer ? ["options", "preview", "save", "history", "read", "decide", "export", "audit-options"] : ["options", "preview", "save", "history", "audit-options", "withdraw", "bundle-preview", "bundle-save", "bundle-history"]).includes(path[0])))) return sessionError(404, "REPORT_ROUTE_NOT_FOUND", "报表入口不存在");
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "需要登录");
  try {
    const body = method === "POST" ? await readBoundedJson(request) : undefined;
    const upstream = await pdosApiFetch("/api/projects/" + projectId + (customer ? "/customer-reports/" : "/reports/") + path.map(encodeURIComponent).join("/"), {
      method, headers: { Authorization: "Bearer " + token, ...(body ? { "Content-Type": "application/json" } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}),
    }, ["save", "export", "bundle-save"].includes(path[0]) ? 120_000 : 30_000);
    if (download && upstream.ok) {
      const headers = new Headers({ "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
      for (const key of ["content-type", "content-length", "content-disposition"]) { const value = upstream.headers.get(key); if (value) headers.set(key, value); }
      return new Response(upstream.body, { status: upstream.status, headers });
    }
    return forwardJson(upstream);
  } catch (error) { return error instanceof InvalidRequestBodyError ? sessionError(400, "INVALID_REQUEST", "请提供有效的报表范围") : sessionError(503, "REPORT_UNAVAILABLE", "报表暂不可用，原生成请求可重试"); }
}
export function POST(request: Request, context: Context) { return forward("POST", request, context); }
export function GET(request: Request, context: Context) { return forward("GET", request, context); }
