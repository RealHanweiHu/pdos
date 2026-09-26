"use client";

export const professionalRoles: Record<string, string> = { product_management: "产品/项目", industrial_design: "ID", mechanical: "结构", hardware: "硬件", firmware: "固件", design_quality: "DQE", supplier_quality: "SQE", industrial_engineering: "IE" };
export type TaskRoute = { owner: string | null; receiver: string | null };
export type TaskRoutes = Record<string, TaskRoute>;
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

export function TaskRouteEditor({ code, routes, onChange }: { code: string; routes: TaskRoutes; onChange: (value: TaskRoutes) => void }) {
  const route = routes[code] ?? { owner: null, receiver: null };
  const change = (slot: "owner" | "receiver", value: string) => {
    const next = { ...route, [slot]: value || null };
    const result = { ...routes };
    if (next.owner || next.receiver) result[code] = next; else delete result[code];
    onChange(result);
  };
  return <div className="space-y-2 rounded-md border p-3"><p className="text-sm font-medium">任务办理路由</p><p className="text-xs text-muted-foreground">编制计划时为以下专业职责指定具名联系人，同一职责的任务统一分派；联系人仍须确认，正式任务和交接另行应用。此处不授予账号权限。</p><div className="grid gap-3 sm:grid-cols-2">{([['owner','负责人交给'],['receiver','接收人交给']] as const).map(([slot,label]) => <label key={slot} className="text-sm">{label}<select className={field} value={route[slot] ?? ""} onChange={event => change(slot, event.target.value)}><option value="">编制计划时逐项指定</option>{Object.entries(professionalRoles).map(([key,label]) => <option key={key} value={key}>{label}联系人</option>)}</select></label>)}</div></div>;
}
