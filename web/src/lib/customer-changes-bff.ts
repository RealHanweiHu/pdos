import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

// Optional catch-all: `/customer-changes` itself arrives with no path.
type Context = {
  params: Promise<{ projectId: string; ccrPath?: string[] }>;
};

type Method = "GET" | "POST";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isUuid(value: string | undefined): value is string {
  return typeof value === "string" && UUID.test(value);
}

/**
 * The customer change chain: received → analyse → quote reply → outward
 * approval → customer decision → optional ECR link.
 *
 * `reply` and `reply/approve` are separate entries on purpose: approving a
 * quote is a four-eyes step the server refuses for the drafter, and collapsing
 * them into one prefix would let a client reach the approval by accident.
 */
const ALLOWED: ReadonlyArray<{ method: Method; shape: readonly string[] }> = [
  { method: "GET", shape: [] },
  { method: "POST", shape: [] },
  { method: "POST", shape: ["#", "analyze"] },
  { method: "POST", shape: ["#", "reply"] },
  { method: "POST", shape: ["#", "reply", "approve"] },
  { method: "POST", shape: ["#", "customer-decision"] },
  { method: "POST", shape: ["#", "engineering-change"] },
];

function matches(shape: readonly string[], segments: string[]) {
  if (shape.length !== segments.length) return false;
  return shape.every((part, index) =>
    part === "#" ? isUuid(segments[index]) : part === segments[index],
  );
}

export async function forwardCustomerChanges(
  method: Method,
  request: Request,
  context: Context,
) {
  const { projectId, ccrPath } = await context.params;
  const segments = ccrPath ?? [];
  if (!ALLOWED.some((entry) => entry.method === method && matches(entry.shape, segments))) {
    return sessionError(
      404,
      "CUSTOMER_CHANGE_ROUTE_NOT_FOUND",
      "Customer change route not found",
    );
  }
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const body = method === "POST" ? await readBoundedJson(request) : undefined;
    const suffix = segments.map(encodeURIComponent).join("/");
    const query = method === "GET" ? new URL(request.url).search : "";
    const path = `/api/projects/${encodeURIComponent(projectId)}/customer-changes${
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
      "CUSTOMER_CHANGE_SERVICE_UNAVAILABLE",
      "Customer change service unavailable",
    );
  }
}
