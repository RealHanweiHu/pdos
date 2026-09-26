import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";

export async function forwardCaseRequirement(request: Request, id: string, operation: "requirement-links" | "requirement-options" | "requirement-link-history" | "case-links") {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  if (!/^[0-9a-f-]{36}$/i.test(id)) return sessionError(400, "INVALID_REQUEST", "Invalid object identifier");
  try {
    const root = operation === "case-links" ? "requirements" : "development-cases";
    const query = operation === "requirement-options" ? `?${new URLSearchParams({ q: new URL(request.url).searchParams.get("q") ?? "" })}` : "";
    const body = request.method === "POST" ? JSON.stringify(await readBoundedJson(request)) : undefined;
    return forwardJson(await pdosApiFetch(`/api/${root}/${encodeURIComponent(id)}/${operation}${query}`, {
      method: request.method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body,
    }));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    return sessionError(503, "CASE_SERVICE_UNAVAILABLE", "Case service unavailable");
  }
}
