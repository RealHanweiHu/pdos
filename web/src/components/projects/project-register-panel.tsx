"use client";

import { type FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import {
  createCost,
  createResource,
  type CostCreateInput,
  type CostStatus,
  type CostType,
  type ProjectCost,
  type ProjectResource,
  requestCosts,
  requestResources,
  type ResourceCreateInput,
  type ResourceStatus,
  type ResourceType,
  transitionCost,
  transitionResource,
} from "./project-register-api";
import { memberLabel } from "./project-task-planning";
import type { ProjectMember } from "./project-work-item-types";

const controlClass =
  "mt-1 min-h-11 w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 disabled:opacity-60";

const costTypeLabels: Record<CostType, string> = {
  material: "物料",
  labor: "人工",
  tooling: "模具/工装",
  logistics: "物流",
  other: "其他",
};
const costStatusLabels: Record<CostStatus, string> = { estimate: "预估", approved: "已批准", actual: "实际" };
const resourceTypeLabels: Record<ResourceType, string> = {
  person: "人员",
  equipment: "设备",
  facility: "场地",
  capability: "能力",
};
const resourceStatusLabels: Record<ResourceStatus, string> = { planned: "计划中", active: "在岗", released: "已释放" };

type LoadState = "loading" | "ready" | "error" | "restricted";

function money(cents: number, currency: string) {
  try {
    return new Intl.NumberFormat("zh-CN", { style: "currency", currency }).format(cents / 100);
  } catch {
    return `${currency} ${(cents / 100).toFixed(2)}`;
  }
}

const toCents = (amount: string) => Math.round(Number(amount) * 100);

/** Per-currency totals for each cost status, in cents to avoid float drift. */
export function costTotals(costs: ProjectCost[]) {
  const totals = new Map<string, Record<CostStatus, number>>();
  for (const cost of costs) {
    const row = totals.get(cost.currency) ?? { estimate: 0, approved: 0, actual: 0 };
    row[cost.status] += toCents(cost.amount);
    totals.set(cost.currency, row);
  }
  return totals;
}

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "ok" | "pending" | "bad" }) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium",
        tone === "neutral" && "bg-muted text-muted-foreground",
        tone === "ok" && "border-success/25 bg-success/10 text-success",
        tone === "pending" && "border-pending/25 bg-pending/10 text-pending",
        tone === "bad" && "border-destructive/25 bg-destructive/10 text-destructive",
      )}
    >
      {children}
    </span>
  );
}

