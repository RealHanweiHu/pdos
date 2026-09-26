import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

type MemoryRouteContext = {
  params: Promise<{ projectId: string; memoryId: string }>;
};

export async function PATCH(request: Request, context: MemoryRouteContext) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const { projectId, memoryId } = await context.params;
    const payload = await readBoundedJson(request, 131_072);
    return forwardJson(
      await pdosApiFetch(
        `/api/projects/${encodeURIComponent(projectId)}/memories/${encodeURIComponent(memoryId)}`,
        {
          method: "PATCH",
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
    return sessionError(503, "MEMORY_SERVICE_UNAVAILABLE", "Memory service unavailable");
  }
}
