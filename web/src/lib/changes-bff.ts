import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

// Optional catch-all: `/changes` itself arrives with no `changePath`.
type Context = {
  params: Promise<{ projectId: string; changePath?: string[] }>;
};

type Method = "GET" | "POST";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isUuid(value: string | undefined): value is string {
  return typeof value === "string" && UUID.test(value);
}

/**
 * ECR → ECN → ERP handoff. Written as an explicit method+shape allowlist: the
 * handoff verbs in particular (queue, export, replay, reconcile) each carry a
 * different confirmation contract server-side, so a blanket proxy would let a
 * typo reach the wrong one.
 */
const ALLOWED: ReadonlyArray<{ method: Method; shape: readonly string[] }> = [
  { method: "GET", shape: [] },
  { method: "GET", shape: ["discussion-topics"] },
  { method: "GET", shape: ["discussion-topics", "sources"] },
  { method: "POST", shape: ["discussion-topics"] },
  { method: "POST", shape: ["discussion-topics", "prepare"] },
  { method: "POST", shape: ["discussion-topics", "#", "inputs"] },
  { method: "POST", shape: ["discussion-topics", "#", "brief-reviews"] },
  { method: "POST", shape: ["discussion-topics", "#", "control", "cancel"] },
  { method: "POST", shape: ["discussion-topics", "#", "control", "cancel_related"] },
  { method: "POST", shape: ["discussion-topics", "#", "control", "recover"] },
  { method: "GET", shape: ["discussion-runs", "#"] },
  { method: "GET", shape: ["discussion-runs", "#", "research", "sources"] },
  { method: "POST", shape: ["discussion-runs", "#", "research", "preview"] },
  { method: "POST", shape: ["discussion-runs", "#", "research"] },
  { method: "GET", shape: ["ecrs", "#", "discussion-runs"] },
  { method: "POST", shape: ["ecrs", "#", "discussion-runs"] },
  { method: "POST", shape: ["ecrs", "#", "discussion-runs", "#", "inputs"] },
  { method: "POST", shape: ["ecrs", "#", "discussion-runs", "#", "brief-reviews"] },
  { method: "POST", shape: ["ecrs", "#", "discussion-runs", "#", "control", "cancel"] },
  { method: "POST", shape: ["ecrs", "#", "discussion-runs", "#", "control", "cancel_related"] },
  { method: "POST", shape: ["ecrs", "#", "discussion-runs", "#", "control", "recover"] },
  { method: "GET", shape: ["ecrs", "#", "decision-summary"] },
  { method: "GET", shape: ["quiet-policy"] },
  { method: "GET", shape: ["quiet-policy", "sources"] },
  { method: "POST", shape: ["quiet-policy"] },
  { method: "POST", shape: ["ecrs", "#", "quiet-period", "adopt-policy"] },
  { method: "GET", shape: ["ecrs", "#", "quiet-period"] },
  { method: "POST", shape: ["ecrs", "#", "quiet-period"] },
  { method: "POST", shape: ["ecrs", "#", "quiet-period", "#", "decide"] },
  { method: "POST", shape: ["ecrs", "#", "quiet-period", "#", "replace-approvers"] },
  { method: "GET", shape: ["professional-sources", "cost_alternative", "#"] },
  { method: "POST", shape: ["professional-sources", "cost_alternative", "#"] },
  { method: "GET", shape: ["professional-sources", "engineering_review", "#"] },
  { method: "POST", shape: ["professional-sources", "engineering_review", "#"] },
  { method: "GET", shape: ["professional-sources", "firmware_package", "#"] },
  { method: "POST", shape: ["professional-sources", "firmware_package", "#"] },
  { method: "GET", shape: ["ecrs", "#", "impact-graph"] },
  { method: "GET", shape: ["ecrs", "#", "impact-scope"] },
  { method: "POST", shape: ["ecrs", "#", "impact-scope"] },
  ...["requirement", "ecn", "bom", "bom_item", "specification", "test_case", "test_run", "sample", "configuration", "build", "issue", "cost_item", "cost", "supplier", "certification", "document"].flatMap(kind => [{method:"GET" as const,shape:["ecrs", "#", "impact-scope", "sources", kind]}, {method:"GET" as const,shape:["ecrs", "#", "impact-scope", "sources", kind, "#"]}]),
  { method: "GET", shape: ["ecrs", "#", "analysis-runs"] },
  { method: "POST", shape: ["ecrs", "#", "analysis-runs"] },
  { method: "GET", shape: ["ecrs", "#", "analysis-context"] },
  { method: "GET", shape: ["ecrs", "#", "execution-overview"] },
  { method: "GET", shape: ["ecrs", "#", "execution-tasks"] },
  { method: "GET", shape: ["ecrs", "#", "execution-tasks", "choices"] },
  { method: "POST", shape: ["ecrs", "#", "execution-tasks"] },
  { method: "POST", shape: ["execution-items", "#", "follow-ups"] },
  { method: "GET", shape: ["execution-items", "#", "results"] },
  { method: "POST", shape: ["execution-items", "#", "results"] },
  { method: "POST", shape: ["execution-items", "#", "results", "#", "confirm"] },
  ...["test_run", "engineering_review", "certification", "document"].map(kind=>({method:"GET" as const,shape:["execution-items", "#", "evidence", kind]})),
  { method: "POST", shape: ["ecrs"] },
  { method: "POST", shape: ["ecrs", "#", "start-impact"] },
  { method: "POST", shape: ["ecrs", "#", "submit-impact"] },
  { method: "POST", shape: ["ecrs", "#", "refresh-impact"] },
  { method: "POST", shape: ["ecrs", "#", "decide"] },
  { method: "POST", shape: ["ecrs", "#", "ecns"] },
  { method: "POST", shape: ["ecns", "#", "submit-effectivity"] },
  { method: "POST", shape: ["ecns", "#", "decide-effectivity"] },
  { method: "GET", shape: ["handoffs", "#", "delivery"] },
  { method: "POST", shape: ["handoffs", "#", "queue"] },
  { method: "POST", shape: ["handoffs", "#", "ready"] },
  { method: "POST", shape: ["handoffs", "#", "export"] },
  { method: "POST", shape: ["handoffs", "#", "replay"] },
  { method: "POST", shape: ["handoffs", "#", "reconcile"] },
];

function matches(shape: readonly string[], segments: string[]) {
  if (shape.length !== segments.length) return false;
  return shape.every((part, index) =>
    part === "#" ? isUuid(segments[index]) : part === segments[index],
  );
}

export async function forwardChanges(
  method: Method,
  request: Request,
  context: Context,
) {
  const { projectId, changePath } = await context.params;
  const segments = changePath ?? [];
  if (!ALLOWED.some((entry) => entry.method === method && matches(entry.shape, segments))) {
    return sessionError(404, "CHANGE_ROUTE_NOT_FOUND", "Change route not found");
  }
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const body = method === "POST" ? await readBoundedJson(request) : undefined;
    const suffix = segments.map(encodeURIComponent).join("/");
    const query = method === "GET" ? new URL(request.url).search : "";
    const path = `/api/projects/${encodeURIComponent(projectId)}/changes${
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
    return sessionError(503, "CHANGE_SERVICE_UNAVAILABLE", "Change service unavailable");
  }
}
