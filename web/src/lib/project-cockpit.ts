/**
 * Single-project overview and manager cockpit (D37 ⑦, D76, P34-6, P75-3).
 * Both are server read models; the browser only checks shape, filters and groups.
 * Health, slip and exit conditions are never recomputed here.
 */
export type CockpitApi = <T>(path: string, body?: unknown) => Promise<T>;
export type Person = { id: string; name: string | null };
export type Rule = { id: string; version: number; text: string };
export type Health = { state: string; label: string; reason: string; rule?: { id: string; version: number } };
export type Unavailable = { available: false; reason: string };
export type ExitCondition = { key: string; label: string; state: string; state_label: string };
export type Slip = { state: "late" | "on_track" | "unknown" | "done"; reason: string; against?: string[] };

export type OverviewAction = {
  kind: "blocked" | "receive" | "decide"; kind_label: string; type: string; title: string; reason: string;
  responsible: Person | null; due_at: string | null; target: { view: string; panel: string | null };
  source: { type: string; id: string | null; revision: number | null };
};
export type ProjectOverview = {
  version: "project-overview/v1"; as_of: string; rules: Rule[];
  project: { id: string; revision: number; name: string; status: string; visibility: string; owner: Person; product: { id: string; name: string } };
  stage: { available: boolean; reason: string | null; template?: { id: string; name: string } | null; stages: { key?: string; name: string; status: "passed" | "current" | "upcoming" }[]; current?: { key: string; name: string } | null; completed?: boolean };
  health: (Health & { basis: { gate_state: string; conditions: { key: string; label: string; state: string }[]; overdue_commitments: string[]; review_pending: boolean; stage_adopted: boolean } }) | Unavailable;
  next_node: { name: string | null; times: { task_key: string | null; baseline: string | null; forecast: { earliest: string | null; latest: string | null } | null; commitments: { id: string; promised_at: string | null; fulfilled: boolean; promisor: Person | null; recipient: Person | null }[]; actual: string | null }; slip: Slip; exit_conditions: ExitCondition[]; exit_outcomes: { available: false; label: string; reason: string } } | Unavailable;
  actions: { available: boolean; items: OverviewAction[]; partial_reasons: string[] };
  next_build: { available: true; build: { id: string; name: string; type: string; purpose: string; planned_quantity: string; unit: string; planned_start: string | null; planned_end: string | null; verification_objectives: string; source_status: string; engineering_configuration: { name: string; revision: number }; manufacturing_configuration: { name: string; revision: number } } | null; not_started: number; unavailable_count: number } | Unavailable;
  key_commitments: { id: string; title: string; promisor: Person | null; recipient: Person | null; promised_at: string | null; for_gate: boolean; overdue: boolean }[];
  risks: {
    risks: { id: string; title: string; responsible: Person | null; due_date: string | null; state: string }[];
    issues: { id: string; title: string; status: string; risk: string | null; risk_label: string; owner: Person | null }[] | Unavailable;
    overdue_waits: { id: string; title: string; target: string; responsible: Person | null; escalation: string; reason: string | null; blocking: boolean }[];
    due_soon: { kind: "commitment" | "g0_task"; id: string; title: string; responsible: Person | null; due_at: string }[];
    window_days: number;
  };
  team: { available: true; members: { principal_id: string; name: string; is_owner: boolean; roles: string[]; lead_roles: string[]; open_tasks: number }[]; vacant_roles: string[]; roles_without_lead: string[]; load_note: string } | Unavailable;
  status_update: { latest: { id: string; actor: Person | null; fact_summary: string; next_steps: string; created_at: string; receipt_id: string } | null; cycle: Unavailable };
  agent_duty: { available: true; window_days: number; items: { operation: string; label: string; count: number; runs: number }[]; total: number; revocable: boolean; revocation_note: string; counts_as_todo: false } | Unavailable;
};

export type CockpitRow = {
  project: { id: string; name: string; status: string; visibility: string; owner: Person; category: { id: string; name: string }; product: { id: string; name: string }; set: { id: string; name: string | null } | null };
  stage: { adopted: boolean; stages: { name: string; status: "passed" | "current" | "upcoming" }[]; current: string | null; completed: boolean };
  health: Health;
  next_node: { name: string | null; times: { baseline: string | null; forecast: string | null; commitments: { promised_at: string | null; fulfilled: boolean }[]; actual: string | null }; slip: Slip };
  exit_conditions: ExitCondition[];
  exit_outcomes: { available: false; label: string };
  latest_update: { first_sentence: string | null; actor: Person; created_at: string } | null;
  risk_count: number; review_pending: boolean; my_decision: boolean;
};
export type ProjectCockpit = {
  version: "project-cockpit/v1"; as_of: string; rules: Rule[];
  summary: { active: number; health: { state: string; label: string; count: number }[]; slipped_nodes: number; my_stage_decisions: number; resource_conflicts: Unavailable; status_updates_missing: Unavailable; agent_exceptions: Unavailable };
  items: CockpitRow[]; unavailable_count: number;
};

const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const healthShape = (value: unknown): value is Health => record(value) && typeof value.state === "string" && typeof value.label === "string" && typeof value.reason === "string";
function invalid(what: string): never { throw new Error(`${what}无法核对，请刷新后重试。`); }

export function parseOverview(value: unknown, projectId: string): ProjectOverview {
  if (!record(value) || value.version !== "project-overview/v1" || !Array.isArray(value.rules)) invalid("项目概览");
  if (!record(value.project) || value.project.id !== projectId) invalid("项目概览的项目范围");
  if (!record(value.actions) || !Array.isArray(value.actions.items) || !record(value.risks) || !record(value.status_update)) invalid("项目概览");
  for (const item of value.actions.items) {
    if (!record(item) || !["blocked", "receive", "decide"].includes(String(item.kind)) || typeof item.title !== "string" || !record(item.target)) invalid("需要办理事项");
  }
  return value as unknown as ProjectOverview;
}

