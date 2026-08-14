import {
  currentSessionToken,
  forwardJson,
  pdosApiFetch,
  sessionError,
} from "@/lib/pdos-api";

type FindingRouteContext = { params: Promise<{ findingId: string }> };

export async function POST(_request: Request, context: FindingRouteContext) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const { findingId } = await context.params;
    return forwardJson(
      await pdosApiFetch(`/api/ai/findings/${encodeURIComponent(findingId)}/apply`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      }),
    );
  } catch {
    return sessionError(503, "FINDING_SERVICE_UNAVAILABLE", "Finding service unavailable");
  }
}
