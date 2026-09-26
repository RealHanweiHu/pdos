"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";

type Demand = { capacity_version_id: string; units: string; contributes_effort: boolean; occupancy_policy: "working_only" | "through_waiting"; basis: string };
type Conflict = { resource_name: string; start: string; end: string; demand_units: string; available_units: string };
type Solution = {
  id: string; result_digest: string; created_at: string; preparation?: { id: string; scenario_id: string; title: string; receipt: { dates_changed: boolean; prepared_as_of: string } } | null; source_digest: string; scenario_basis_digest: string;
  inputs: { demands: Record<string, Demand[]>; no_resource_reasons: Record<string, string>; horizon_days: number };
  result: {
    solution_status: string; project_finish: string | null;
    nodes: { node_key: string; start: string | null; finish: string | null; actual_start: string | null; actual_finish: string | null; remaining_work_start: string | null; unknown_reasons: string[]; warnings: string[] }[];
    resource_solver: {
      as_of: string; horizon_end: string; attempts: number;
      policies: { resource_id: string; policy_id: string; version: number; rank: number; status: string; valid_from: string; valid_until: string }[];
      profiles: { id: string; resource_id: string; resource_name: string; version: number; parallel_units: string; window_start: string; window_end: string; basis: string }[];
      decisions: { node_key: string; delay_minutes?: number; attempts: number; delays: Conflict[]; reasons: string[] }[];
      priority_intervals: { resource_id: string; start: string; end: string; units: string; rank: number }[];
      reserved_intervals: { resource_id: string; start: string; end: string; units: string; origin?: string; covered_node_key?: string }[];
    };
    capacity: { conflicts: Conflict[]; unknown: { node_key: string; reason: string }[]; reservation_differences: { node_key: string; resource_name: string; start: string; end: string; forecast_units: string | null; reserved_units: string; disposition: string; reservation_ids: string[] }[] };
  };
};
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const when = (value: string | null) => value ? new Date(value).toLocaleString() : "待定";