export function parseCockpit(value: unknown): ProjectCockpit {
  if (!record(value) || value.version !== "project-cockpit/v1" || !Array.isArray(value.items) || !record(value.summary)) invalid("项目驾驶舱");
  const seen = new Set<string>();
  for (const row of value.items) {
    if (!record(row) || !record(row.project) || !uuid(row.project.id) || seen.has(row.project.id) || !healthShape(row.health) || !Array.isArray(row.exit_conditions)) invalid("驾驶舱项目行");
    seen.add(row.project.id);
  }
  return value as unknown as ProjectCockpit;
}

export async function readProjectOverview(api: CockpitApi, scope: { categoryId: string; productId: string; projectId: string }): Promise<ProjectOverview> {
  if (![scope.categoryId, scope.productId, scope.projectId].every(uuid)) invalid("项目范围");
  return parseOverview(await api<unknown>(`v1/categories/${scope.categoryId}/products/${scope.productId}/projects/${scope.projectId}/overview`), scope.projectId);
}

export async function readProjectCockpit(api: CockpitApi): Promise<ProjectCockpit> {
  return parseCockpit(await api<unknown>("v1/personal/project-cockpit"));
}

export function available<T extends object>(value: T | Unavailable): value is T {
  return !("available" in value && value.available === false);
}

/** Filters a reader can save: project set, category, owner, plus one summary focus. */
export type CockpitFocus = "" | `health:${string}` | "slipped" | "my_decisions";
export type CockpitView = { set: string; category: string; owner: string; focus: CockpitFocus };
export const emptyView: CockpitView = { set: "", category: "", owner: "", focus: "" };
export const UNSET = "__none__";

export function filterRows(rows: CockpitRow[], view: CockpitView): CockpitRow[] {
  return rows.filter(row =>
    (!view.set || (view.set === UNSET ? row.project.set === null : row.project.set?.id === view.set))
    && (!view.category || row.project.category.id === view.category)
    && (!view.owner || row.project.owner.id === view.owner)
    && (!view.focus
      || (view.focus === "slipped" && row.next_node.slip.state === "late")
      || (view.focus === "my_decisions" && row.my_decision)
      || (view.focus.startsWith("health:") && row.health.state === view.focus.slice(7))));
}

/** Rows grouped by health tier in the server's fixed tier order (same as the list). */
export function groupRows(rows: CockpitRow[], tiers: { state: string; label: string }[]): { state: string; label: string; rows: CockpitRow[] }[] {
  return tiers.map(tier => ({ ...tier, rows: rows.filter(row => row.health.state === tier.state) })).filter(group => group.rows.length);
}

export function filterOptions(rows: CockpitRow[]) {
  const unique = <T extends { id: string }>(items: T[]) => [...new Map(items.map(item => [item.id, item])).values()];
  return {
    sets: unique(rows.flatMap(row => row.project.set ? [{ id: row.project.set.id, name: row.project.set.name ?? "未命名项目集" }] : [])),
    categories: unique(rows.map(row => row.project.category)),
    owners: unique(rows.map(row => ({ id: row.project.owner.id, name: row.project.owner.name ?? "姓名暂不可读" }))),
  };
}

export type SavedView = { name: string; view: CockpitView };
export function savedViewsKey(principalId: string): string { return `pdos:project-cockpit:${principalId}:views:v1`; }
/** Saved views live only in this browser (per-viewer convenience); bad data reads as none. */
export function readSavedViews(storage: Pick<Storage, "getItem"> | null, principalId: string): SavedView[] {
  try {
    const value: unknown = JSON.parse(storage?.getItem(savedViewsKey(principalId)) ?? "[]");
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is SavedView => record(item) && typeof item.name === "string" && !!item.name.trim() && record(item.view)
      && ["set", "category", "owner", "focus"].every(key => typeof (item.view as Record<string, unknown>)[key] === "string")).slice(0, 20);
  } catch { return []; }
}
export function writeSavedViews(storage: Pick<Storage, "setItem"> | null, principalId: string, views: SavedView[]): boolean {
  try { storage?.setItem(savedViewsKey(principalId), JSON.stringify(views.slice(0, 20))); return !!storage; } catch { return false; }
}
export function saveView(views: SavedView[], name: string, view: CockpitView): SavedView[] {
  const label = name.trim().slice(0, 40);
  if (!label) return views;
  return [...views.filter(item => item.name !== label), { name: label, view }];
}

export function dateText(value: string | null | undefined): string {
  if (!value) return "未知";
  const date = new Date(value.length === 10 ? `${value}T00:00:00Z` : value);
  if (!Number.isFinite(date.getTime())) return "未知";
  return `${String(date.getUTCMonth() + 1).padStart(2, "0")}月${String(date.getUTCDate()).padStart(2, "0")}日`;
}

export function slipText(slip: Slip): string {
  return slip.state === "late" ? `已滑期 · ${slip.reason}` : slip.state === "on_track" ? "未滑期" : slip.state === "done" ? "节点已决定" : `滑期未知 · ${slip.reason}`;
}

export function healthTone(state: string): "danger" | "warning" | "success" | "neutral" {
  return state === "blocked" ? "danger" : state === "normal" ? "success" : state === "unknown" ? "neutral" : "warning";
}

/** Where a 需要办理 item is handled; never executes a command from the overview. */
export function actionTarget(item: OverviewAction): { view: string; panel: string | null } {
  return { view: ["tasks", "plan", "gates", "builds", "team"].includes(item.target.view) ? item.target.view : "tasks", panel: item.target.panel };
}
