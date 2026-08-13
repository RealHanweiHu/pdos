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
        segments[2] === "detail")
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
      ["transitions", "root-causes", "actions", "effectiveness-reviews", "preventive-not-applicable"].includes(
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
    return forwardJson(
      await pdosApiFetch(
        `/api/projects/${encodeURIComponent(projectId)}/quality/${suffix}`,
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
