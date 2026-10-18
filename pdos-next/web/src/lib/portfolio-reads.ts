import type { Project, PlanForecast } from "@/lib/project-plan-view";
import type { NamedProjectUpdate } from "@/lib/project-status-update";

export type PortfolioApi = <T>(path: string, body?: unknown) => Promise<T>;
export type PortfolioCategory = { id: string; name: string; purpose: string };
export type PortfolioProduct = { id: string; name: string; purpose: string };
export type OpenItem = { id: string; kind: string; title: string; owner_id: string; owner_name?: string | null; due_date: string | null; status: string };
export type PortfolioProject = {
  project: Pick<Project, "id" | "name" | "purpose" | "scope" | "owner_id" | "visibility" | "revision" | "status" | "source_status" | "created_at" | "definition" | "work_packages"> & {
    plan: { id: string; revision: number; status: string; forecast: Pick<PlanForecast, "earliest_finish" | "latest_finish"> } | null;
    plan_state: "available" | "not_created" | "unavailable";
    task_count: number | null;
    owner_name?: string | null;
    latest_status_update?: NamedProjectUpdate | null;
  };
  category: PortfolioCategory;
  product: PortfolioProduct;
  openItems: OpenItem[];
  openItemsError: string;
};
export type Portfolio = {
  projects: PortfolioProject[];
  categories: PortfolioCategory[];
  readErrors: { path: string; message: string }[];
  asOf?: string;
};
export type MyOpenItem = OpenItem & { projectId: string; projectName: string; categoryId: string; productId: string };
export type DueState = "overdue" | "soon" | "scheduled" | "none";

type ProjectPage = { items: PortfolioProject[]; next_cursor: string | null; unavailable_count: number; as_of: string };
export type ActivityRun = { run_id: string; goal: string; status: string; created_at: string; product_id: string | null; scope: "personal" | "category"; categoryId: string; categoryName: string };
type ActivityPage = { items: ActivityRun[]; next_cursor: string | null; as_of: string };

/** 服务端按当前权限投影，连续读取全部页；单项目直接读取，避免扫描其他项目。 */
export async function readPortfolio(api: PortfolioApi, projectId?: string): Promise<Portfolio> {
  const projects = new Map<string, PortfolioProject>();
  const categories = new Map<string, PortfolioCategory>();
  const seen = new Set<string>();
  let cursor: string | null = null, unavailable = 0, asOf: string | undefined;
  do {
    const path: string = projectId ? `v1/personal/projects/${projectId}`
      : `v1/personal/projects?page_size=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
    const page: ProjectPage = await api<ProjectPage>(path);
    asOf = page.as_of;
    for (const entry of page.items) {
      projects.set(entry.project.id, entry);
      categories.set(entry.category.id, entry.category);
    }
    unavailable += page.unavailable_count;
    cursor = projectId ? null : page.next_cursor;
    if (cursor && seen.has(cursor)) throw new Error("项目分页位置未推进，请刷新重试。");
    if (cursor) seen.add(cursor);
  } while (cursor);
  return {
    projects: [...projects.values()], categories: [...categories.values()], asOf,
    readErrors: unavailable ? [{ path: "v1/personal/projects", message: `${unavailable} 个项目的关联资料当前不可读，请核对权限后刷新。` }] : [],
  };
}

/** 最近运行取明确的前 12 次；等待答复连续翻页，不会被最近记录挤掉。 */
export async function readRunActivity(api: PortfolioApi, waiting = false): Promise<ActivityRun[]> {
  const runs = new Map<string, ActivityRun>(), seen = new Set<string>();
  let cursor: string | null = null;
  do {
    const page: ActivityPage = await api<ActivityPage>(`v1/personal/run-activity?page_size=${waiting ? 100 : 12}&waiting=${waiting}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
    for (const run of page.items) runs.set(run.run_id, run);
    cursor = waiting ? page.next_cursor : null;
    if (cursor && seen.has(cursor)) throw new Error("运行分页位置未推进，请刷新重试。");
    if (cursor) seen.add(cursor);
  } while (cursor);
  return [...runs.values()];
}

export function findProject(portfolio: Portfolio, projectId: string): PortfolioProject | undefined {
  return portfolio.projects.find(entry => entry.project.id === projectId);
}

const closedItemStatuses = new Set(["done", "closed", "cancelled"]);

export function myOpenItems(portfolio: Portfolio, principalId: string): MyOpenItem[] {
  const mine: MyOpenItem[] = [];
  for (const entry of portfolio.projects) {
    for (const item of entry.openItems) {
      if (item.owner_id !== principalId || closedItemStatuses.has(item.status)) continue;
      mine.push({ ...item, projectId: entry.project.id, projectName: entry.project.name, categoryId: entry.category.id, productId: entry.product.id });
    }
  }
  return mine.sort((a, b) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999"));
}

export function openRisks(entry: PortfolioProject): OpenItem[] {
  return entry.openItems.filter(item => item.kind === "risk" && item.status === "open");
}

/** 到期状态按日期字符串比较；now 为 YYYY-MM-DD。逾期与 7 天内到期需要处置。 */
export function dueState(item: Pick<OpenItem, "due_date" | "status">, now: string): DueState {
  if (!item.due_date || closedItemStatuses.has(item.status)) return "none";
  if (item.due_date < now) return "overdue";
  const soon = new Date(`${now}T00:00:00Z`);
  soon.setUTCDate(soon.getUTCDate() + 7);
  if (item.due_date <= soon.toISOString().slice(0, 10)) return "soon";
  return "scheduled";
}

export function openTasks(entry: PortfolioProject, now: string): { overdue: OpenItem[]; soon: OpenItem[] } {
  const tasks = entry.openItems.filter(item => item.kind === "task");
  return {
    overdue: tasks.filter(item => dueState(item, now) === "overdue"),
    soon: tasks.filter(item => dueState(item, now) === "soon"),
  };
}

/** 与品类工作台项目行一致的状态口径：来源需重核优先于计划状态。 */
export function projectStateLabel(entry: PortfolioProject): string {
  if (entry.project.source_status !== "current") return "需重核";
  return entry.project.plan_state === "unavailable" ? "计划暂不可读" : entry.project.plan ? "已有计划" : "待建计划";
}

export type CategoryGroup = { category: PortfolioCategory; products: { product: PortfolioProduct; entries: PortfolioProject[] }[] };

export function groupByCategory(portfolio: Portfolio): CategoryGroup[] {
  const groups: CategoryGroup[] = [];
  for (const entry of portfolio.projects) {
    let group = groups.find(item => item.category.id === entry.category.id);
    if (!group) { group = { category: entry.category, products: [] }; groups.push(group); }
    let productGroup = group.products.find(item => item.product.id === entry.product.id);
    if (!productGroup) { productGroup = { product: entry.product, entries: [] }; group.products.push(productGroup); }
    productGroup.entries.push(entry);
  }
  return groups;
}