export function ResourceScheduleSolutions({ path, demands, noResourceReasons, nodes, onPrepared }: { onPrepared?: (scenarioId?: string) => Promise<void>; path: string; demands: Record<string, Demand[]>; noResourceReasons: Record<string, string>; nodes: { node_key: string; title?: string }[] }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Solution[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [horizon, setHorizon] = useState("90");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<{ key: string; id: string } | null>(null);
  async function history(cursor?: string) {
    const response = await caseLinkRequest<{ items: Solution[]; next: string | null }>(`${path}${cursor ? `?before=${cursor}` : ""}`);
    setItems(previous => cursor ? [...previous, ...response.items.filter(item => !previous.some(old => old.id === item.id))] : response.items);
    setNext(response.next);
  }
  async function run(solve: boolean, cursor?: string) {
    setBusy(true); setError("");
    try {
      if (solve) {
        const body = { demands, no_resource_reasons: Object.fromEntries(Object.entries(noResourceReasons).filter(([, value]) => value.trim()).map(([key, value]) => [key, value.trim()])), horizon_days: Number(horizon) };
        const key = JSON.stringify(body);
        if (pending.current?.key !== key) pending.current = { key, id: crypto.randomUUID() };
        const saved = await caseLinkRequest<Solution>(path, { ...body, request_id: pending.current.id });
        pending.current = null;
        setItems(previous => [saved, ...previous.filter(item => item.id !== saved.id)]);
      }
      await history(cursor);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "资源日期方案暂不可用"); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded-md border p-3">
    <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => { setOpen(!open); if (!open) void run(false); }}>{open ? "收起资源日期方案" : "计算资源受限候选日期"}</Button>
    {open && <>
      <p className="text-xs text-muted-foreground">采用上方明确选择的资源和投入，按依赖先后、同层节点固定顺序寻找可用日期。已确认占用和旧资源占用保留，同一节点的已有预约合并计算；当前有效政策中优先于本次新申请的待办也计入。结果是待审方案，尚未形成预约、正式计划或交付承诺。</p>
      <p className="text-xs text-muted-foreground">日期从本次计算时点重新推算。搜索只给出当前规则找到的方案，不保证最短工期；未找到日期时显示缺项或搜索边界，资源约束下的浮时和关键路径暂不推定。</p>
      <label className="block text-sm">最多向后搜索天数<input className={field} type="number" min="1" max="366" step="1" value={horizon} disabled={busy} onChange={event => setHorizon(event.target.value)} /></label>
      <Button type="button" size="sm" disabled={busy || !Number.isInteger(Number(horizon)) || Number(horizon) < 1 || Number(horizon) > 366 || Object.values(demands).flat().some(item => !item.capacity_version_id || !item.units || !item.basis.trim())} onClick={() => void run(true)}>{busy ? "处理中…" : "计算并保存候选日期"}</Button>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {items.map(item => {
        const result = item.result; const evidence = result.resource_solver;
        const resourceName = (id: string) => evidence.profiles.find(profile => profile.resource_id === id)?.resource_name ?? "共享资源";
        const title = (key: string) => nodes.find(node => node.node_key === key)?.title ?? key;
        return <details key={item.id} className="space-y-2 rounded-md border p-3">
          <summary className="cursor-pointer text-sm font-medium">{when(item.created_at)} · {result.solution_status === "candidate_found" ? "已找到候选日期" : "仍有约束待处理"}</summary>
          <p className="text-sm">预计项目结束：{when(result.project_finish)}</p>
          <p className="text-xs">计算范围 {when(evidence.as_of)} — {when(evidence.horizon_end)}。这是保存时的来源快照；当前进展、容量、优先级或预约变化后需重算。</p>
          {result.nodes.map(node => {
            const decision = evidence.decisions.find(value => value.node_key === node.node_key);
            return <div key={node.node_key} className="space-y-1 border-l pl-2 text-xs">
              <p className="font-medium">{title(node.node_key)}{node.actual_finish ? " · 已实际完成" : node.actual_start ? " · 已实际开工" : ""}</p>
              <p>{when(node.start)} → {when(node.finish)}{node.actual_start && !node.actual_finish ? `；剩余工作从 ${when(node.remaining_work_start)}` : ""}</p>
              {!!decision?.delay_minutes && <p>因资源约束后移 {decision.delay_minutes} 分钟</p>}
              {node.unknown_reasons.map((reason, index) => <p key={index} className="text-destructive">{reason}</p>)}
              {node.warnings.map((reason, index) => <p key={index}>{reason}</p>)}
              {!!decision?.delays.length && <details><summary className="cursor-pointer">导致调整的窗口（最多显示前 20 处）</summary>{decision.delays.map((conflict, index) => <p key={index}>{conflict.resource_name}：{when(conflict.start)} — {when(conflict.end)}，需求 {conflict.demand_units} / 可用 {conflict.available_units}</p>)}</details>}
            </div>;
          })}
          {result.capacity.unknown.map((value, index) => <p key={index} className="text-xs text-destructive">{value.node_key}：{value.reason}</p>)}
          {result.capacity.conflicts.map((value, index) => <p key={index} className="text-xs text-destructive">{value.resource_name}：{when(value.start)} — {when(value.end)}，需求 {value.demand_units} / 可用 {value.available_units}</p>)}
          {result.solution_status === "candidate_found" && <PrepareResourceDates solution={item} path={path.replace(/scenarios\/[^/]+\/resource-schedules$/, "resource-schedule-preparations")} onPrepared={async (scenarioId) => { await history(); await onPrepared?.(scenarioId); }} />}
          <details><summary className="cursor-pointer text-xs">需另行办理的预约差异（{result.capacity.reservation_differences.length}）</summary>{result.capacity.reservation_differences.map((difference, index) => <p key={index} className="my-2 text-xs">{title(difference.node_key)} · {difference.resource_name} · {when(difference.start)} — {when(difference.end)} · 候选需求 {difference.forecast_units ?? "未知"} / 已预约 {difference.reserved_units}；{difference.disposition === "additional_capacity_needed" ? "仍需预约" : difference.disposition === "requirement_unknown" ? "需求待定，不能推定可释放" : "可另行核对释放"}{difference.reservation_ids.map(id => <a key={id} className="ml-2 text-primary underline" href={`/projects?project=${path.split("/")[1]}&tab=overview&resource_reservation_id=${id}#resource-reservations`}>打开原预约办理</a>)}{difference.reservation_ids.length === 0 && <a className="ml-2 text-primary underline" href={`/projects?project=${path.split("/")[1]}&tab=overview#resource-reservations`}>办理资源预约</a>}</p>)}</details>
          <details><summary className="cursor-pointer text-xs">固定的容量、优先级和占用依据</summary>
            {evidence.profiles.map(profile => <p key={profile.id} className="my-2 text-xs">{profile.resource_name} · 容量 v{profile.version} · {profile.parallel_units} 单位 · {when(profile.window_start)} — {when(profile.window_end)}<br />{profile.basis}</p>)}
            {evidence.policies.map(policy => <p key={policy.resource_id} className="my-2 text-xs">{resourceName(policy.resource_id)} · 优先级 v{policy.version} · 本项目顺位 {policy.rank} · {policy.status === "active" ? "启用" : "暂停"} · {when(policy.valid_from)} — {when(policy.valid_until)}</p>)}
            {evidence.reserved_intervals.map((span, index) => <p key={`r:${index}`} className="text-xs">{resourceName(span.resource_id)} · {when(span.start)} — {when(span.end)} · {span.units} 单位 · {span.origin === "legacy_inventory" ? "旧资源占用" : "已确认预约"}{span.covered_node_key ? ` · 对应 ${title(span.covered_node_key)}` : ""}</p>)}
            {evidence.priority_intervals.map((span, index) => <p key={`p:${index}`} className="text-xs">{resourceName(span.resource_id)} · {when(span.start)} — {when(span.end)} · {span.units} 单位 · 在先待办，顺位 {span.rank}</p>)}
            {Object.entries(item.inputs.demands).flatMap(([key, values]) => values.map((demand, index) => <p key={`${key}:${index}`} className="my-2 text-xs">{title(key)} · {evidence.profiles.find(profile => profile.id === demand.capacity_version_id)?.resource_name} · {demand.units} 单位 · {demand.contributes_effort ? "提供工时" : "辅助资源"} · {demand.occupancy_policy === "working_only" ? "工作时段占用" : "持续占用至完成"}：{demand.basis}</p>))}
            {Object.entries(item.inputs.no_resource_reasons).map(([key, reason]) => <p key={key} className="text-xs">{title(key)} 无需资源：{reason}</p>)}
          </details>
        </details>;
      })}
      {next && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void run(false, next)}>更早的日期方案</Button>}
      <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => void run(false)}>刷新历史</Button>
    </>}
  </section>;
}


