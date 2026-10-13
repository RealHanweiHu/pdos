import type { Project, ProjectList } from "@/lib/project-plan-view";

export type PortfolioApi = <T>(path: string, body?: unknown) => Promise<T>;
export type PortfolioCategory = { id: string; name: string; purpose: string };
export type PortfolioProduct = { id: string; name: string; purpose: string };
export type OpenItem = { id: string; kind: string; title: string; owner_id: string; due_date: string | null; status: string };
export type PortfolioProject = {
  project: Project;
  category: PortfolioCategory;
  product: PortfolioProduct;
  openItems: OpenItem[];
  openItemsError: string;
};
export type Portfolio = {
  projects: PortfolioProject[];
  categories: PortfolioCategory[];
  readErrors: { path: string; message: string }[];
};
export type MyOpenItem = OpenItem & { projectId: string; projectName: string; categoryId: string; productId: string };
export type DueState = "overdue" | "soon" | "scheduled" | "none";

/** 逐品类汇总本人权限内的项目与未决事项；权限过滤由服务端完成。跨品类投影端点接入后替换。 */
export async function readPortfolio(api: PortfolioApi): Promise<Portfolio> {
  const readErrors: { path: string; message: string }[] = [];
  let categories: PortfolioCategory[] = [];
  try {
    categories = await api<PortfolioCategory[]>("v1/categories");
  } catch (failure) {
    readErrors.push({ path: "v1/categories", message: (failure as Error).message });
    return { projects: [], categories, readErrors };
  }
  const projects: PortfolioProject[] = [];
  await Promise.all(categories.map(async category => {
    let products: PortfolioProduct[] = [];
    try {
      products = await api<PortfolioProduct[]>(`v1/categories/${category.id}/products`);
    } catch (failure) {
      readErrors.push({ path: `v1/categories/${category.id}/products`, message: (failure as Error).message });
      return;
    }
    await Promise.all(products.map(async product => {
      let list: ProjectList;
      try {
        list = await api<ProjectList>(`v1/categories/${category.id}/products/${product.id}/projects`);
      } catch (failure) {
        readErrors.push({ path: `v1/categories/${category.id}/products/${product.id}/projects`, message: (failure as Error).message });
        return;
      }
      await Promise.all(list.items.map(async project => {
        const entry: PortfolioProject = { project, category, product, openItems: [], openItemsError: "" };
        try {
          const result = await api<{ items: OpenItem[] }>(`v1/categories/${category.id}/projects/${project.id}/open-items`);
          entry.openItems = result.items;
        } catch (failure) {
          entry.openItemsError = (failure as Error).message;
        }
        projects.push(entry);
      }));
    }));
  }));
  projects.sort((a, b) => b.project.created_at.localeCompare(a.project.created_at));
  return { projects, categories, readErrors };
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
  return entry.project.plan ? "已有计划" : "待建计划";
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