export function ProjectRegisterPanel({
  canEdit,
  currentUserId,
  members,
  projectId,
}: {
  canEdit: boolean;
  currentUserId: string;
  members: ProjectMember[];
  projectId: string;
}) {
  const [resources, setResources] = useState<ProjectResource[]>([]);
  const [resourceState, setResourceState] = useState<LoadState>("loading");
  const [costs, setCosts] = useState<ProjectCost[]>([]);
  const [costState, setCostState] = useState<LoadState>(canEdit ? "loading" : "restricted");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    requestResources(projectId).then(
      (loaded) => { if (active) { setResources(loaded); setResourceState("ready"); } },
      () => { if (active) setResourceState("error"); },
    );
    if (canEdit) {
      requestCosts(projectId).then(
        (loaded) => { if (active) { setCosts(loaded); setCostState("ready"); } },
        () => { if (active) setCostState("error"); },
      );
    }
    return () => { active = false; };
  }, [canEdit, projectId, reloadKey]);

  async function run<T>(operation: () => Promise<T>, apply: (value: T) => void, success: string) {
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      apply(await operation());
      setStatus(success);
      return true;
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "操作失败，请稍后重试。");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function addResource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const text = (name: string) => String(data.get(name) ?? "").trim();
    if (text("start_date") && text("end_date") && text("end_date") < text("start_date")) {
      setError("结束日期不能早于开始日期。");
      return;
    }
    const input: ResourceCreateInput = {
      name: text("name"),
      resource_type: text("resource_type") as ResourceType,
      allocation_percent: text("allocation_percent") || "100",
    };
    if (text("assigned_user_id")) input.assigned_user_id = text("assigned_user_id");
    if (text("start_date")) input.start_date = text("start_date");
    if (text("end_date")) input.end_date = text("end_date");
    const created = await run(
      () => createResource(projectId, input),
      (resource) => setResources((current) => [resource, ...current]),
      "资源已添加",
    );
    if (created) form.reset();
  }

  async function addCost(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const text = (name: string) => String(data.get(name) ?? "").trim();
    const input: CostCreateInput = { cost_type: text("cost_type") as CostType, amount: text("amount") };
    if (text("incurred_on")) input.incurred_on = text("incurred_on");
    if (text("description")) input.description = text("description");
    const created = await run(
      () => createCost(projectId, input),
      (cost) => setCosts((current) => [cost, ...current]),
      "成本已登记",
    );
    if (created) form.reset();
  }

  function moveResource(resource: ProjectResource, toStatus: "active" | "released") {
    void run(
      () => transitionResource(projectId, resource.id, toStatus),
      () => setReloadKey((key) => key + 1),
      toStatus === "active" ? "资源已启用" : "资源已释放",
    );
  }

  function moveCost(cost: ProjectCost, toStatus: "approved" | "actual") {
    void run(
      () => transitionCost(projectId, cost.id, toStatus),
      (updated) => setCosts((current) => current.map((item) => (item.id === updated.id ? updated : item))),
      toStatus === "approved" ? "成本已批准" : "成本已记为实际",
    );
  }

  const assignable = members.filter((member) => member.assignable && member.is_active);
  const totals = costTotals(costs);

  return (
    <div className="space-y-4">
      {error ? <p className="rounded-lg border border-destructive/30 bg-destructive/8 px-3 py-2 text-sm text-destructive" role="alert">{error}</p> : null}
      {status ? <p className="rounded-lg border bg-muted/40 px-3 py-2 text-sm text-muted-foreground" role="status">{status}</p> : null}

      <section aria-label="资源分配" className="overflow-hidden rounded-lg border bg-card">
        <div className="flex flex-wrap items-end justify-between gap-2 border-b px-4 py-3">
          <div>
            <h3 className="font-semibold">资源分配</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">总负荷按该人员在所有项目中“在岗”的投入比例合计。</p>
          </div>
          <span className="font-mono text-xs text-muted-foreground">{resources.length} 条</span>
        </div>
        {canEdit ? (
          <form className="grid gap-3 border-b bg-muted/25 p-4 sm:grid-cols-2 lg:grid-cols-3 lg:items-end" onSubmit={addResource}>
            <label className="text-xs font-medium sm:col-span-2 lg:col-span-1" htmlFor="resource-name">资源名称<input className={controlClass} disabled={busy} id="resource-name" maxLength={256} name="name" required /></label>
            <label className="text-xs font-medium" htmlFor="resource-type">
              类型
              <select className={controlClass} defaultValue="person" disabled={busy} id="resource-type" name="resource_type">
                {Object.entries(resourceTypeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label className="text-xs font-medium" htmlFor="resource-assignee">
              对应成员
              <select className={controlClass} defaultValue="" disabled={busy} id="resource-assignee" name="assigned_user_id">
                <option value="">不关联成员</option>
                {assignable.map((member) => <option key={member.user_id} value={member.user_id}>{memberLabel(members, member.user_id, currentUserId)}</option>)}
              </select>
            </label>
            <label className="text-xs font-medium" htmlFor="resource-allocation">投入比例 %<input className={controlClass} defaultValue="100" disabled={busy} id="resource-allocation" max={100} min={1} name="allocation_percent" required step="1" type="number" /></label>
            <label className="text-xs font-medium" htmlFor="resource-start">开始日期<input className={controlClass} disabled={busy} id="resource-start" name="start_date" type="date" /></label>
            <label className="text-xs font-medium" htmlFor="resource-end">结束日期<input className={controlClass} disabled={busy} id="resource-end" name="end_date" type="date" /></label>
            <Button className="h-11 sm:col-span-2 lg:col-span-1" disabled={busy} type="submit">添加资源</Button>
          </form>
        ) : null}
        {resourceState === "loading" ? <p className="px-4 py-8 text-center text-sm text-muted-foreground">正在读取资源…</p> : null}
        {resourceState === "error" ? (
          <div className="px-4 py-8 text-center">
            <p className="text-sm text-destructive">资源数据暂不可用。</p>
            <Button className="mt-3 h-11 sm:h-8" onClick={() => { setResourceState("loading"); setReloadKey((key) => key + 1); }} variant="outline">重新读取</Button>
          </div>
        ) : null}
        {resourceState === "ready" && resources.length === 0 ? <p className="px-4 py-8 text-center text-sm text-muted-foreground">还没有资源分配。</p> : null}
        {resourceState === "ready" && resources.length > 0 ? (
          <ul className="divide-y" role="list">
            {resources.map((resource) => {
              const load = resource.assignee_active_allocation_percent === null ? null : Number(resource.assignee_active_allocation_percent);
              return (
                <li className="p-4" data-testid="resource-row" key={resource.id}>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="min-w-0 flex-1 font-medium">{resource.name} <span className="font-mono text-[11px] text-muted-foreground">{resource.code}</span></p>
                    <Badge tone={resource.status === "active" ? "ok" : "neutral"}>{resourceStatusLabels[resource.status]}</Badge>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span>{resourceTypeLabels[resource.resource_type]}</span>
                    {resource.assigned_user_id ? <span>成员：{memberLabel(members, resource.assigned_user_id, currentUserId)}</span> : null}
                    <span>本项目投入 {Number(resource.allocation_percent)}%</span>
                    <span className="font-mono">{resource.start_date ?? "—"} → {resource.end_date ?? "—"}</span>
                    {load !== null ? (
                      <span className={cn(load > 100 && "font-medium text-destructive")}>
                        总负荷 {load}%{load > 100 ? "（超负荷）" : ""}
                      </span>
                    ) : null}
                  </div>
                  {canEdit && resource.status !== "released" ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {resource.status === "planned" ? <Button className="h-11 sm:h-8" disabled={busy} onClick={() => moveResource(resource, "active")}>启用</Button> : null}
                      <Button className="h-11 sm:h-8" disabled={busy} onClick={() => moveResource(resource, "released")} variant="outline">释放</Button>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : null}
      </section>

      <section aria-label="成本登记" className="overflow-hidden rounded-lg border bg-card">
        <div className="flex flex-wrap items-end justify-between gap-2 border-b px-4 py-3">
          <div>
            <h3 className="font-semibold">成本登记</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">预估 → 已批准 → 实际；批准后金额锁定。ERP 仍是实际成本的权威来源。</p>
          </div>
          {costState === "ready" ? <span className="font-mono text-xs text-muted-foreground">{costs.length} 条</span> : null}
        </div>
        {costState === "restricted" ? <p className="px-4 py-8 text-center text-sm text-muted-foreground">成本数据仅项目经理及以上角色可见。</p> : null}
        {costState === "loading" ? <p className="px-4 py-8 text-center text-sm text-muted-foreground">正在读取成本…</p> : null}
        {costState === "error" ? <p className="px-4 py-8 text-center text-sm text-destructive">成本数据暂不可用。</p> : null}
        {costState === "ready" ? (
          <>
            {totals.size > 0 ? (
              <div className="divide-y border-b">
                {[...totals.entries()].map(([currency, row]) => (
                  <dl className="grid grid-cols-3 divide-x py-3 text-center" data-testid={`cost-totals-${currency}`} key={currency}>
                    {(["estimate", "approved", "actual"] as const).map((key) => (
                      <div className="min-w-0 px-2" key={key}>
                        <dt className="text-[11px] text-muted-foreground">{costStatusLabels[key]}</dt>
                        <dd className="mt-1 truncate font-mono text-sm font-semibold">{money(row[key], currency)}</dd>
                      </div>
                    ))}
                  </dl>
                ))}
              </div>
            ) : null}
            <form className="grid gap-3 border-b bg-muted/25 p-4 sm:grid-cols-2 lg:grid-cols-4 lg:items-end" onSubmit={addCost}>
              <label className="text-xs font-medium" htmlFor="cost-type">
                成本类型
                <select className={controlClass} defaultValue="material" disabled={busy} id="cost-type" name="cost_type">
                  {Object.entries(costTypeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              <label className="text-xs font-medium" htmlFor="cost-amount">金额（CNY）<input className={controlClass} disabled={busy} id="cost-amount" inputMode="decimal" min="0" name="amount" required step="0.01" type="number" /></label>
              <label className="text-xs font-medium" htmlFor="cost-date">发生日期<input className={controlClass} disabled={busy} id="cost-date" name="incurred_on" type="date" /></label>
              <label className="text-xs font-medium" htmlFor="cost-description">说明<input className={controlClass} disabled={busy} id="cost-description" maxLength={2_000} name="description" /></label>
              <Button className="h-11 sm:col-span-2 lg:col-span-4 lg:justify-self-end" disabled={busy} type="submit">登记成本</Button>
            </form>
            {costs.length === 0 ? <p className="px-4 py-8 text-center text-sm text-muted-foreground">还没有成本记录。</p> : (
              <ul className="divide-y" role="list">
                {costs.map((cost) => (
                  <li className="p-4" data-testid="cost-row" key={cost.id}>
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="min-w-0 flex-1 font-medium">
                        {costTypeLabels[cost.cost_type]} <span className="font-mono text-[11px] text-muted-foreground">{cost.code}</span>
                      </p>
                      <span className="font-mono text-sm font-semibold">{money(toCents(cost.amount), cost.currency)}</span>
                      <Badge tone={cost.status === "actual" ? "ok" : cost.status === "approved" ? "pending" : "neutral"}>{costStatusLabels[cost.status]}</Badge>
                    </div>
                    {cost.description || cost.incurred_on ? (
                      <p className="mt-1 text-xs text-muted-foreground">{[cost.incurred_on, cost.description].filter(Boolean).join(" · ")}</p>
                    ) : null}
                    {cost.status !== "actual" ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {cost.status === "estimate" ? <Button className="h-11 sm:h-8" disabled={busy} onClick={() => moveCost(cost, "approved")}>批准</Button> : null}
                        {cost.status === "approved" ? <Button className="h-11 sm:h-8" disabled={busy} onClick={() => moveCost(cost, "actual")}>记为实际</Button> : null}
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </>
        ) : null}
      </section>
    </div>
  );
}