function PrepareResourceDates({ solution, path, onPrepared }: { solution: Solution; path: string; onPrepared: (scenarioId: string) => Promise<void> }) {
  const [title, setTitle] = useState("资源约束日期方案");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<{ key: string; id: string } | null>(null);
  async function prepare() {
    setBusy(true); setError("");
    try {
      const body = { schedule_id: solution.id, expected_result_digest: solution.result_digest, title, reason };
      const key = JSON.stringify(body);
      if (pending.current?.key !== key) pending.current = { key, id: crypto.randomUUID() };
      const prepared = await caseLinkRequest<{ scenario_id: string }>(path, { ...body, request_id: pending.current.id });
      await onPrepared(prepared.scenario_id);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "计划情景准备失败"); }
    finally { setBusy(false); }
  }
  async function openPrepared() {
    if (!solution.preparation) return;
    setBusy(true); setError("");
    try {
      await onPrepared(solution.preparation.scenario_id);
      const id = solution.preparation.scenario_id;
      requestAnimationFrame(() => document.getElementById(`resource-plan-${id}`)?.scrollIntoView({ block: "start" }));
    } catch (failure) { setError(failure instanceof Error ? failure.message : "历史情景读取失败"); }
    finally { setBusy(false); }
  }
  if (solution.preparation) return <div className="space-y-1 rounded-md border p-2 text-xs">
    <p>已准备计划情景：{solution.preparation.title} · {when(solution.preparation.receipt.prepared_as_of)}</p>
    <p>{solution.preparation.receipt.dates_changed ? "准备时重新计算产生日期差异，请审阅新情景后继续批准。" : "准备时日期与所选方案一致，仍需办理正式基线批准及独立应用。"}</p>
    <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => void openPrepared()}>查看准备后的计划情景</Button>{error && <p role="alert" className="text-destructive">{error}</p>}
  </div>;
  return <details className="rounded-md border p-3"><summary className="cursor-pointer text-sm">按此方案准备计划情景</summary>
    <form className="mt-2 space-y-2" onSubmit={event => { event.preventDefault(); void prepare(); }}>
      <p className="text-xs">固定原工时、等待和资源选择，把候选开始时间带入原计划情景。准备时按当前时点重新计算，日期差异和容量结果会保留供审阅；后续沿原基线批准与独立应用办理，资源预约另行处理。</p>
      <label className="block text-sm">情景名称<input className={field} required maxLength={2048} disabled={busy} value={title} onChange={event => setTitle(event.target.value)} /></label>
      <label className="block text-sm">选定理由与需关注的影响<textarea className={field} required maxLength={2048} disabled={busy} value={reason} onChange={event => setReason(event.target.value)} /></label>
      <label className="flex gap-2 text-xs"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} />已核对资源、优先级、日期及预约差异；继续准备待审情景。</label>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <Button type="submit" size="sm" disabled={busy || !confirmed || !title.trim() || !reason.trim()}>{busy ? "正在准备…" : "准备计划情景"}</Button>
    </form>
  </details>;
}
