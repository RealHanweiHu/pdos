/** Presentation destinations only. Every embedded command retains its server scope. */
export const projectViews = [
  { id: "now", label: "概览" }, { id: "tasks", label: "任务" },
  { id: "plan", label: "计划" }, { id: "docs", label: "文件" },
  { id: "prep", label: "产品与工程" }, { id: "builds", label: "试制与验证" },
  { id: "issues", label: "问题与变更" }, { id: "review", label: "评审与交付" },
  { id: "gates", label: "阶段与门禁" }, { id: "feedback", label: "现场反馈" },
] as const;
export type ProjectViewId = typeof projectViews[number]["id"];
export function projectView(value: string | null): ProjectViewId {
  return projectViews.find(item => item.id === value)?.id ?? "tasks";
}
export const professionalViews = {
  docs: { title: "文件", description: "查找项目可用资料，上传原件并核对引用版本。", panels: [["files", "文件"], ["originals", "上传与管理"], ["sources", "原文与事实"], ["lifecycle", "保留与隔离"]] },
  prep: { title: "产品与工程", description: "规格、配置和制品在同一处核对，正式基线独立保留。", panels: [
    ["definition", "产品定义"], ["build", "工程配置与 BOM"], ["variants", "平台与差异"],
    ["manufacturing", "制造准备"], ["publication", "制造发布"], ["supply", "物料齐套"], ["cost", "成本"],
  ] },
  builds: { title: "试制与验证", description: "从试制轮次到实物、交接与验证，逐项记录实际进展。", panels: [
    ["summary", "试制轮次"], ["start", "开工条件"], ["execution", "实际产出"],
    ["verification", "验证准备"], ["professional", "请求与方法"], ["handoff", "交样与接收"],
    ["launch", "承诺与开测"], ["results", "结果与处置"], ["pilots", "试产"],
  ] },
  issues: { title: "问题与变更", description: "从现象和原始依据出发，追踪原因、措施、专业决定与复验。", panels: [
    ["quality", "问题与分诊"], ["followup", "原因与措施"], ["changes", "变更与实施"],
  ] },
  review: { title: "评审与交付", description: "核对固定版本、用途、例外与专业结论，完成具名办理。", panels: [
    ["packages", "发布与交付包"], ["exceptions", "例外与专业决定"], ["external", "外部移交"],
  ] },
  feedback: { title: "现场反馈", description: "保留现场现象和原始依据，跟进分诊与后续改进。", panels: [["field", "反馈与接续"]] },
} as const;
export type ProfessionalView = keyof typeof professionalViews;
export function isProfessionalView(view: ProjectViewId): view is ProfessionalView { return view in professionalViews; }

export function projectWorkspaceHref(categoryId: string, productId: string, projectId: string, view: ProjectViewId, panel?: string) {
  return `/?${new URLSearchParams({ area: "cockpit", category: categoryId, product: productId, project: projectId, projectView: view, ...(panel ? { panel } : {}) })}`;
}
