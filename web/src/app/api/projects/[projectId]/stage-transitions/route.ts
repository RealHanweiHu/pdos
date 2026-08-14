import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

type ProjectRouteContext = { params: Promise<{ projectId: string }> };

export async function POST(request: Request, context: ProjectRouteContext) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const payload = await readBoundedJson(request);
    const { projectId } = await context.params;
    return forwardJson(
      await pdosApiFetch(
        `/api/projects/${encodeURIComponent(projectId)}/stage-transitions`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        },
      ),
    );
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(503, "PROJECT_SERVICE_UNAVAILABLE", "Project service unavailable");
  }
}
