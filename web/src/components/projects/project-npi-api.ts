import { EMPTY_NPI_SNAPSHOT, type NpiSnapshot, type TestTemplate, type TestTemplateSelection } from "./project-npi-types";

export class NpiRequestError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

async function readError(response: Response): Promise<NpiRequestError> {
  const fallback = response.status >= 500
    ? "试制与测试服务暂时不可用，请刷新确认当前记录后重试。"
    : "操作未完成，请核对所填资料后重试。";
  try {
    const body = await response.json();
    const detail = body?.detail ?? body ?? {};
    return new NpiRequestError(
      detail.code ?? "NPI_REQUEST_FAILED",
      detail.message ?? fallback,
    );
  } catch {
    return new NpiRequestError("NPI_REQUEST_FAILED", fallback);
  }
}

export async function fetchNpiSnapshot(projectId: string): Promise<NpiSnapshot> {
  const response = await fetch(`/api/projects/${projectId}/npi`, {
    cache: "no-store",
  });
  if (!response.ok) throw await readError(response);
  const body = await response.json();
  // The backend omits collections a role may not see (suppliers and customers
  // get sign-offs only), so every key is defaulted rather than assumed.
  return { ...EMPTY_NPI_SNAPSHOT, ...body };
}

async function write(
  path: string,
  method: "POST" | "PATCH" | "PUT",
  body: unknown,
): Promise<unknown> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!response.ok) throw await readError(response);
  return response.json();
}

export async function fetchTestTemplates(projectId: string): Promise<{
  templates: TestTemplate[];
  product_scope_message?: string;
  stages: { id: string; code: BuildPhase; name: string }[];
}> {
  const response = await fetch(`/api/projects/${projectId}/npi/test-templates`, { cache: "no-store" });
  if (!response.ok) throw await readError(response);
  return response.json();
}

export function saveTestTemplate(projectId: string, selection: TestTemplateSelection,
  target: { planId: string } | { stage_id: string; phase: BuildPhase; title: string; sample_size: number }) {
  if ("planId" in target) {
    return write(`/api/projects/${projectId}/npi/test-plans/${target.planId}/template`, "POST", selection);
  }
  return write(`/api/projects/${projectId}/npi/test-plans`, "POST", { ...target, template: selection });
}

// The backend models all use `extra="forbid"`, so these payload types mirror
// the server contracts exactly — an extra field is a 422, not a warning.

export type BuildPhase = "evt" | "dvt" | "pvt";

export const BUILD_PURPOSE_LABELS = {
  engineering_build: "工程试制", certification_sample: "认证样机",
  customer_sample: "客户样机", reliability_test: "可靠性测试", production_trial: "生产试制",
};
export type BuildPurpose = keyof typeof BUILD_PURPOSE_LABELS;
export async function fetchBuildOptions(projectId: string): Promise<{
  stages: { id: string; code: BuildPhase; name: string }[];
}> {
  const response = await fetch(`/api/projects/${projectId}/npi/build-options`, { cache: "no-store" });
  if (!response.ok) throw await readError(response);
  return response.json();
}

export function createBuild(
  projectId: string,
  body: {
    stage_id: string;
    phase: BuildPhase;
    purpose?: BuildPurpose;
    code: string;
    planned_quantity: number;
    notes?: string | null;
  },
) {
  return write(`/api/projects/${projectId}/npi/builds`, "POST", body);
}

export function updateBuild(
  projectId: string,
  buildId: string,
  body: { status: "in_progress" | "completed" | "cancelled"; completed_quantity: number },
) {
  return write(`/api/projects/${projectId}/npi/builds/${buildId}`, "PATCH", body);
}

export function addSample(
  projectId: string,
  buildId: string,
  body: {
    serial_number: string;
    parent_sample_id?: string | null;
    prototype_bom_id?: string | null;
    notes?: string | null;
  },
) {
  return write(
    `/api/projects/${projectId}/npi/builds/${buildId}/samples`,
    "POST",
    body,
  );
}

export function recordTestResult(
  projectId: string,
  testCaseId: string,
  body: {
    status: "planned" | "passed" | "failed" | "blocked" | "waived";
    result_notes?: string | null;
    related_issue_id?: string | null;
  },
) {
  return write(
    `/api/projects/${projectId}/npi/test-cases/${testCaseId}/result`,
    "POST",
    body,
  );
}

export type TestImportBatch = {
  id: string;
  project_id: string;
  plan_id: string;
  document_id: string;
  status: "parsed" | "confirmed";
  created_run_ids: string[];
  skipped_rows: { sheet?: string; reason: string }[];
  reused_existing: boolean;
};

export type TestImportOperation = {
  run_id: string | null;
  status: string;
  batch: TestImportBatch | null;
  error_code: string | null;
};

export async function readTestImport(projectId: string, runId: string): Promise<TestImportOperation> {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/npi/test-import-requests/${encodeURIComponent(runId)}`, { cache: "no-store" });
  if (!response.ok) throw await readError(response);
  return response.json();
}

export async function uploadTestReport(projectId: string, planId: string, file: File): Promise<TestImportBatch | TestImportOperation> {
  const body = new FormData();
  body.set("plan_id", planId);
  body.set("file", file);
  const response = await fetch(`/api/projects/${projectId}/npi/test-imports`, { method: "POST", body });
  if (!response.ok) throw await readError(response);
  return response.json();
}
