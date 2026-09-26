import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

// Optional catch-all: `/evidence` itself arrives with no path.
type Context = {
  params: Promise<{ evidencePath?: string[] }>;
};

type Method = "GET" | "POST";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isUuid(value: string | undefined): value is string {
  return typeof value === "string" && UUID.test(value);
}

/**
 * The tenant-level evidence base (V2-7): research sources and the immutable
 * snapshots agent conclusions cite.
 *
 * There is deliberately no route that edits a snapshot's body — correcting one
 * means capturing a new snapshot and superseding the old, and the absence of an
 * edit path here mirrors the database trigger that enforces it.
 */
const ALLOWED: ReadonlyArray<{ method: Method; shape: readonly string[] }> = [
  { method: "GET", shape: ["sources"] },
  { method: "POST", shape: ["sources"] },
  { method: "GET", shape: ["sources", "#", "responsibility"] },
  { method: "POST", shape: ["sources", "#", "responsibility"] },
  { method: "GET", shape: ["snapshots"] },
  { method: "POST", shape: ["snapshots"] },
  { method: "GET", shape: ["snapshots", "#"] },
  { method: "GET", shape: ["snapshots", "#", "content"] },
  { method: "POST", shape: ["snapshots", "#", "supersede"] },
  { method: "POST", shape: ["snapshots", "#", "conflict"] },
];

function matches(shape: readonly string[], segments: string[]) {
  if (shape.length !== segments.length) return false;
  return shape.every((part, index) =>
    part === "#" ? isUuid(segments[index]) : part === segments[index],
  );
}

export async function forwardEvidence(
  method: Method,
  request: Request,
  context: Context,
) {
  const { evidencePath } = await context.params;
  const segments = evidencePath ?? [];
  if (!ALLOWED.some((entry) => entry.method === method && matches(entry.shape, segments))) {
    return sessionError(404, "EVIDENCE_ROUTE_NOT_FOUND", "Evidence route not found");
  }
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const body = method === "POST" ? await readBoundedJson(request) : undefined;
    const suffix = segments.map(encodeURIComponent).join("/");
    const query = method === "GET" ? new URL(request.url).search : "";
    return forwardJson(
      await pdosApiFetch(`/api/evidence/${suffix}${query}`, {
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
    return sessionError(503, "EVIDENCE_SERVICE_UNAVAILABLE", "Evidence service unavailable");
  }
}
