import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";
async function proxy(request: Request, method: "GET" | "POST") {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const query = new URLSearchParams();
    if (method === "GET") for (const key of ["user_id", "q", "before_version"]) { const value = new URL(request.url).searchParams.get(key); if (value !== null) query.set(key, value); }
    const body = method === "POST" ? await readBoundedJson(request) : undefined;
    return forwardJson(await pdosApiFetch(`/api/integrations/tencent-meeting/bindings${query.size ? `?${query}` : ""}`, { method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) }));
  } catch (error) { return error instanceof InvalidRequestBodyError ? sessionError(400, "INVALID_REQUEST", "Valid JSON required") : sessionError(503, "INTEGRATION_UNAVAILABLE", "Integration temporarily unavailable"); }
}
export function GET(request: Request) { return proxy(request, "GET"); }
export function POST(request: Request) { return proxy(request, "POST"); }
