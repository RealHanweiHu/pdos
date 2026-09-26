import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

// Optional catch-all: `/npi` itself arrives with no `npiPath`.
type Context = {
  params: Promise<{ projectId: string; npiPath?: string[] }>;
};

type Method = "GET" | "POST" | "PATCH" | "PUT";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isUuid(value: string | undefined): value is string {
  return typeof value === "string" && UUID.test(value);
}

/**
 * The NPI execution surface: builds, samples, sample configurations and
 * sign-offs, test plans/cases/runs/reports, imports and certifications.
 *
 * Written as an explicit method+shape allowlist rather than a blanket proxy so
 * that a path the backend does not serve fails here, visibly, instead of being
 * forwarded and coming back as a confusing backend error.
 */
const ALLOWED: ReadonlyArray<{ method: Method; shape: readonly string[] }> = [
  { method: "GET", shape: ["cost-definition-feedback"] },
  { method: "POST", shape: ["cost-definition-feedback"] },
  { method: "POST", shape: ["cost-definition-feedback", "preview"] },
  { method: "POST", shape: ["cost-definition-feedback", "#", "preview"] },
  { method: "POST", shape: ["cost-definition-feedback", "#", "decisions"] },
  { method: "GET", shape: ["cost-alternatives"] },
  { method: "POST", shape: ["cost-alternatives"] },
  { method: "POST", shape: ["cost-alternatives", "preview"] },
  { method: "GET", shape: ["cost-gaps"] },
  { method: "POST", shape: ["cost-gaps"] },
  { method: "POST", shape: ["cost-gaps", "preview"] },
  { method: "POST", shape: ["cost-gaps", "#", "preview"] },
  { method: "POST", shape: ["cost-gaps", "#", "observations"] },
  { method: "GET", shape: ["cost-imports"] },
  { method: "POST", shape: ["cost-imports", "inspect"] },
  { method: "POST", shape: ["cost-imports", "preview"] },
  { method: "POST", shape: ["cost-imports", "confirm"] },
  { method: "GET", shape: ["cost-backtests"] },
  { method: "POST", shape: ["cost-backtests"] },
  { method: "POST", shape: ["cost-backtests", "preview"] },
  { method: "GET", shape: ["cost-freezes"] },
  { method: "POST", shape: ["cost-freezes"] },
  { method: "POST", shape: ["cost-freezes", "preview"] },
  { method: "POST", shape: ["cost-freezes", "#", "decision-preview"] },
  { method: "POST", shape: ["cost-freezes", "#", "decide"] },
  { method: "GET", shape: ["cost-rollups", "options"] },
  { method: "POST", shape: ["cost-rollups", "preview"] },
  { method: "GET", shape: ["cost-rollups"] },
  { method: "POST", shape: ["cost-rollups"] },
  { method: "GET", shape: ["cost-inputs"] },
  { method: "POST", shape: ["cost-inputs", "#", "preview"] },
  { method: "POST", shape: ["cost-inputs", "#"] },
  { method: "GET", shape: ["supplier-notices", "candidates", "#", "applications"] },
  { method: "POST", shape: ["supplier-notices", "candidates", "#", "applications", "preview"] },
  { method: "POST", shape: ["supplier-notices", "candidates", "#", "applications"] },
  { method: "GET", shape: ["supplier-notices", "links"] },
  { method: "GET", shape: ["supplier-notices", "ecrs", "#", "impact"] },
  { method: "GET", shape: ["supplier-notices", "ecrs", "#", "analysis-context"] },
  { method: "GET", shape: ["supplier-notices", "candidates", "#", "reviews"] },
  { method: "GET", shape: ["supplier-notices", "candidates", "#", "text"] },
  { method: "POST", shape: ["supplier-notices", "candidates", "#", "reviews", "preview"] },
  { method: "POST", shape: ["supplier-notices", "candidates", "#", "reviews"] },
  { method: "GET", shape: ["supplier-notices", "watches", "#", "dispatches"] },
  { method: "POST", shape: ["supplier-notices", "watches", "#", "dispatches", "#", "retry"] },
  { method: "GET", shape: ["supplier-notices", "watches", "#", "scans"] },
  { method: "POST", shape: ["supplier-notices", "watches", "#", "scans"] },
  { method: "GET", shape: ["supplier-notices", "watches"] },
  { method: "POST", shape: ["supplier-notices", "watches"] },
  { method: "POST", shape: ["supplier-notices", "watches", "preview"] },
  { method: "POST", shape: ["supplier-recovery", "items", "#", "reviews", "preview"] },
  { method: "POST", shape: ["supplier-recovery", "items", "#", "reviews"] },
  { method: "GET", shape: ["supplier-recovery", "items", "#", "results"] },
  { method: "POST", shape: ["supplier-recovery", "items", "#", "results"] },
  { method: "POST", shape: ["supplier-recovery", "items", "#", "results", "preview"] },
  { method: "GET", shape: ["supplier-recovery", "work-packages"] },
  { method: "GET", shape: ["cost-reduction", "review-context"] },
  { method: "GET", shape: ["cost-reduction", "applications"] },
  { method: "GET", shape: ["cost-reduction", "runs"] },
  { method: "POST", shape: ["cost-reduction", "runs"] },
  { method: "GET", shape: ["cost-reduction", "sources"] },
  { method: "GET", shape: ["cost-reduction", "discussions"] },
  { method: "POST", shape: ["cost-reduction", "context"] },
  { method: "GET", shape: ["supplier-recovery", "runs"] },
  { method: "POST", shape: ["supplier-recovery", "runs"] },
  { method: "GET", shape: ["supplier-recovery", "sources"] },
  { method: "POST", shape: ["supplier-recovery", "context"] },
  { method: "GET", shape: ["tooling-rounds"] },
  { method: "POST", shape: ["tooling-rounds", "#", "preview"] },
  { method: "POST", shape: ["tooling-rounds", "#"] },
  { method: "GET", shape: ["changes", "#", "compliance"] },
  { method: "POST", shape: ["changes", "#", "compliance", "#"] },
  { method: "GET", shape: ["supplier-compliance"] },
  { method: "POST", shape: ["supplier-compliance", "#", "preview"] },
  { method: "POST", shape: ["supplier-compliance", "#"] },
  { method: "GET", shape: ["supplier-engineering"] },
  { method: "POST", shape: ["suppliers", "#", "engineering-records", "#", "preview"] },
  { method: "POST", shape: ["suppliers", "#", "engineering-records", "#"] },
  { method: "GET", shape: [] },
  { method: "GET", shape: ["supply-snapshots", "#", "sharing"] },
  { method: "POST", shape: ["supply-snapshots", "#", "sharing"] },
  { method: "GET", shape: ["supply-sharing"] },
  { method: "POST", shape: ["supply-sharing", "#", "decision"] },
  { method: "GET", shape: ["builds", "#", "material-movements"] },
  { method: "POST", shape: ["builds", "#", "material-movements"] },
  { method: "POST", shape: ["builds", "#", "material-movements", "preview"] },
  { method: "POST", shape: ["builds", "#", "material-movements", "#", "correction", "preview"] },
  { method: "POST", shape: ["builds", "#", "material-movements", "#", "correction"] },
  { method: "GET", shape: ["supply-snapshots", "#", "movements"] },
  { method: "POST", shape: ["material-movements", "#", "reconcile"] },
  { method: "GET", shape: ["material-exposure"] },
  { method: "GET", shape: ["supply-snapshots", "#", "supplier"] },
  { method: "POST", shape: ["supply-snapshots", "#", "supplier"] },
  { method: "GET", shape: ["material-admission", "build", "#"] },
  { method: "POST", shape: ["material-admission", "build", "#", "policy"] },
  { method: "POST", shape: ["material-admission", "build", "#", "waivers"] },
  { method: "POST", shape: ["material-admission", "build", "#", "waivers", "#", "decide"] },
  { method: "GET", shape: ["material-admission", "gate", "#"] },
  { method: "POST", shape: ["material-admission", "gate", "#", "policy"] },
  { method: "POST", shape: ["material-admission", "gate", "#", "waivers"] },
  { method: "POST", shape: ["material-admission", "gate", "#", "waivers", "#", "decide"] },
  { method: "GET", shape: ["material-exceptions", "#", "schedule"] },
  { method: "POST", shape: ["material-exceptions", "#", "schedule"] },
  { method: "GET", shape: ["material-exceptions"] },
  { method: "GET", shape: ["material-exceptions", "#"] },
  { method: "POST", shape: ["material-exceptions", "#", "review"] },
  { method: "POST", shape: ["material-exceptions", "#", "preview"] },
  { method: "POST", shape: ["builds", "#", "material-exceptions"] },
  { method: "GET", shape: ["supply-imports"] },
  { method: "GET", shape: ["supply-imports", "#"] },
  { method: "POST", shape: ["supply-imports", "inspect"] },
  { method: "POST", shape: ["supply-imports", "preview"] },
  { method: "POST", shape: ["supply-imports", "confirm"] },
  { method: "GET", shape: ["firmware-work-packages"] },
  { method: "POST", shape: ["firmware-work-packages"] },
  { method: "GET", shape: ["firmware-work-packages", "current"] },
  { method: "GET", shape: ["firmware-work-packages", "sources"] },
  { method: "GET", shape: ["firmware-work-packages", "#", "tasks"] },
  { method: "POST", shape: ["firmware-work-packages", "#", "tasks"] },
  { method: "GET", shape: ["firmware-task-results", "#"] },
  { method: "GET", shape: ["firmware-task-results", "#", "runs"] },
  { method: "POST", shape: ["firmware-task-results", "#"] },
  { method: "GET", shape: ["build-options"] },
  { method: "POST", shape: ["builds"] },
  { method: "PATCH", shape: ["builds", "#"] },
  { method: "POST", shape: ["builds", "#", "samples"] },
  { method: "GET", shape: ["builds", "#", "supply-allocations"] },
  { method: "GET", shape: ["builds", "#", "supply-allocations", "receipts", "#"] },
  { method: "POST", shape: ["builds", "#", "supply-allocations", "preview"] },
  { method: "POST", shape: ["builds", "#", "supply-allocations", "coverage-preview"] },
  { method: "POST", shape: ["builds", "#", "supply-allocations", "allocate"] },
  { method: "POST", shape: ["builds", "#", "supply-allocations", "release"] },
  { method: "GET", shape: ["builds", "#", "materials"] },
  { method: "POST", shape: ["builds", "#", "materials", "preview"] },
  { method: "POST", shape: ["builds", "#", "materials", "freeze"] },
  { method: "POST", shape: ["builds", "#", "materials", "revision-preview"] },
  { method: "POST", shape: ["builds", "#", "materials", "revise"] },
  { method: "POST", shape: ["certifications"] },
  { method: "POST", shape: ["certifications", "scan"] },
  { method: "GET", shape: ["sample-configurations"] },
  { method: "POST", shape: ["sample-configurations", "compare"] },
  { method: "POST", shape: ["sample-configurations", "compare-versions"] },
  { method: "GET", shape: ["samples", "#", "configuration-history"] },
  { method: "GET", shape: ["samples", "#", "configuration-edit-options"] },
  { method: "POST", shape: ["sample-signoffs"] },
  { method: "POST", shape: ["sample-signoffs", "#", "respond"] },
  { method: "PUT", shape: ["samples", "#", "build-configuration"] },
  { method: "GET", shape: ["test-cases", "#", "execution-preparation"] },
  { method: "POST", shape: ["test-cases", "#", "execution-preparation"] },
  { method: "GET", shape: ["test-cases", "#", "verification-path"] },
  { method: "PUT", shape: ["test-cases", "#", "verification-path"] },
  { method: "POST", shape: ["test-cases", "#", "result"] },
  { method: "GET", shape: ["test-cases", "#", "runs"] },
  { method: "POST", shape: ["test-cases", "#", "runs"] },
  { method: "POST", shape: ["test-cases", "#", "runs", "#", "complete"] },
  { method: "POST", shape: ["test-imports"] },
  { method: "POST", shape: ["test-import-requests"] },
  { method: "GET", shape: ["test-import-requests", "#"] },
  { method: "GET", shape: ["test-plans", "#", "imports"] },
  { method: "GET", shape: ["test-imports", "#", "preview"] },
  { method: "GET", shape: ["test-imports", "#", "sample-options"] },
  { method: "POST", shape: ["test-imports", "#", "resolve-samples"] },
  { method: "GET", shape: ["test-imports", "#", "mapping-options"] },
  { method: "GET", shape: ["test-imports", "#", "comparison"] },
  { method: "POST", shape: ["test-imports", "#", "reparse"] },
  { method: "POST", shape: ["test-imports", "#", "confirm"] },
  { method: "POST", shape: ["test-imports", "#", "execution-times"] },
  { method: "POST", shape: ["test-plans"] },
  { method: "GET", shape: ["test-templates"] },
  { method: "POST", shape: ["test-plans", "#", "template"] },
  { method: "POST", shape: ["test-plans", "#", "suggestions"] },
  { method: "POST", shape: ["test-plans", "#", "suggestion-requests"] },
  { method: "GET", shape: ["test-plans", "#", "suggestion-requests", "#"] },
  { method: "GET", shape: ["test-plans", "#", "suggestion-sources"] },
  { method: "POST", shape: ["test-plans", "#", "cases"] },
  { method: "POST", shape: ["test-plans", "#", "reports"] },
  { method: "POST", shape: ["test-reports", "#", "review"] },
];

