import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

type MemoryRouteContext = { params: Promise<{ projectId: string }> };

async function authorization() {
  const token = await currentSessionToken();
  return token ? { Authorization: `Bearer ${token}` } : null;
}

export async function GET(request: Request, context: MemoryRouteContext) {
  const headers = await authorization();
  if (!headers) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const { projectId } = await context.params;
    const requestedStatus = new URL(request.url).searchParams.get("status");
    const status = ["draft", "verified", "archived"].includes(requestedStatus ?? "")
      ? `?status=${requestedStatus}`
      : "";
    return forwardJson(
      await pdosApiFetch(
        `/api/projects/${encodeURIComponent(projectId)}/memories${status}`,
        { headers },
      ),
    );
  } catch {
    return sessionError(503, "MEMORY_SERVICE_UNAVAILABLE", "Memory service unavailable");
  }
}

export async function POST(request: Request, context: MemoryRouteContext) {
  const headers = await authorization();
  if (!headers) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const { projectId } = await context.params;
    const payload = await readBoundedJson(request, 131_072);
    return forwardJson(
      await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/memories`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    );
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(503, "MEMORY_SERVICE_UNAVAILABLE", "Memory service unavailable");
  }
}
