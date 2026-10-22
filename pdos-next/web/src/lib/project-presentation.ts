import type { PortfolioProject } from "./portfolio-reads";

export type ProjectGrouping = "stage" | "owner" | "category";
export type ProjectView = "list" | "board" | "timeline";
export type ProjectFilters = { query: string; ownerId: string; categoryId: string };
export type ProjectGroup = { id: string; label: string; entries: PortfolioProject[] };

export function projectOwner(entry: PortfolioProject): string {
  return entry.project.owner_name || "负责人姓名暂不可读";
}

/** Filters the authorized read set, without inferring roles or permissions. */
export function filterProjects(entries: PortfolioProject[], filters: ProjectFilters): PortfolioProject[] {
  const query = filters.query.trim().toLocaleLowerCase();
  return entries.filter(entry => (!filters.ownerId || entry.project.owner_id === filters.ownerId)
    && (!filters.categoryId || entry.category.id === filters.categoryId)
    && (!query || [entry.project.id, entry.project.name, entry.product.name, entry.category.name,
      entry.project.definition.title, entry.project.owner_name ?? ""].some(value => value.toLocaleLowerCase().includes(query))));
}

/** Stages require actual templates. Plan status cannot stand in for a stage. */
export function groupProjects(entries: PortfolioProject[], grouping: ProjectGrouping): ProjectGroup[] {
  const groups = new Map<string, ProjectGroup>();
  for (const entry of entries) {
    const id = grouping === "owner" ? entry.project.owner_id : grouping === "category" ? entry.category.id : "stage-unavailable";
    const label = grouping === "owner" ? projectOwner(entry) : grouping === "category" ? entry.category.name : "阶段记录待接入";
    if (!groups.has(id)) groups.set(id, { id, label, entries: [] });
    groups.get(id)!.entries.push(entry);
  }
  return [...groups.values()];
}

export function projectForecast(entry: PortfolioProject): { earliest: string | null; latest: string | null } {
  if (entry.project.plan_state !== "available") return { earliest: null, latest: null };
  const forecast = entry.project.plan?.forecast;
  return { earliest: validDate(forecast?.earliest_finish), latest: validDate(forecast?.latest_finish) };
}

function validDate(value: string | null | undefined): string | null {
  return value && Number.isFinite(Date.parse(value)) ? value : null;
}

export function formatProjectDate(value: string | null): string {
  if (!value) return "未知";
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", timeZone: "UTC" }).format(new Date(value));
}

/** Finish bounds, never a stage duration or a gate date. */
export function forecastAxis(entries: PortfolioProject[]): { start: number; end: number } | null {
  const points = entries.flatMap(entry => Object.values(projectForecast(entry)).filter((date): date is string => !!date).map(Date.parse));
  if (!points.length) return null;
  return { start: Math.min(...points) - 86_400_000, end: Math.max(...points) + 86_400_000 };
}

export function forecastPosition(entry: PortfolioProject, axis: { start: number; end: number }): { left: number; width: number } | null {
  const { earliest, latest } = projectForecast(entry);
  if (!earliest || !latest || Date.parse(latest) < Date.parse(earliest) || axis.end <= axis.start) return null;
  const span = axis.end - axis.start;
  return { left: (Date.parse(earliest) - axis.start) / span * 100, width: (Date.parse(latest) - Date.parse(earliest)) / span * 100 };
}
