import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";
type Context = { params: Promise<{ workPath?: string[] }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
async function forward(method: "GET" | "POST" | "PUT", request: Request, context: Context) {
  const { workPath = [] } = await context.params;
  const [root, space, kind, id, action] = workPath;
  const scoped = root === "spaces" && uuid.test(space ?? "");
  const allowed = method === "GET" ?
    (workPath.length === 1 && ["spaces", "my-work"].includes(root ?? "")) || (root === "requirements" && uuid.test(space ?? "") && workPath.length === 3 && ["opportunities", "definition-sources"].includes(kind ?? "")) || (scoped && workPath.length === 4 && ["experiments", "opportunities", "strategies", "definitions", "requirement-packages"].includes(kind ?? "") && uuid.test(id ?? "")) || (scoped && workPath.length === 5 && uuid.test(id ?? "") && ((kind === "definition-exports" && action === "download") || (kind === "evidence" && action === "content") || (kind === "definitions" && ["reuse-options", "cost-feedback"].includes(action ?? "")) || (["experiments", "strategies", "definitions", "work-items"].includes(kind ?? "") && action === "history"))) || (scoped && (workPath.length === 2 || (workPath.length === 3 && ["initial-plans", "requirement-options", "evidence", "products", "sources", "searches", "subscriptions", "requirement-packages", "competitors", "market-segments", "opportunities", "experiments", "strategies", "definitions"].includes(kind ?? "")))) :
    method === "PUT" ? scoped && workPath.length === 4 && kind === "members" && uuid.test(id ?? "") :
    (workPath.length === 1 && root === "spaces") || (scoped && workPath.length === 3 && ["definition-export-options", "definition-export-preview", "definition-export-save", "definition-export-history", "result-followup-inbox", "result-followup-options", "result-followup-read", "result-followup-preview", "result-followup-save", "result-metric-context", "result-metric-preview", "result-metric-save", "result-metric-replay", "retirement-feedback-options", "retirement-feedback", "retirement-feedback-save", "result-feedback-history", "result-feedback-options", "result-feedback", "result-feedback-save", "experiment-feedback-target", "experiment-feedback-options", "experiment-feedback", "experiment-feedback-save", "matrix-outcomes", "matrix-outcome-save", "matrix-dispositions", "matrix-disposition-save", "matrix-ai-runs", "matrix-ai-history", "matrix-ai-progress", "matrix-ai-cancel", "matrix-ai-options", "matrix-ai-context", "matrix-record-save", "matrix-record-history", "matrix-record-read", "matrix-record-replay", "matrix-record-refresh", "matrix-market-options", "matrix-coverage-context", "matrix-coverage-calculation", "product-roadmap", "product-roadmap-history", "product-roadmap-save", "product-matrix", "product-matrix-comparison", "initial-plans", "research", "work-items", "products", "changes", "lifecycle", "sources", "capture", "searches", "subscriptions", "competitors", "requirement-packages", "competitor-comparison", "market-segments", "opportunities", "experiments", "strategies", "definitions", "market-sizing"].includes(kind ?? "")) ||
    (scoped && workPath.length === 5 && uuid.test(id ?? "") && ((kind === "research" && ["start", "conclude", "cancel"].includes(action ?? "")) || (kind === "work-items" && ["actions", "assignment"].includes(action ?? "")) || (kind === "products" && ["changes", "members"].includes(action ?? "")) || (["subscriptions", "requirement-packages"].includes(kind ?? "") && action === "actions") || (["experiments", "strategies", "definitions"].includes(kind ?? "") && ["actions", "changes"].includes(action ?? "")) || (kind === "definitions" && action === "reviews")));
  const responsibility = scoped && workPath.length === 5 && kind === "responsibilities" && ["research", "work", "definition", "package", "strategy", "experiment", "opportunity", "space", "node", "subscription"].includes(id ?? "") && uuid.test(action ?? "") && ["GET", "POST"].includes(method);
  if (!allowed && !responsibility) return sessionError(404, "PRODUCT_WORK_ROUTE_NOT_FOUND", "Product work route not found");
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const body = method === "GET" ? undefined : await readBoundedJson(request);
    const query = method === "GET" && kind === "work-items" && action === "history" ? `?${new URLSearchParams([...new URL(request.url).searchParams].filter(([key]) => key === "before_id"))}` : method === "GET" && root === "my-work" ? `?${new URLSearchParams([...new URL(request.url).searchParams].filter(([key]) => ["collection", "offset", "limit"].includes(key)))}` : method === "GET" && (responsibility || kind === "subscriptions") ? new URL(request.url).search : method === "GET" && kind === "initial-plans" ? `?${new URLSearchParams(Object.fromEntries(["source_kind", "source_id", "options"].map((key) => [key, new URL(request.url).searchParams.get(key) ?? ""])))}` : method === "GET" && kind === "requirement-options" ? `?q=${encodeURIComponent(new URL(request.url).searchParams.get("q") ?? "")}` : "";
    const upstream = await pdosApiFetch(`/api/product-work/${workPath.map(encodeURIComponent).join("/")}${query}`, {
      method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}),
    }, method === "POST" && kind === "matrix-ai-runs" ? 300_000 : method === "POST" && ["capture", "sources", "searches"].includes(kind ?? "") ? 30_000 : method === "POST" && kind === "definition-export-save" ? 120_000 : 5_000);
    if (method === "GET" && kind === "definition-exports" && action === "download" && upstream.ok) {
      const headers = new Headers({"Cache-Control":"no-store", "X-Content-Type-Options":"nosniff"});
      for (const name of ["content-type", "content-length", "content-disposition"]) { const value = upstream.headers.get(name); if (value) headers.set(name,value); }
      return new Response(upstream.body, {status:upstream.status,headers});
    }
    return forwardJson(upstream);
  } catch (error) {
    return error instanceof InvalidRequestBodyError ? sessionError(400, "INVALID_REQUEST", "Valid JSON required") : sessionError(503, "PRODUCT_WORK_UNAVAILABLE", "立项前工作暂不可用");
  }
}
export function GET(request: Request, context: Context) { return forward("GET", request, context); }
export function POST(request: Request, context: Context) { return forward("POST", request, context); }
export function PUT(request: Request, context: Context) { return forward("PUT", request, context); }
