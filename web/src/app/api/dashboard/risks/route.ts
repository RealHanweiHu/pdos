import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";

export async function GET(request: Request) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  if (new URL(request.url).search) {
    return sessionError(400, "INVALID_REQUEST", "Dashboard risk query parameters are not supported");
  }
  try {
    return await forwardJson(await pdosApiFetch("/api/dashboard/risks", {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    }));
  } catch {
    return sessionError(503, "DASHBOARD_RISKS_UNAVAILABLE", "Dashboard risks unavailable");
  }
}