function matches(shape: readonly string[], segments: string[]) {
  if (shape.length !== segments.length) return false;
  return shape.every((part, index) =>
    part === "#" ? isUuid(segments[index]) : part === segments[index],
  );
}

function allowedPath(method: Method, segments: string[]) {
  return ALLOWED.some(
    (entry) => entry.method === method && matches(entry.shape, segments),
  );
}

class ImportBodyTooLarge extends Error {}

async function readImportForm(request: Request): Promise<FormData> {
  const contentType = request.headers.get("content-type") ?? "";
  if (!contentType.startsWith("multipart/form-data;") || !request.body) {
    throw new InvalidRequestBodyError("Excel multipart form required");
  }
  const limit = 20 * 1024 * 1024 + 64 * 1024;
  if (Number(request.headers.get("content-length")) > limit) {
    throw new ImportBodyTooLarge();
  }
  const reader = request.body.getReader();
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) {
        await reader.cancel();
        throw new ImportBodyTooLarge();
      }
      chunks.push(new Uint8Array(value));
    }
  } finally {
    reader.releaseLock();
  }
  let incoming: FormData;
  try {
    incoming = await new Response(new Blob(chunks), {
      headers: { "Content-Type": contentType },
    }).formData();
  } catch {
    throw new InvalidRequestBodyError("Invalid multipart form");
  }
  const file = incoming.get("file");
  const planId = incoming.get("plan_id");
  if (
    !(file instanceof File) || typeof planId !== "string" || !isUuid(planId) ||
    incoming.getAll("file").length !== 1 || incoming.getAll("plan_id").length !== 1 ||
    !file.name.toLowerCase().endsWith(".xlsx") || file.size === 0
  ) {
    throw new InvalidRequestBodyError("Excel file and test plan required");
  }
  if (file.size > 20 * 1024 * 1024) throw new ImportBodyTooLarge();
  const outgoing = new FormData();
  outgoing.set("plan_id", planId);
  outgoing.set("file", file, file.name);
  return outgoing;
}

