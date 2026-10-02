import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

type Context = {
  params: Promise<{ projectId: string; qualityPath: string[] }>;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isUuid(value: string | undefined): value is string {
  return typeof value === "string" && UUID.test(value);
}

function allowedPath(method: "GET" | "POST", segments: string[]) {
  if (segments[0] === "responsibilities") return segments.length === 3 && ["complaint", "ncr", "capa", "certification"].includes(segments[1]) && isUuid(segments[2]);
  if (segments[0] === "issue-links") {
    return method === "GET"
      ? segments.length === 1 || segments.length === 2 && segments[1] === "options"
      : segments.length === 1 || segments.length === 2 && segments[1] === "escalate" || segments.length === 3 && isUuid(segments[1]) && segments[2] === "retract";
  }
  if (segments[0] === "fmea" && segments[1] === "candidates") {
    return method === "GET"
      ? segments.length === 2 || segments.length === 3 && isUuid(segments[2])
      : segments.length === 3 && segments[2] === "capture" || segments.length === 4 && isUuid(segments[2]) && ["refresh", "disposition"].includes(segments[3]);
  }
  if (segments[0] === "fmea") {
    return method === "GET"
      ? segments.length === 1 || segments.length === 2 && (["sources", "coverage"].includes(segments[1]) || isUuid(segments[1])) || segments.length === 3 && isUuid(segments[1]) && segments[2] === "design-rules"
      : segments.length === 2 && segments[1] === "versions" || segments.length === 3 && isUuid(segments[1]) && ["publish", "design-rules"].includes(segments[2]);
  }
  if (method === "GET") {
    return (
      (segments.length === 1 && segments[0] === "complaints") ||
      (segments.length === 2 && segments[0] === "complaints" && isUuid(segments[1])) ||
      (segments.length === 3 &&
        segments[0] === "complaints" &&
        isUuid(segments[1]) &&
        segments[2] === "ncrs") ||
      (segments.length === 2 && segments[0] === "ncrs" && isUuid(segments[1])) ||
      (segments.length === 3 &&
        segments[0] === "ncrs" &&
        isUuid(segments[1]) &&
        ["detail", "workspace", "evidence", "work-packages", "preparation-runs"].includes(segments[2]))
    );
  }
  return (
    (segments.length === 1 && segments[0] === "complaints") ||
    (segments.length === 3 &&
      segments[0] === "complaints" &&
      isUuid(segments[1]) &&
      ["triage", "transitions"].includes(segments[2] ?? "")) ||
    (segments.length === 3 &&
      segments[0] === "ncrs" &&
      isUuid(segments[1]) &&
      ["transitions", "root-causes", "actions", "effectiveness-reviews", "preventive-not-applicable", "operations", "preparation-context", "preparation-runs"].includes(
        segments[2] ?? "",
      )) ||
    (segments.length === 5 &&
      segments[0] === "ncrs" &&
      isUuid(segments[1]) &&
      segments[2] === "root-causes" &&
      isUuid(segments[3]) &&
      segments[4] === "approve") ||
    (segments.length === 5 &&
      segments[0] === "ncrs" &&
      isUuid(segments[1]) &&
      segments[2] === "actions" &&
      isUuid(segments[3]) &&
      segments[4] === "transitions")
  );
}

export async function forwardQuality(
  method: "GET" | "POST",
  request: Request,
  context: Context,
) {
  const { projectId, qualityPath } = await context.params;
  if (!allowedPath(method, qualityPath)) {
    return sessionError(404, "QUALITY_ROUTE_NOT_FOUND", "Quality route not found");
  }
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const body = method === "POST" ? await readBoundedJson(request) : undefined;
    const suffix = qualityPath.map(encodeURIComponent).join("/");
    const query = new URLSearchParams();
    if (method === "GET" && ["fmea", "issue-links", "ncrs", "responsibilities"].includes(qualityPath[0])) {
      const incoming = new URL(request.url).searchParams;
      for (const key of ["kind", "offset", "before_version", "before_id", "issue_id", "ncr_id"]) {
        const value = incoming.get(key);
        if (value !== null) query.set(key, value);
      }
    }
    return forwardJson(
      await pdosApiFetch(
        `/api/projects/${encodeURIComponent(projectId)}/quality/${suffix}${query.size ? `?${query}` : ""}`,
        {
          method,
          headers: {
            Authorization: `Bearer ${token}`,
            ...(body ? { "Content-Type": "application/json" } : {}),
          },
          ...(body ? { body: JSON.stringify(body) } : {}),
        },
      ),
    );
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "Valid JSON request required");
    }
    return sessionError(503, "QUALITY_SERVICE_UNAVAILABLE", "Quality service unavailable");
  }
}
