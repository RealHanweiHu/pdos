import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

// Optional catch-all: `/decisions` itself arrives with no `decisionPath`.
type Context = {
  params: Promise<{ projectId: string; decisionPath?: string[] }>;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isUuid(value: string | undefined): value is string {
  return typeof value === "string" && UUID.test(value);
}

/**
 * GET  /api/projects/{id}/decisions
 * POST /api/projects/{id}/decisions
 * POST /api/projects/{id}/decisions/{uuid}/follow-up
 */
function allowedPath(method: "GET" | "POST", segments: string[]) {
  if (segments.length === 0) return true;
  if (method === "GET" && segments.length === 1 && segments[0] === "options") return true;
  if (method === "GET") return segments.length === 2 && isUuid(segments[0]) && ["execution-evidence", "intake-sources", "responsibility"].includes(segments[1] ?? "");
  return segments.length === 2 && isUuid(segments[0]) && ["follow-up", "execution-target", "responsibility"].includes(segments[1] ?? "");
}

export async function forwardDecisions(
  method: "GET" | "POST",
  request: Request,
  context: Context,
) {
  const { projectId, decisionPath } = await context.params;
  const segments = decisionPath ?? [];
  if (!allowedPath(method, segments)) {
    return sessionError(404, "DECISION_ROUTE_NOT_FOUND", "Decision route not found");
  }
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const body = method === "POST" ? await readBoundedJson(request) : undefined;
    const suffix = segments.map(encodeURIComponent).join("/");
    const query = method === "GET" ? new URL(request.url).search : "";
    const path = `/api/projects/${encodeURIComponent(projectId)}/decisions${
      suffix ? `/${suffix}` : ""
    }${query}`;
    return forwardJson(
      await pdosApiFetch(path, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
      }),
    );
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "Valid JSON request required");
    }
    return sessionError(
      503,
      "DECISION_SERVICE_UNAVAILABLE",
      "Decision service unavailable",
    );
  }
}
