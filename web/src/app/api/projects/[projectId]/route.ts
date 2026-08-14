import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

type ProjectRouteContext = { params: Promise<{ projectId: string }> };

async function upstreamPath(context: ProjectRouteContext) {
  const { projectId } = await context.params;
  return `/api/projects/${encodeURIComponent(projectId)}`;
}

export async function GET(_request: Request, context: ProjectRouteContext) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    return forwardJson(
      await pdosApiFetch(await upstreamPath(context), {
        headers: { Authorization: `Bearer ${token}` },
      }),
    );
  } catch {
    return sessionError(503, "PROJECT_SERVICE_UNAVAILABLE", "Project service unavailable");
  }
}

export async function PATCH(request: Request, context: ProjectRouteContext) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const payload = await readBoundedJson(request);
    return forwardJson(
      await pdosApiFetch(await upstreamPath(context), {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      }),
    );
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(503, "PROJECT_SERVICE_UNAVAILABLE", "Project service unavailable");
  }
}
