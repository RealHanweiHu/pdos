/**
 * ⌘K 命令与快速创建（B19，v1.1 §05.12.5）。
 *
 * 只列出已登记、已实现的领域命令在页面上的现有入口；可见性只取服务器下发的权限投影，
 * 拿不到就不显示。选中命令只是打开原页面的新建表单，确认、具名办理与权限核对仍由原表单和服务器完成。
 * 具名决定（T2）不进入本面板；编号检索只做定位。
 */

/** 本面板接入的命令及其登记档位；单元测试逐条对照 contracts/operations.json。 */
export const paletteOperations = {
  "category.create": "T1",
  "proposal.create": "T1",
  "work.task.create": "T0",
  "work.status_update.create": "T1",
} as const;
export type PaletteOperation = keyof typeof paletteOperations;

/** 目标页面据此打开原有的新建表单；读到后立即从地址中移除。 */
export const createIntents = { category: "category.create", proposal: "proposal.create", task: "work.task.create", status_update: "work.status_update.create" } as const satisfies Record<string, PaletteOperation>;
export type CreateIntent = keyof typeof createIntents;
export const createIntentParam = "create";

export type PaletteSignals = {
  /** v1/categories 中 capabilities.product_management === true 的品类。 */
  productManagement: { id: string; name: string }[];
  /** 当前所在项目；canWrite 只取服务器读回的本人成员 can_write。 */
  project: { categoryId: string; projectId: string; name: string; canWrite: boolean } | null;
};
export const noSignals: PaletteSignals = { productManagement: [], project: null };

export type PaletteGroup = "create" | "navigate";
export type PaletteCommand = {
  id: string;
  group: PaletteGroup;
  label: string;
  /** 用户可读的办理方式；不出现档位枚举（B18）。 */
  hint: string;
  keywords: string;
  href: string;
  operation?: PaletteOperation;
};

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const confirmHint = "打开新建表单，本人确认后才保存";

function href(values: Record<string, string>) { return `?${new URLSearchParams(values)}`; }

/** 与侧栏同源：全局入口对所有人可见，产品管理入口只给持有当前产品管理授权的人。 */
function navigation(signals: PaletteSignals): PaletteCommand[] {
  const go = (id: string, label: string, keywords: string, values: Record<string, string>): PaletteCommand => ({ id: `go:${id}`, group: "navigate", label, hint: "跳转", keywords, href: href(values) });
  const items = [
    go("work", "我的工作", "待办 承诺 已完成 work", { area: "work" }),
    go("inbox", "收件箱", "通知 聊天 消息 inbox", { area: "inbox" }),
    go("pai", "小Pai", "对话 会话 助手 ai pai", { area: "pai" }),
    go("projects", "项目", "项目列表 看板 时间轴 projects", { area: "projects" }),
    go("programs", "项目集", "项目集 programs", { area: "programs" }),
    go("knowledge", "知识", "资料 知识 knowledge", { area: "knowledge" }),
  ];
  const managed = signals.productManagement;
  if (managed.length) {
    items.push(go("category", "品类", "产品管理 品类 category", { area: "category" }));
    items.push(go("proposals", "立项提案", "产品管理 提案 立项 proposal", { area: "category", category: managed[0].id, focus: "proposals" }));
  }
  items.push(go("settings", "设置", "偏好 主题 设置 settings", { area: "settings" }));
  return items;
}

/** 快速创建按服务器权限收窄：无权限的命令不生成，而不是生成后报错。 */
function quickCreate(signals: PaletteSignals): PaletteCommand[] {
  const items: PaletteCommand[] = [];
  const project = signals.project;
  if (project?.canWrite && uuid.test(project.categoryId) && uuid.test(project.projectId)) {
    const scope = { area: "cockpit", category: project.categoryId, project: project.projectId };
    items.push({ id: `create:task:${project.projectId}`, group: "create", operation: "work.task.create", label: `新建任务 · ${project.name}`, hint: "打开新建任务表单，填写后由你保存", keywords: "新建 创建 任务 task", href: href({ ...scope, projectView: "tasks", [createIntentParam]: "task" }) });
    items.push({ id: `create:status:${project.projectId}`, group: "create", operation: "work.status_update.create", label: `写状态更新 · ${project.name}`, hint: "打开具名周报，本人确认后才发布", keywords: "状态更新 周报 动态 status update", href: href({ ...scope, projectView: "now", [createIntentParam]: "status_update" }) });
  }
  const managed = signals.productManagement.filter(item => uuid.test(item.id));
  for (const category of managed) items.push({ id: `create:proposal:${category.id}`, group: "create", operation: "proposal.create", label: `新建立项提案 · ${category.name}`, hint: confirmHint, keywords: `新建 创建 立项 提案 proposal ${category.name}`, href: href({ area: "category", category: category.id, focus: "proposals", [createIntentParam]: "proposal" }) });
  // 页面入口在产品管理的品类列表里，可见条件与之相同；能否创建仍由服务器在本人确认时判定。
  if (managed.length) items.push({ id: "create:category", group: "create", operation: "category.create", label: "新建品类", hint: confirmHint, keywords: "新建 创建 品类 category", href: href({ area: "category", [createIntentParam]: "category" }) });
  return items;
}

export function paletteCommands(signals: PaletteSignals): PaletteCommand[] {
  return [...quickCreate(signals), ...navigation(signals)];
}

/** 输入完整编号时只做定位，不附带任何命令；其余按全部关键词匹配。 */
export function filterCommands(commands: PaletteCommand[], query: string): PaletteCommand[] {
  const q = query.trim().toLocaleLowerCase();
  if (!q) return commands;
  if (uuid.test(q)) return [];
  const terms = q.split(/\s+/);
  return commands.filter(command => {
    const text = `${command.label} ${command.keywords}`.toLocaleLowerCase();
    return terms.every(term => text.includes(term));
  });
}

/** 命令目标只能是本应用的相对查询地址。 */
export function commandHref(command: PaletteCommand): string | null {
  return command.href.startsWith("?") && !command.href.includes("//") ? command.href : null;
}

/** 读出并移除一次性的新建意图；目标页面在可以打开原表单时调用。 */
export function takeCreateIntent(search: string, intent: CreateIntent): { matched: boolean; search: string } {
  const params = new URLSearchParams(search);
  if (params.get(createIntentParam) !== intent) return { matched: false, search };
  params.delete(createIntentParam);
  const rest = params.toString();
  return { matched: true, search: rest ? `?${rest}` : "" };
}

type RawCategory = { id?: unknown; name?: unknown; capabilities?: { product_management?: unknown } };

/** 只认服务器明确给出的 true；字段缺失或类型不对一律不授予。 */
export function managedCategories(raw: unknown): PaletteSignals["productManagement"] {
  if (!Array.isArray(raw)) return [];
  return (raw as RawCategory[])
    .filter(item => item && typeof item.id === "string" && uuid.test(item.id) && typeof item.name === "string" && item.capabilities?.product_management === true)
    .map(item => ({ id: item.id as string, name: (item.name as string).trim() || "未命名品类" }));
}

/** 本人在项目中的写入资格只取服务器成员列表，找不到本人即视为不可写。 */
export function memberCanWrite(members: unknown, principalId: string): boolean {
  if (!Array.isArray(members) || !uuid.test(principalId)) return false;
  const self = members.find(row => row && typeof row === "object" && (row as { id?: unknown }).id === principalId) as { can_write?: unknown } | undefined;
  return self?.can_write === true;
}
