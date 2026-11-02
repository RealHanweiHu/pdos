export type GlobalArea = "work" | "inbox" | "pai" | "cockpit" | "projects" | "programs" | "category" | "knowledge" | "settings";
export type GlobalLocation = { area: GlobalArea; categoryId: string; projectId: string };
export type GlobalAreaEntry = { id: GlobalArea; label: string; group?: "main" | "product_management"; planned?: boolean };
export type NavigationCategory = { id: string; capabilities?: { product_management?: boolean } };

/** 已确认的产品导航；项目工作区保留深链，产品管理仍按服务器授权显示。 */
export const globalAreas: GlobalAreaEntry[] = [
  { id: "work", label: "我的工作", group: "main" },
  { id: "inbox", label: "收件箱", group: "main" },
  { id: "pai", label: "小Pai", group: "main" },
  { id: "projects", label: "项目", group: "main" },
  { id: "programs", label: "项目集", group: "main" },
  { id: "knowledge", label: "知识", group: "main" },
  { id: "category", label: "品类", group: "product_management" },
  { id: "cockpit", label: "项目工作区" },
  { id: "settings", label: "设置" },
];

export const defaultGlobalLocation: GlobalLocation = { area: "work", categoryId: "", projectId: "" };

/** 只消费服务器对当前有效 Grant 的投影；普通可读、can_write 或岗位名称都不能补授此能力。 */
export function productManagementCategories<T extends NavigationCategory>(categories: T[]): T[] {
  return categories.filter(category => category.capabilities?.product_management === true);
}

export function productManagementHref(categoryId = "", view: "categories" | "proposals" = "categories"): string {
  const params = new URLSearchParams({ area: "category" });
  if (categoryId) params.set("category", categoryId);
  if (view === "proposals") params.set("focus", "proposals");
  return `?${params.toString()}`;
}

/** 旧品类工作区 area 值到新全局结构的映射。旧"项目"即品类内项目执行区。 */
const legacyBenchAreas = new Set(["products", "projects", "knowledge", "settings"]);

export function resolveGlobalLocation(search: string): GlobalLocation {
  const params = new URLSearchParams(search);
  const categoryId = params.get("category") ?? "";
  const projectId = params.get("project") ?? "";
  const raw = params.get("area") ?? "";
  if (globalAreas.some(entry => entry.id === raw)) return { area: raw as GlobalArea, categoryId, projectId };
  // 旧链接：?category=x&area=products|projects|knowledge|settings → 品类工作区内对应区。
  if (legacyBenchAreas.has(raw) && categoryId) return { area: raw === "knowledge" ? "knowledge" : "category", categoryId, projectId };
  if (!raw && categoryId) return { area: "category", categoryId, projectId };
  return { area: "work", categoryId, projectId };
}

export function globalHref(location: GlobalLocation, search = ""): string {
  const params = new URLSearchParams(search);
  params.set("area", location.area);
  params.delete("projectView"); params.delete("panel");
  for (const key of ["build", "request", "run", "issue", "change", "feedback", "publication"]) params.delete(key);
  if (location.categoryId) params.set("category", location.categoryId); else params.delete("category");
  if (location.projectId) params.set("project", location.projectId); else params.delete("project");
  if (location.area !== "category") { params.delete("bench"); params.delete("view"); params.delete("task"); params.delete("product"); params.delete("focus"); }
  return `?${params.toString()}`;
}

export function projectWorkbenchHref(categoryId: string, productId: string, projectId: string): string {
  return `?${new URLSearchParams({ area: "category", category: categoryId, bench: "projects", view: "plan", product: productId, project: projectId })}`;
}

/** 旧 URL 规范化为新结构的一次性映射；未变化时 changed=false。 */
export function normalizeGlobalSearch(search: string): { search: string; changed: boolean } {
  const params = new URLSearchParams(search);
  const raw = params.get("area") ?? "";
  // Existing project deep links enter the same project surface; preserve fixed object IDs.
  if (params.get("category") && params.get("product") && params.get("project") && raw === "category" && params.get("bench") === "projects") {
    const section = params.get("view") ?? "overview", task = params.get("task") ?? "";
    const destination: Record<string, [string, string]> = {
      overview: ["now", ""], plan: ["plan", ""], issues: ["issues", ["followup", "changes"].includes(task) ? task : "quality"],
      field: ["feedback", "field"], reviews: ["review", ["exceptions", "external"].includes(task) ? task : "packages"], files: ["docs", "originals"],
      builds: task === "prepare" || !task ? ["prep", "build"] : ["supply", "cost"].includes(task) ? ["prep", task] : ["builds", task],
      verification: ["builds", task === "prepare" || !task ? "verification" : task === "request" ? "professional" : task],
    };
    if (destination[section]) {
      const [view, panel] = destination[section];
      params.set("area", "cockpit"); params.set("projectView", view);
      if (panel) params.set("panel", panel); else params.delete("panel");
      params.delete("bench"); params.delete("view"); params.delete("task");
      return { search: `?${params.toString()}`, changed: true };
    }
  }
  if (raw === "resources" && params.get("category")) {
    params.set("area", "work"); params.delete("category"); params.delete("view"); params.delete("task"); params.delete("product"); params.delete("project");
    return { search: `?${params.toString()}`, changed: true };
  }
  // 同名全局入口不携带旧工作台参数；带 bench 的链接已经规范化。
  const legacyView = !params.has("bench") && ["view", "task", "product"].some(key => params.has(key));
  if (legacyBenchAreas.has(raw) && params.get("category") && (raw === "products" || legacyView)) {
    params.set("area", raw === "knowledge" ? "knowledge" : "category");
    params.set("bench", raw === "knowledge" ? "knowledge" : raw);
    const normalized = normalizeGlobalSearch(`?${params.toString()}`);
    return { search: normalized.search, changed: true };
  }
  if (!raw && params.get("category")) { params.set("area", "category"); return { search: `?${params.toString()}`, changed: true }; }
  return { search, changed: false };
}
