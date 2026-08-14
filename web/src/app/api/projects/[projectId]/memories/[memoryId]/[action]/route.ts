import {
  currentSessionToken,
  forwardJson,
  pdosApiFetch,
  sessionError,
} from "@/lib/pdos-api";

type MemoryActionContext = {
  params: Promise<{ projectId: string; memoryId: string; action: string }>;
};

const allowedActions = new Set(["verify", "archive", "reembed"]);

export async function POST(_request: Request, context: MemoryActionContext) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const { projectId, memoryId, action } = await context.params;
    if (!allowedActions.has(action)) {
      return sessionError(404, "MEMORY_ACTION_NOT_FOUND", "Memory action not found");
    }
    return forwardJson(
      await pdosApiFetch(
        `/api/projects/${encodeURIComponent(projectId)}/memories/${encodeURIComponent(memoryId)}/${action}`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        },
      ),
    );
  } catch {
    return sessionError(503, "MEMORY_SERVICE_UNAVAILABLE", "Memory service unavailable");
  }
}
