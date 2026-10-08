export type WorkspaceArea = "work" | "products" | "projects" | "resources" | "knowledge" | "settings";
export type WorkspaceLocation = { area: WorkspaceArea; section: string; task: string; productId: string };
export type WorkspaceEntry = { id: string; label: string; panel?: string; planned?: boolean };

export const workspaceAreas: { id: WorkspaceArea; label: string }[] = [
  { id: "work", label: "我的工作" }, { id: "products", label: "产品" },
  { id: "projects", label: "项目" }, { id: "resources", label: "组合与资源" },
  { id: "knowledge", label: "知识" }, { id: "settings", label: "设置" },
];

export const workspaceSections: Record<WorkspaceArea, WorkspaceEntry[]> = {
  work: [{ id: "overview", label: "待处理", panel: "work" }, { id: "activity", label: "活动", panel: "activity" }],
  products: [
    { id: "overview", label: "总览" }, { id: "research", label: "研究" },
    { id: "opportunities", label: "机会与实验", planned: true },
    { id: "definition", label: "定义与规格", panel: "definition" },
    { id: "variants", label: "派生与配置", panel: "variants" },
    { id: "roadmap", label: "矩阵与路线图", planned: true }, { id: "feedback", label: "反馈", planned: true },
  ],
  projects: [
    { id: "overview", label: "现在" }, { id: "plan", label: "工作与计划", panel: "plan" },
    { id: "builds", label: "试制" }, { id: "verification", label: "测试与交接" },
    { id: "issues", label: "问题与变更", panel: "quality" },
    { id: "reviews", label: "评审与交付", planned: true }, { id: "files", label: "资料", panel: "originals" },
  ],
  resources: [{ id: "overview", label: "组合与资源", planned: true }],
  knowledge: [{ id: "sources", label: "来源与事实", panel: "sources" }, { id: "files", label: "原件", panel: "originals" }],
  settings: [{ id: "preferences", label: "外观" }, { id: "models", label: "AI 运行与费用", panel: "accounting" }, { id: "originals", label: "原件保留与隔离", panel: "lifecycle" }],
};

export const workspaceTasks: Record<string, WorkspaceEntry[]> = {
  "products/research": [
    { id: "sources", label: "资料与事实", panel: "sources" }, { id: "files", label: "原件", panel: "originals" },
    { id: "competitors", label: "竞品对比", planned: true },
  ],
  "projects/builds": [
    { id: "prepare", label: "配置与准备", panel: "build" }, { id: "supply", label: "物料齐套", panel: "supply" },
    { id: "cost", label: "成本", panel: "cost" }, { id: "start", label: "开工条件", panel: "start" },
    { id: "execution", label: "实际产出", panel: "execution" },
  ],
  "projects/verification": [
    { id: "prepare", label: "验证准备", panel: "verification" }, { id: "request", label: "请求与方法", panel: "professional" },
    { id: "handoff", label: "交样与接收", panel: "handoff" }, { id: "launch", label: "承诺与开测", panel: "launch" },
    { id: "results", label: "结果与处置", panel: "results" },
  ],
};

export const defaultWorkspaceLocation: WorkspaceLocation = { area: "work", section: "overview", task: "", productId: "" };

/** Only known destinations become navigation. Object access remains a server decision. */
export function resolveWorkspaceLocation(search: string): WorkspaceLocation {
  const params = new URLSearchParams(search);
  const area = workspaceAreas.find(entry => entry.id === params.get("area"))?.id ?? "work";
  const section = workspaceSections[area].find(entry => entry.id === params.get("view"))?.id ?? workspaceSections[area][0].id;
  const tasks = workspaceTasks[`${area}/${section}`];
  const task = tasks?.find(entry => entry.id === params.get("task"))?.id ?? tasks?.[0].id ?? "";
  return { area, section, task, productId: params.get("product") ?? "" };
}

export function workspaceHref(location: WorkspaceLocation, search = ""): string {
  const params = new URLSearchParams(search);
  params.set("area", location.area); params.set("view", location.section);
  if (location.task) params.set("task", location.task); else params.delete("task");
  if (location.productId) params.set("product", location.productId); else params.delete("product");
  return `?${params.toString()}`;
}

export function workspaceEntry(location: WorkspaceLocation): WorkspaceEntry {
  const tasks = workspaceTasks[`${location.area}/${location.section}`];
  return tasks?.find(entry => entry.id === location.task) ?? workspaceSections[location.area].find(entry => entry.id === location.section) ?? workspaceSections[location.area][0];
}