export async function forwardNpi(
  method: Method,
  request: Request,
  context: Context,
) {
  const { projectId, npiPath } = await context.params;
  const incoming = npiPath ?? [];
  const segments = method === "POST" && incoming.length === 3 && incoming[0] === "test-plans"
    && incoming[2] === "suggestions" && process.env.PDOS_AI_TEST_PLAN_ASYNC === "true"
    ? [incoming[0], incoming[1], "suggestion-requests"]
    : method === "POST" && incoming.length === 1 && incoming[0] === "test-imports"
      && process.env.PDOS_AI_REPORT_IMPORT_ASYNC === "true" ? ["test-import-requests"] : incoming;
  if (!allowedPath(method, segments)) {
    return sessionError(404, "NPI_ROUTE_NOT_FOUND", "NPI route not found");
  }
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    if (method === "POST" && segments.length === 1 && ["test-imports", "test-import-requests"].includes(segments[0])) {
      const form = await readImportForm(request);
      return forwardJson(
        await pdosApiFetch(
          `/api/projects/${encodeURIComponent(projectId)}/npi/${segments[0]}`,
          { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: form },
          120_000,
        ),
      );
    }
    const body = method === "GET" ? undefined : await readBoundedJson(request);
    const suffix = segments.map(encodeURIComponent).join("/");
    const query = method === "GET" ? new URL(request.url).search : "";
    const path = `/api/projects/${encodeURIComponent(projectId)}/npi${
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
      }, (segments.at(-1) === "suggestions" || (segments[0] === "cost-reduction" && segments[1] === "runs" && method === "POST")) ? 120_000 : undefined),
    );
  } catch (error) {
    if (error instanceof ImportBodyTooLarge) {
      return sessionError(413, "IMPORT_FILE_TOO_LARGE", "Excel file must not exceed 20 MiB");
    }
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "Invalid request body");
    }
    return sessionError(503, "NPI_SERVICE_UNAVAILABLE", "NPI service unavailable");
  }
}
