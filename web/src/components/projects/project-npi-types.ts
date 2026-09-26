/** Shapes returned by `GET /api/projects/{id}/npi`. */

export type NpiBuild = {
  id: string;
  code: string;
  phase: string;
  status: string;
  planned_quantity: number;
  purpose?: string;
  notes?: string | null;
};

export type NpiSample = {
  id: string;
  build_batch_id: string;
  serial_number: string;
  status: string;
  notes?: string | null;
};

export type NpiTestPlan = {
  template_snapshot?: { plan_revision?: number } | null;
  parent_plan_id?: string | null;
  source_finding_id?: string | null;
  id: string;
  title: string;
  phase: string;
  status: string;
  coverage?: TestCoverage;
};

export type TestCoverage = {
  scope_status?: "unconfigured" | "current" | "changed";
  scope_message?: string;
  status: "configured" | "unconfigured";
  template_name?: string;
  version?: number;
  required: number | null;
  covered: number | null;
  coverage_percent: number | null;
  passed?: number;
  failed?: number;
  missing?: number;
  not_applicable?: number;
  items: { key: string; title: string; state: string; reason: string | null }[];
};

export type TestTemplate = {
  locked_exclusions?: Record<string, string>;
  required_enabled?: string[];
  id: string;
  name: string;
  version: number;
  product_type: string;
  items: { key: string; title: string; required: boolean; method: string; acceptance_criteria: string }[];
};

export type TestTemplateSelection = {
  template_id: string;
  version: number;
  product_type: string;
  exclusions: { key: string; reason: string }[];
};

export type NpiTestCase = {
  id: string;
  plan_id: string;
  title: string;
  status: string;
  sample_ids?: string[];
};

export type NpiTestReport = {
  id: string;
  plan_id: string;
  title: string;
  status: string;
};

export type NpiSampleSignoff = {
  id: string;
  audience: string;
  status: string;
  sample_ids: string[];
};

export type NpiCertification = {
  id: string;
  standard: string;
  status: string;
  expires_on?: string | null;
};

export type NpiSnapshot = {
  builds: NpiBuild[];
  samples: NpiSample[];
  sample_signoffs: NpiSampleSignoff[];
  test_plans: NpiTestPlan[];
  test_cases: NpiTestCase[];
  test_reports: NpiTestReport[];
  certifications: NpiCertification[];
  certification_alerts: unknown[];
};

export const EMPTY_NPI_SNAPSHOT: NpiSnapshot = {
  builds: [],
  samples: [],
  sample_signoffs: [],
  test_plans: [],
  test_cases: [],
  test_reports: [],
  certifications: [],
  certification_alerts: [],
};

// Build batches are EVT/DVT/PVT only — MP is a production phase, not a build
// batch, and the database CHECK refuses it.
export const BUILD_PHASE_LABELS: Record<string, string> = {
  evt: "EVT",
  dvt: "DVT",
  pvt: "PVT",
};

export const BUILD_STATUS_LABELS: Record<string, string> = {
  planned: "已计划",
  in_progress: "进行中",
  completed: "已完成",
  cancelled: "已取消",
};

export const SAMPLE_STATUS_LABELS: Record<string, string> = {
  planned: "待制作",
  built: "已制作",
  scrapped: "已报废",
  returned: "已返还",
};

export const TEST_CASE_STATUS_LABELS: Record<string, string> = {
  planned: "待执行",
  passed: "通过",
  failed: "失败",
  blocked: "阻塞",
  waived: "豁免",
};

export function labelFor(
  labels: Record<string, string>,
  value: string | null | undefined,
): string {
  if (!value) return "—";
  return labels[value] ?? value;
}
