import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";
export async function GET(_request: Request, context: { params: Promise<{ findingId: string }> }) {
  const token = await currentSessionToken(); if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try { return forwardJson(await pdosApiFetch(`/api/ai/findings/${encodeURIComponent((await context.params).findingId)}`, { headers: { Authorization: `Bearer ${token}` } })); }
  catch { return sessionError(503, "FINDING_SERVICE_UNAVAILABLE", "Finding service unavailable"); }
}
