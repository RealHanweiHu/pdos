import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";
type Context = { params: Promise<{ projectId: string; gateId: string }> };
export async function GET(_: Request, context: Context) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const { projectId, gateId } = await context.params;
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/gates/${encodeURIComponent(gateId)}/assignment-options`, { headers: { Authorization: `Bearer ${token}` } }));
  } catch { return sessionError(503, "GATE_SERVICE_UNAVAILABLE", "Gate service unavailable"); }
}
