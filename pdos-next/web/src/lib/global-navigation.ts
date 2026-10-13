export type GlobalArea = "work" | "cockpit" | "projects" | "programs" | "category" | "knowledge" | "settings";
export type GlobalLocation = { area: GlobalArea; categoryId: string; projectId: string };
export type GlobalAreaEntry = { id: GlobalArea; label: string; planned?: boolean };

/** 全局入口（用户 2026-10-13 定）：项目管理是主体，品类工作是项目前置。 */
export const globalAreas: GlobalAreaEntry[] = [
  { id: "work", label: "我的工作" },
  { id: "cockpit", label: "项目驾驶舱" },
  { id: "projects", label: "项目列表" },
  { id: "programs", label: "项目集", planned: true },
  { id: "category", label: "产品品类工作区" },
  { id: "knowledge", label: "知识" },
  { id: "settings", label: "设置" },
];

export const defaultGlobalLocation: GlobalLocation = { area: "work", categoryId: "", projectId: "" };

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
  if (location.categoryId) params.set("category", location.categoryId); else params.delete("category");
  if (location.projectId) params.set("project", location.projectId); else params.delete("project");
  if (location.area !== "category") { params.delete("bench"); params.delete("view"); params.delete("task"); params.delete("product"); }
  return `?${params.toString()}`;
}

/** 旧 URL 规范化为新结构的一次性映射；未变化时 changed=false。 */
export function normalizeGlobalSearch(search: string): { search: string; changed: boolean } {
  const params = new URLSearchParams(search);
  const raw = params.get("area") ?? "";
  if (raw === "resources" && params.get("category")) {
    params.set("area", "programs"); params.delete("category"); params.delete("view"); params.delete("task"); params.delete("product");
    return { search: `?${params.toString()}`, changed: true };
  }
  if (legacyBenchAreas.has(raw) && params.get("category")) {
    params.set("area", raw === "knowledge" ? "knowledge" : "category");
    params.set("bench", raw === "knowledge" ? "knowledge" : raw);
    return { search: `?${params.toString()}`, changed: true };
  }
  if (!raw && params.get("category")) { params.set("area", "category"); return { search: `?${params.toString()}`, changed: true }; }
  return { search, changed: false };
}
