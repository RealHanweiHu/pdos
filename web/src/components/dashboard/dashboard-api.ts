import { isRecord, responseBody } from "@/components/workspace-api";

export type DashboardRisk = {
  id: string;
  project_id: string;
  title: string;
  status: "open" | "mitigating" | "watching";
  likelihood: number;
  impact: number;
  score: number;
  updated_at: string;
  project: { id: string; code: string; name: string };
};

export type DashboardRiskSummary = {
  project_id: string;
  open_risk_count: number;
  max_score: number;
};

export type DashboardRisks = {
  items: DashboardRisk[];
  total: number;
  projects: DashboardRiskSummary[];
};

function isNonemptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isIntegerBetween(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= minimum && value <= maximum;
}

function isDashboardRisk(value: unknown): value is DashboardRisk {
  if (!isRecord(value) || !isRecord(value.project)) return false;
  return isNonemptyString(value.id) && isNonemptyString(value.project_id) && isNonemptyString(value.title) &&
    typeof value.status === "string" && ["open", "mitigating", "watching"].includes(value.status) &&
    isIntegerBetween(value.likelihood, 1, 5) && isIntegerBetween(value.impact, 1, 5) &&
    value.score === value.likelihood * value.impact &&
    typeof value.updated_at === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value.updated_at) &&
    Number.isFinite(Date.parse(value.updated_at)) &&
    value.project.id === value.project_id && isNonemptyString(value.project.code) && isNonemptyString(value.project.name);
}

function isRiskSummary(value: unknown): value is DashboardRiskSummary {
  return isRecord(value) && isNonemptyString(value.project_id) &&
    isIntegerBetween(value.open_risk_count, 0, Number.MAX_SAFE_INTEGER) &&
    isIntegerBetween(value.max_score, value.open_risk_count === 0 ? 0 : 1, value.open_risk_count === 0 ? 0 : 25);
}

export function parseDashboardRisks(body: unknown): DashboardRisks {
  if (!isRecord(body) || !Array.isArray(body.items) || !body.items.every(isDashboardRisk) ||
    !isIntegerBetween(body.total, 0, Number.MAX_SAFE_INTEGER) || body.items.length !== Math.min(body.total, 8) ||
    !Array.isArray(body.projects) || !body.projects.every(isRiskSummary)) {
    throw new Error("invalid dashboard risk response");
  }
  const items: DashboardRisk[] = body.items;
  const projects: DashboardRiskSummary[] = body.projects;
  const summaries = new Map(projects.map((project) => [project.project_id, project]));
  if (summaries.size !== projects.length || new Set(items.map((item) => item.id)).size !== items.length ||
    projects.reduce((total, project) => total + project.open_risk_count, 0) !== body.total) {
    throw new Error("inconsistent dashboard risk summary");
  }
  const rankedCounts = new Map<string, number>();
  for (const item of items) {
    const summary = summaries.get(item.project_id);
    const rankedCount = (rankedCounts.get(item.project_id) ?? 0) + 1;
    if (!summary || summary.open_risk_count < rankedCount || summary.max_score < item.score) {
      throw new Error("inconsistent dashboard risk summary");
    }
    rankedCounts.set(item.project_id, rankedCount);
  }
  return { items, total: body.total, projects };
}

export async function requestDashboardRisks(): Promise<DashboardRisks> {
  const response = await fetch("/api/dashboard/risks", { cache: "no-store", credentials: "same-origin" });
  if (!response.ok) throw new Error(`Dashboard risk request failed (${response.status})`);
  return parseDashboardRisks(await responseBody(response));
}
