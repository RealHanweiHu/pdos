"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";
import type { Calendar } from "@/components/cases/work-calendar-form";

type Source = { id: string; code: string; name: string; resource_type: string; assigned_user_id: string | null; allocation_percent: string; start_date: string | null; end_date: string | null; status: string; details: Record<string, unknown> };
type Reconciliation = { id: string; legacy_resource_id: string; sequence: number; resource_name: string | null; disposition: string; window_start: string | null; window_end: string | null; parallel_units: string | null; occupancy_policy: string | null; basis: string; created_at: string; source_snapshot: Source };
type Item = { source: Source; source_digest: string; sequence: number; current: boolean; reconciliation: Reconciliation | null };
type Resource = { id: string; name: string; kind: string; user_id: string | null };
type State = { items: Item[]; has_more: boolean; can_manage: boolean; history: Reconciliation[] };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const types: Record<string, string> = { person: "人员", equipment: "设备", facility: "设施", capability: "能力" };
const status: Record<string, string> = { planned: "计划占用", active: "有效占用", released: "已释放" };
const compatible: Record<string, string[]> = { person: ["person"], equipment: ["equipment", "bench", "mold", "fixture"], facility: ["laboratory", "bench", "pilot_line"], capability: ["skill_group"] };
function DetailValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span>未填写</span>;
  if (typeof value !== "object") return <span className="whitespace-pre-wrap">{String(value)}</span>;
  return <dl className="space-y-1 pl-3">{Object.entries(value).map(([key, item]) => <div key={key}><dt className="font-medium">{key}</dt><dd><DetailValue value={item} /></dd></div>)}</dl>;
}
function SourceView({ source }: { source: Source }) {
  return <div className="space-y-1 text-xs"><p>{source.code} · {source.name} · {types[source.resource_type]} · {status[source.status]}</p><p>原分配比例：{source.allocation_percent}% · 开始：{source.start_date ?? "未知"} · 结束：{source.end_date ?? "未知"}</p>{Object.keys(source.details).length > 0 && <details><summary className="cursor-pointer">原记录详细依据</summary><DetailValue value={source.details} /></details>}</div>;
}
function ReconcileForm({ item, resources, calendars, busy, save }: { item: Item; resources: Resource[]; calendars: Calendar[]; busy: boolean; save: (body: object) => Promise<void> }) {
  const choices = resources.filter((resource) => compatible[item.source.resource_type]?.includes(resource.kind) && (item.source.resource_type !== "person" || !item.source.assigned_user_id || resource.user_id === item.source.assigned_user_id));
  const [resource, setResource] = useState(item.source.assigned_user_id ? choices.find((value) => value.user_id === item.source.assigned_user_id)?.id ?? "" : "");
  const [calendar, setCalendar] = useState("");
  const [start, setStart] = useState(""); const [end, setEnd] = useState("");
  const [units, setUnits] = useState(item.source.resource_type === "person" ? String(Number(item.source.allocation_percent) / 100) : "");
  const [policy, setPolicy] = useState("working_only"); const [basis, setBasis] = useState("");
  const released = item.source.status === "released";
  return <form className="space-y-2 border-t pt-3" onSubmit={(event) => { event.preventDefault(); void save({ legacy_resource_id: item.source.id, source_digest: item.source_digest, expected_sequence: item.sequence, disposition: released ? "retained_released" : "mapped", basis, ...(released ? {} : { resource_id: resource, calendar_version_id: calendar, window_start: new Date(start).toISOString(), window_end: new Date(end).toISOString(), parallel_units: units, occupancy_policy: policy }) }); }}>
    <p className="text-sm font-medium">{released ? "确认保留已释放历史" : "核对并归并旧占用"}</p>
    {!released && <>
      <label className="block text-sm">实际共享资源<select className={field} required value={resource} onChange={(event) => setResource(event.target.value)}><option value="">选择匹配身份</option>{choices.map((value) => <option value={value.id} key={value.id}>{value.name}</option>)}</select></label>
      {!choices.length && <p className="text-xs">尚无匹配的共享资源，请先在资源配置中登记实际身份。</p>}
      <label className="block text-sm">原占用适用日历<select className={field} required value={calendar} onChange={(event) => setCalendar(event.target.value)}><option value="">选择日历版本</option>{calendars.map((value) => <option key={value.id} value={value.id}>{value.name} v{value.version} · {value.definition.calendar.timezone}</option>)}</select></label>
      <p className="text-xs text-muted-foreground">时间以浏览器时区输入；窗口须覆盖原记录的全部日期，原结束日期按包含当天处理。未知日期须补充实际窗口及依据。</p>
      <div className="grid gap-2 sm:grid-cols-2"><label className="text-sm">占用开始<input className={field} type="datetime-local" required value={start} onChange={(event) => setStart(event.target.value)} /></label><label className="text-sm">占用结束<input className={field} type="datetime-local" required value={end} onChange={(event) => setEnd(event.target.value)} /></label></div>
      <label className="block text-sm">实际占用并行单位<input className={field} required type="number" min="0.00000001" max="1000" step="any" readOnly={item.source.resource_type === "person"} value={units} onChange={(event) => setUnits(event.target.value)} /></label>
      {item.source.resource_type === "person" && <p className="text-xs">人员占用沿用原分配比例；例如 50% 对应 0.5 单位。</p>}
      <label className="block text-sm">占用方式<select className={field} value={policy} onChange={(event) => setPolicy(event.target.value)}><option value="working_only">仅日历工作时段</option><option value="through_waiting">窗口内持续占用，含等待和非工作时段</option></select></label>
    </>}
    <label className="block text-sm">核对依据<textarea className={field} required maxLength={2048} value={basis} onChange={(event) => setBasis(event.target.value)} placeholder={released ? "记录原占用已释放的核对依据。" : "说明身份对应关系、占用窗口、单位换算及占用方式的实际依据。"} /></label>
    <Button type="submit" size="sm" disabled={busy || (!released && (!resource || !calendar))}>{released ? "保存释放历史核对" : "确认归并并计入容量"}</Button>
  </form>;
}

