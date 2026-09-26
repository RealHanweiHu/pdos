import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";

export async function forwardFindingLifecycle(method: "GET" | "POST", path: string) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    return forwardJson(await pdosApiFetch(`/api/ai/findings/${path}`, {
      method, headers: { Authorization: `Bearer ${token}`, ...(path === "archive-stale" ? { "Content-Type": "application/json" } : {}) },
      ...(path === "archive-stale" ? { body: JSON.stringify({}) } : {}),
    }));
  } catch { return sessionError(503, "FINDING_SERVICE_UNAVAILABLE", "建议记录暂不可用，请刷新后核对"); }
}
