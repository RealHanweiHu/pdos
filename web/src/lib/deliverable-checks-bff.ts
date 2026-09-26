import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

// Optional catch-all: `/deliverable-checks` itself arrives with no path.
type Context = {
  params: Promise<{ projectId: string; checkPath?: string[] }>;
};

type Method = "GET" | "POST";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isUuid(value: string | undefined): value is string {
  return typeof value === "string" && UUID.test(value);
}

const ALLOWED: ReadonlyArray<{ method: Method; shape: readonly string[] }> = [
  { method: "GET", shape: [] },
  { method: "POST", shape: ["prepare"] },
  { method: "POST", shape: ["items", "#", "resolve"] },
];

function matches(shape: readonly string[], segments: string[]) {
  if (shape.length !== segments.length) return false;
  return shape.every((part, index) =>
    part === "#" ? isUuid(segments[index]) : part === segments[index],
  );
}

export async function forwardDeliverableChecks(
  method: Method,
  request: Request,
  context: Context,
) {
  const { projectId, checkPath } = await context.params;
  const segments = checkPath ?? [];
  if (!ALLOWED.some((entry) => entry.method === method && matches(entry.shape, segments))) {
    return sessionError(404, "CHECK_ROUTE_NOT_FOUND", "Deliverable check route not found");
  }
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    // `prepare` takes no body server-side; everything else that writes does.
    const bodyless = method === "GET" || segments[0] === "prepare";
    const body = bodyless ? undefined : await readBoundedJson(request);
    const suffix = segments.map(encodeURIComponent).join("/");
    const query = method === "GET" ? new URL(request.url).search : "";
    const path = `/api/projects/${encodeURIComponent(projectId)}/deliverable-checks${
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
    return sessionError(503, "CHECK_SERVICE_UNAVAILABLE", "Deliverable check service unavailable");
  }
}