export function ProjectResourceInventory({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false); const [data, setData] = useState<State | null>(null);
  const [resources, setResources] = useState<Resource[]>([]); const [calendars, setCalendars] = useState<Calendar[]>([]);
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null); const [notice, setNotice] = useState<string | null>(null);
  const requests = useRef(new Map<string, string>());
  const path = `projects/${projectId}/resource-inventory`;
  async function load() { const [state, identities, calendarList] = await Promise.all([caseLinkRequest<State>(path), caseLinkRequest<{ items: Resource[] }>("planning/resources"), caseLinkRequest<{ items: Calendar[] }>("planning/calendars")]); setData(state); setResources(identities.items); setCalendars(calendarList.items); }
  async function refresh() { setBusy(true); setError(null); try { await load(); } catch (failure) { setError(failure instanceof Error ? failure.message : "盘点信息暂不可用"); } finally { setBusy(false); } }
  async function save(body: object) { setBusy(true); setError(null); setNotice(null); const key = JSON.stringify(body); let id = requests.current.get(key); if (!id) { id = crypto.randomUUID(); requests.current.set(key, id); } try { await caseLinkRequest(path, { ...body, request_id: id }); await load(); setNotice("核对记录已保存；有效旧占用已纳入后续容量检查。"); } catch (failure) { setError(failure instanceof Error ? failure.message : "归并未完成"); } finally { setBusy(false); } }
  return <section className="mt-4 space-y-3 rounded-lg border p-4"><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => { setOpen(!open); if (!open) void refresh(); }}>{open ? "收起旧资源盘点" : "旧资源盘点与归并"}</Button>{open && <div className="space-y-3">
    {error && <p className="text-sm text-destructive" role="alert">{error}</p>}{notice && <p className="text-sm" role="status">{notice}</p>}
    <p className="text-xs text-muted-foreground">盘点记录保存旧资源快照和共享身份对应关系。有效占用直接计入容量，不补造历史预约批准；原记录变化后需要重新核对。</p>
    {data && !data.items.length && <p className="text-sm">本项目没有旧资源记录。</p>}
    {data?.items.map((item) => <article className="space-y-2 rounded-md border p-3" key={item.source.id}><SourceView source={item.source} /><a className="text-xs text-primary underline" href={`/projects?project=${projectId}&tab=overview&resource_allocation_id=${item.source.id}`}>原分配释放与办理历史</a><p className="text-sm">{item.current ? "已核对当前版本" : item.reconciliation ? "原记录已变化，待重新核对" : "尚未核对"}</p>{item.reconciliation && <div className="text-xs"><p>{item.reconciliation.resource_name ?? "保留释放历史"} · 核对 v{item.sequence}</p><p className="whitespace-pre-wrap">{item.reconciliation.basis}</p></div>}
      {data.can_manage && <details><summary className="cursor-pointer text-sm">{item.reconciliation ? "修订核对记录" : "办理核对"}</summary><ReconcileForm key={`${item.source.id}:${item.sequence}:${item.source_digest}`} item={item} resources={resources} calendars={calendars} busy={busy} save={save} /></details>}
      <details><summary className="cursor-pointer text-xs">归并历史与原记录快照</summary>{data.history.filter((record) => record.legacy_resource_id === item.source.id).map((record) => <div key={record.id} className="space-y-1 border-t py-2 text-xs"><p>v{record.sequence} · {new Date(record.created_at).toLocaleString()} · {record.resource_name ?? "释放历史"}</p>{record.window_start && record.window_end && <p>{new Date(record.window_start).toLocaleString()} — {new Date(record.window_end).toLocaleString()} · {record.parallel_units} 单位 · {record.occupancy_policy === "working_only" ? "工作时段" : "持续占用"}</p>}<p className="whitespace-pre-wrap">{record.basis}</p><SourceView source={record.source_snapshot} /></div>)}</details>
    </article>)}
    {data?.has_more && <p className="text-xs">显示前 1000 条旧记录，尚有记录未展示。</p>}<Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => void refresh()}>刷新盘点记录</Button>
  </div>}</section>;
}
