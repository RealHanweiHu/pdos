import {
  currentSessionToken,
  forwardJson,
  pdosApiFetch,
  sessionError,
} from "@/lib/pdos-api";

type ActivityRouteContext = { params: Promise<{ projectId: string }> };

export async function GET(_request: Request, context: ActivityRouteContext) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const { projectId } = await context.params;
    return forwardJson(
      await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/activity`, {
        headers: { Authorization: `Bearer ${token}` },
      }),
    );
  } catch {
    return sessionError(503, "PROJECT_ACTIVITY_UNAVAILABLE", "Project activity unavailable");
  }
}
