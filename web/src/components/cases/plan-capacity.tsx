"use client";

import { ResourceScheduleSolutions } from "@/components/projects/resource-schedule-solutions";
import { ResourcePriorityPolicy } from "@/components/projects/resource-priority-policy";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "./case-requirements";
import type { Calendar } from "./work-calendar-form";

type Capacity = { id: string; version: number; calendar_version_id: string; window_start: string; window_end: string; parallel_units: string; basis: string; capacity_contract: { capacity: string; unit: string } };
type Resource = { id: string; name: string; kind: string; user_id: string | null; capacity: Capacity | null };
type Options = { items: Resource[]; can_manage: boolean; people: { id: string; display_name: string }[] };
type Demand = { capacity_version_id: string; units: string; contributes_effort: boolean; occupancy_policy: "working_only" | "through_waiting"; basis: string };
type Check = { id: string; created_at: string; inputs: { demands: Record<string, Demand[]>; no_resource_reasons?: Record<string, string> }; result: { schedule_as_of?: string; reservation_differences?: { resource_name: string; node_key: string; start: string; end: string; forecast_units: string | null; reserved_units: string; disposition: string; reservation_ids: string[] }[]; status: string; reservation_coverage?: string; reservation_evidence?: { resource_id: string; start: string; end: string; units: string; origin?: string; covered_node_key?: string }[]; resources: { resource_id: string; name: string; peak_units: string; workload_hours: string; node_keys: string[] }[]; conflicts: { resource_id: string; resource_name: string; start: string; end: string; demand_units: string; available_units: string; node_keys: string[] }[]; unknown: { node_key: string; reason: string }[]; warnings: { node_key: string; reason: string }[]; profiles: { id: string; resource_name: string; version: number; basis: string; window_start: string; window_end: string; parallel_units: string }[] } };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const kinds: Record<string, string> = { person: "人员", skill_group: "技能组", laboratory: "实验室", bench: "台架", equipment: "设备", mold: "模具", fixture: "治具", pilot_line: "试制线" };
const statuses: Record<string, string> = { conflicts: "发现容量冲突", unknown: "仍有容量缺项", scenario_only_clear: "本情景内部未发现冲突", capacity_clear: "计入已有预约后未发现容量冲突" };
function localInput(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function CapacityForm({ resource, calendars, busy, save }: { resource: Resource; calendars: Calendar[]; busy: boolean; save: (path: string, body: object) => Promise<void> }) {
  const [calendar, setCalendar] = useState(resource.capacity?.calendar_version_id ?? calendars[0]?.id ?? "");
  const [start, setStart] = useState(localInput(resource.capacity?.window_start));
  const [end, setEnd] = useState(localInput(resource.capacity?.window_end));
  const [units, setUnits] = useState(resource.capacity?.parallel_units ?? "");
  const [basis, setBasis] = useState("");
  return <form className="space-y-2 rounded-md border p-3" onSubmit={(event) => { event.preventDefault(); void save("planning/capacities", { resource_id: resource.id, expected_version: resource.capacity?.version ?? 0, calendar_version_id: calendar, window_start: new Date(start).toISOString(), window_end: new Date(end).toISOString(), parallel_units: units, basis }); }}>
    <h5 className="text-sm font-medium">{resource.name} · {resource.capacity ? `发布容量 v${resource.capacity.version + 1}` : "配置容量"}</h5>
    <p className="text-xs text-muted-foreground">新版本完整替代可用性声明，旧版本保留。窗口以浏览器时区填写，日历决定窗口内的工作时段。</p>
    <label className="block text-sm">工作日历<select className={field} required value={calendar} onChange={(event) => setCalendar(event.target.value)}><option value="">选择日历</option>{calendars.map((item) => <option key={item.id} value={item.id}>{item.name} v{item.version} · {item.definition.calendar.timezone}</option>)}</select></label>
    <div className="grid gap-2 sm:grid-cols-2"><label className="text-sm">窗口开始<input className={field} required type="datetime-local" value={start} onChange={(event) => setStart(event.target.value)} /></label><label className="text-sm">窗口结束<input className={field} required type="datetime-local" value={end} onChange={(event) => setEnd(event.target.value)} /></label></div>
    <label className="block text-sm">工作时段内最多并行单位<input className={field} required type="number" min="0" max={resource.kind === "person" ? "1" : "1000"} step="any" value={units} onChange={(event) => setUnits(event.target.value)} /></label>
    <label className="block text-sm">容量依据<textarea required maxLength={2048} className={field} value={basis} onChange={(event) => setBasis(event.target.value)} placeholder="可投入比例、班次、设备数量及窗口依据；未知容量暂不发布。" /></label>
    <Button type="submit" size="sm" disabled={busy || !calendar}>发布容量版本</Button>
  </form>;
}

export function PlanCapacity({ candidateId, scenarioId, nodes, calendars, requestPath, forecastMode = false, scenarioMode = false, onScenarioPrepared }: { onScenarioPrepared?: (scenarioId?: string) => Promise<void>; candidateId: string; scenarioId: string; requestPath?: string; forecastMode?: boolean; scenarioMode?: boolean; nodes: { node_key: string; title?: string; owner_user_id?: string | null; work_minutes: number | null; allocation: { parallel_units: string } }[]; calendars: Calendar[] }) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<Options | null>(null);
  const [checks, setChecks] = useState<Check[]>([]);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [demands, setDemands] = useState<Record<string, Demand[]>>({});
  const [noResources, setNoResources] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [kind, setKind] = useState("person");
  const [person, setPerson] = useState("");
  const [editing, setEditing] = useState("");
  const requestIds = useRef(new Map<string, string>());
  const defaultsLoaded = useRef(false);
  const [loadedCalendars, setLoadedCalendars] = useState<Calendar[]>([]);
  const path = requestPath ?? `initial-plans/${candidateId}/scenarios/${scenarioId}/capacity-checks`;
  async function load() {
    const [choices, history, calendarOptions] = await Promise.all([caseLinkRequest<Options>("planning/resources"), caseLinkRequest<{ items: Check[]; has_more: boolean; initial_demands?: Record<string, Demand[]>; initial_no_resource_reasons?: Record<string, string> }>(path), calendars.length ? Promise.resolve({ items: calendars }) : caseLinkRequest<{ items: Calendar[] }>("planning/calendars")]);
    setLoadedCalendars(calendarOptions.items);
    if (!defaultsLoaded.current) { if (history.initial_demands) setDemands(history.initial_demands); if (history.initial_no_resource_reasons) setNoResources(history.initial_no_resource_reasons); defaultsLoaded.current = true; }
    setOptions(choices); setChecks(history.items); setMore(history.has_more);
  }
  async function refresh() { setBusy(true); setError(null); try { await load(); } catch (failure) { setError(failure instanceof Error ? failure.message : "资源配置暂不可用"); } finally { setBusy(false); } }
  async function save(endpoint: string, body: object) {
    setBusy(true); setError(null);
    const key = JSON.stringify({ endpoint, body });
    let id = requestIds.current.get(key);
    if (!id) { id = crypto.randomUUID(); requestIds.current.set(key, id); }
    try { await caseLinkRequest(endpoint, { ...body, request_id: id }); await load(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "资源操作未完成"); }
    finally { setBusy(false); }
  }
  const resources = options?.items ?? [];
  const available = resources.filter((resource) => resource.capacity);
  const edit = resources.find((resource) => resource.id === editing);
  function update(key: string, index: number, patch: Partial<Demand>) { setDemands({ ...demands, [key]: (demands[key] ?? []).map((item, position) => position === index ? { ...item, ...patch } : item) }); }
  return <section className="space-y-3 border-t pt-3">
    <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => { setOpen(!open); if (!open) void refresh(); }}>{open ? "收起容量检查" : "配置资源并检查容量"}</Button>
    {open && <div className="space-y-3">
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <p className="text-xs text-muted-foreground">{scenarioMode ? "按固定情景的剩余工作窗口核对当前容量及已有预约。比较结果保留情景计算时点；正式批准应用前需按届时的进展、日期和预约重新核对。" : forecastMode ? "按本轮预测的剩余工作窗口检查容量。同一节点已确认的预约覆盖相应需求，其余预约仍计入占用；检查保留现有预约，差异需另行办理。" : "检查固定排程中的资源重叠和可用时段，并计入当前正式预约；旧资源尚未归并时明确列为缺项。检查不会占用资源，等待期间是否持续占用需逐项选择。"}</p>
      <details className="space-y-2 rounded-md border p-3"><summary className="cursor-pointer text-sm font-medium">共享资源与容量（{resources.length}）</summary>
        {resources.map((resource) => <div key={resource.id} className="space-y-1 border-b py-2 text-sm"><p>{resource.name} · {kinds[resource.kind]}</p>{resource.capacity ? <><p>容量 v{resource.capacity.version} · {resource.capacity.parallel_units} 并行单位</p><p className="text-xs">{new Date(resource.capacity.window_start).toLocaleString()} — {new Date(resource.capacity.window_end).toLocaleString()}</p><p className="whitespace-pre-wrap text-xs text-muted-foreground">{resource.capacity.basis}</p></> : <p className="text-xs">容量待配置</p>}{options?.can_manage && <ResourcePriorityPolicy resourceId={resource.id} resourceName={resource.name}/>}{options?.can_manage && <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setEditing(resource.id)}>配置新容量版本</Button>}</div>)}
        {options?.can_manage && <>
          <form className="space-y-2 border-t pt-3" onSubmit={(event) => { event.preventDefault(); void save("planning/resources", { name, kind, user_id: kind === "person" ? person : null }); }}>
            <h5 className="text-sm font-medium">登记共享资源</h5><label className="block text-sm">资源名称<input required maxLength={256} className={field} value={name} onChange={(event) => setName(event.target.value)} /></label>
            <label className="block text-sm">资源类型<select className={field} value={kind} onChange={(event) => setKind(event.target.value)}>{Object.entries(kinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            {kind === "person" && <label className="block text-sm">实际人员<select required className={field} value={person} onChange={(event) => setPerson(event.target.value)}><option value="">选择内部成员</option>{options.people.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label>}
            <Button type="submit" size="sm" disabled={busy}>登记资源</Button>
          </form>
          {edit && <CapacityForm key={`${edit.id}:${edit.capacity?.version ?? 0}`} resource={edit} calendars={calendars.length ? calendars : loadedCalendars} busy={busy} save={save} />}
        </>}
      </details>
      {!available.length && <p className="text-sm">尚无已配置容量的共享资源，请由资源配置管理员先登记并发布容量。</p>}
      <Button type="button" size="sm" variant="outline" disabled={busy || !available.length} onClick={() => {
        const next = { ...demands };
        for (const node of nodes) {
          if (next[node.node_key]?.length || noResources[node.node_key]?.trim() || node.work_minutes === 0) continue;
          const resource = available.find((item) => item.kind === "person" && item.user_id === node.owner_user_id);
          if (resource?.capacity) next[node.node_key] = [{ capacity_version_id: resource.capacity.id, units: node.allocation.parallel_units, contributes_effort: true, occupancy_policy: "working_only", basis: "按候选负责人匹配已配置人员资源；投入沿用本情景假设，仅占用工作时段。" }];
        }
        setDemands(next);
      }}>按负责人匹配空白节点的人员资源</Button>
      {nodes.map((node) => <details key={node.node_key} className="space-y-2 rounded-md border p-2"><summary className="cursor-pointer text-sm">{node.node_key} · {node.title} · 排程投入 {node.allocation.parallel_units} 单位</summary>
        {node.work_minutes === 0 && <label className="block text-sm">零工时节点无需资源的依据（填写后此节点不再添加资源）<input className={field} maxLength={2048} value={noResources[node.node_key] ?? ""} disabled={busy || !!demands[node.node_key]?.length} onChange={(event) => setNoResources({ ...noResources, [node.node_key]: event.target.value })} /></label>}
        {(demands[node.node_key] ?? []).map((demand, index) => <div className="space-y-2 rounded-md border p-2" key={index}>
          <label className="block text-sm">资源与容量版本<select required className={field} disabled={busy} value={demand.capacity_version_id} onChange={(event) => update(node.node_key, index, { capacity_version_id: event.target.value })}><option value="">选择资源</option>{available.map((resource) => <option key={resource.id} value={resource.capacity!.id}>{resource.name} · v{resource.capacity!.version}</option>)}{demand.capacity_version_id && !available.some((resource) => resource.capacity!.id === demand.capacity_version_id) && <option value={demand.capacity_version_id}>先前选择的容量已修订，请重选</option>}</select></label>
          <label className="block text-sm">占用单位<input required type="number" min="0.00000001" max="1000" step="any" className={field} disabled={busy} value={demand.units} onChange={(event) => update(node.node_key, index, { units: event.target.value })} /></label>
          <label className="flex gap-2 text-sm"><input type="checkbox" checked={demand.contributes_effort} disabled={busy} onChange={(event) => update(node.node_key, index, { contributes_effort: event.target.checked })} />该资源提供排程估算中的工时投入</label>
          <label className="block text-sm">占用时段<select className={field} disabled={busy} value={demand.occupancy_policy} onChange={(event) => update(node.node_key, index, { occupancy_policy: event.target.value as Demand["occupancy_policy"] })}><option value="working_only">仅节点实际工作时段</option><option value="through_waiting">从开始至完成持续占用（含等待与非工作时段）</option></select></label>
          <label className="block text-sm">投入和占用依据<textarea required maxLength={2048} className={field} disabled={busy} value={demand.basis} onChange={(event) => update(node.node_key, index, { basis: event.target.value })} /></label>
          <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setDemands({ ...demands, [node.node_key]: demands[node.node_key].filter((_, position) => position !== index) })}>移除此项资源</Button>
        </div>)}
        <Button type="button" size="sm" variant="outline" disabled={busy || !available.length || !!noResources[node.node_key]?.trim()} onClick={() => setDemands({ ...demands, [node.node_key]: [...(demands[node.node_key] ?? []), { capacity_version_id: "", units: "", contributes_effort: true, occupancy_policy: "working_only", basis: "" }] })}>添加资源需求</Button>
      </details>)}
      <Button type="button" size="sm" disabled={busy || Object.values(demands).flat().some((item) => !item.capacity_version_id || !item.units || !item.basis.trim())} onClick={() => void save(path, { demands, no_resource_reasons: Object.fromEntries(Object.entries(noResources).filter(([, reason]) => reason.trim()).map(([key, reason]) => [key, reason.trim()])) })}>{scenarioMode ? "检查并保存情景容量" : forecastMode ? "检查并保存预测容量" : "检查并保存容量情景"}</Button>
      {scenarioMode && <ResourceScheduleSolutions onPrepared={onScenarioPrepared} path={path.replace(/capacity-checks$/, "resource-schedules")} demands={demands} noResourceReasons={noResources} nodes={nodes} />}
      {checks.map((check) => <details key={check.id} className="space-y-2 rounded-md border p-3"><summary className="cursor-pointer text-sm font-medium">{new Date(check.created_at).toLocaleString()} · {statuses[check.result.status]}</summary>
        <p className="text-xs text-muted-foreground">{scenarioMode ? "此记录固定情景窗口及检查时的容量、预约；预约差异须另行办理。" : forecastMode ? "历史检查固定当时的预测窗口、容量和预约。需求或预约变化后需重新检查；新增、取消或释放预约仍单独办理。" : "历史检查基于当时的容量版本和预约快照；正式应用前需要重新检查并取得批准。"}</p>
        {check.result.schedule_as_of && <p className="text-xs">排程计算时点：{new Date(check.result.schedule_as_of).toLocaleString()}</p>}
        {check.result.resources.map((resource) => <p key={resource.resource_id} className="text-sm">{resource.name} · 总峰值 {resource.peak_units} 单位 · 本情景占用累计 {Number(resource.workload_hours).toFixed(2)} 单位小时 · {resource.node_keys.join("、")}</p>)}
        {check.result.reservation_coverage === "not_connected" && <p className="text-xs">此历史检查尚未计入正式预约。</p>}
        {!!check.result.reservation_evidence?.length && <details><summary className="cursor-pointer text-xs">检查时的已知占用</summary>{check.result.reservation_evidence.map((occupied,index) => <p key={index} className="text-xs">{check.result.resources.find((resource) => resource.resource_id===occupied.resource_id)?.name ?? "共享资源"} · {new Date(occupied.start).toLocaleString()} — {new Date(occupied.end).toLocaleString()} · {occupied.units} 单位 · {occupied.origin === "legacy_inventory" ? "旧资源归并" : "正式预约"}{occupied.covered_node_key ? ` · 已覆盖节点 ${occupied.covered_node_key} 的相应需求` : ""}</p>)}</details>}
        {!!check.result.reservation_differences?.length && <details><summary className="cursor-pointer text-sm">{scenarioMode ? "情景需求与已确认预约的差异" : "预测需求与已确认预约的差异"}</summary>{check.result.reservation_differences.map((difference,index) => <div key={index} className="my-2 border-l pl-2 text-xs"><p className="font-medium">{difference.node_key} · {difference.resource_name} · {difference.disposition === "additional_capacity_needed" ? "尚需预约覆盖" : difference.disposition === "requirement_unknown" ? "需求待定，暂不能判断是否释放" : "多余预约可另行核对释放"}</p><p>{new Date(difference.start).toLocaleString()} — {new Date(difference.end).toLocaleString()}</p><p>{scenarioMode ? "情景需求" : "预测需求"} {difference.forecast_units ?? "未知"} / 已预约 {difference.reserved_units} 单位</p>{difference.reservation_ids.length > 0 && <p>相关预约：{difference.reservation_ids.join("、")}</p>}</div>)}</details>}
        {check.result.conflicts.map((conflict, index) => <p key={index} className="text-sm text-destructive">{conflict.resource_name}：{new Date(conflict.start).toLocaleString()} — {new Date(conflict.end).toLocaleString()} · 需求 {conflict.demand_units} / 可用 {conflict.available_units} · {conflict.node_keys.join("、")}</p>)}
        {[...check.result.unknown, ...check.result.warnings].map((item, index) => <p key={index} className="text-xs">{item.node_key}：{item.reason}</p>)}
        <details><summary className="cursor-pointer text-xs">资源版本及投入依据</summary>{check.result.profiles.map((profile) => <p key={profile.id} className="my-2 whitespace-pre-wrap text-xs">{profile.resource_name} v{profile.version} · {profile.parallel_units} 单位<br />{new Date(profile.window_start).toLocaleString()} — {new Date(profile.window_end).toLocaleString()}<br />{profile.basis}</p>)}{Object.entries(check.inputs.demands).flatMap(([key, values]) => values.map((demand, index) => <p key={`${key}:${index}`} className="my-2 text-xs">{key} · {check.result.profiles.find((profile) => profile.id === demand.capacity_version_id)?.resource_name} · {demand.units} 单位 · {demand.contributes_effort ? "计入工时投入" : "辅助占用"} · {demand.occupancy_policy === "working_only" ? "仅工作时段" : "持续占用含等待"}：{demand.basis}</p>))}{Object.entries(check.inputs.no_resource_reasons ?? {}).map(([key, reason]) => <p key={key} className="text-xs">{key} 无需资源：{reason}</p>)}</details>
      </details>)}
      {more && <p className="text-xs">显示最近 50 次容量检查。</p>}
      <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => void refresh()}>刷新资源和容量检查</Button>
    </div>}
  </section>;
}
