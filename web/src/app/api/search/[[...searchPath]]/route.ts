import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

// Optional catch-all: `/api/search` itself arrives with no `searchPath`.
type Context = {
  params: Promise<{ searchPath?: string[] }>;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isUuid(value: string | undefined): value is string {
  return typeof value === "string" && UUID.test(value);
}

/**
 * GET  /api/search
 * POST /api/search/projects/{uuid}/sample-matches
 * Anything else is a 404 here rather than an opaque pass-through.
 */
function allowedPath(method: "GET" | "POST", segments: string[]) {
  if (method === "GET") return segments.length === 0 || (
    segments.length === 3 && segments[0] === "sources" && isUuid(segments[2]) &&
    ["project", "issue", "task", "risk", "requirement", "specification", "decision", "document", "attachment", "memory", "sample"].includes(segments[1])
  );
  return (
    segments.length === 3 &&
    segments[0] === "projects" &&
    isUuid(segments[1]) &&
    segments[2] === "sample-matches"
  );
}

async function forwardSearch(
  method: "GET" | "POST",
  request: Request,
  context: Context,
) {
  const { searchPath } = await context.params;
  const segments = searchPath ?? [];
  if (!allowedPath(method, segments)) {
    return sessionError(404, "SEARCH_ROUTE_NOT_FOUND", "Search route not found");
  }
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const body = method === "POST" ? await readBoundedJson(request) : undefined;
    const suffix = segments.map(encodeURIComponent).join("/");
    // The query string carries q/kinds/limit and must survive the hop.
    const query = new URL(request.url).search;
    const path = `/api/search${suffix ? `/${suffix}` : ""}${method === "GET" ? query : ""}`;
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
    return sessionError(503, "SEARCH_SERVICE_UNAVAILABLE", "Search service unavailable");
  }
}

export function GET(request: Request, context: Context) {
  return forwardSearch("GET", request, context);
}

export function POST(request: Request, context: Context) {
  return forwardSearch("POST", request, context);
}
