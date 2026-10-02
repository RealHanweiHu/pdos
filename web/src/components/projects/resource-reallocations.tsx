"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";

type Resource = { id: string; name: string; capacity: { id: string; version: number } | null };
type Option = { id: string; project_id: string; project_name: string; node_id: string; state: string; capacity_version_id: string; window_start: string; window_end: string; parallel_units: string; occupancy_policy: string; basis: string; payload_digest: string };
type Selected = { original: Option; capacity: string; start: string; end: string; units: string; occupancy: string; impact: string; targetRequest: string };
type Issue = { resource_name?: string; reason?: string; start?: string; end?: string; demand_units?: string; available_units?: string };
type Item = { reservation_id: string; project_id: string; resource_name: string; rank: number; impact: string; original: { state: string; window_start: string; window_end: string; parallel_units: string }; target: { window_start: string; window_end: string; parallel_units: string; occupancy_policy: string } };
type Body = { project: { id: string; name: string; owner_name: string }; items: Item[]; conflicts: Issue[]; unknown: Issue[]; capacity_clear: boolean; reason: string };
type Allocation = { id: string; title: string; created_at: string; payload_digest: string; project_count: number; approved_count: number; status: string; can_decide: boolean; can_withdraw: boolean; can_apply: boolean; parts: { project_id: string; body: Body }[]; decisions: { id: string; project_id: string | null; action: string; reason: string; created_at: string }[]; application: { items: { project_id: string; previous_reservation_id: string; reservation_id: string }[] } | null };
type Preview = { snapshot: { projects: { id: string; name: string; owner_name: string }[]; items: Item[]; conflicts: Issue[]; unknown: Issue[]; capacity_clear: boolean }; preview_digest: string };
type Review = { allocation_id: string; payload_digest: string; sources_current: boolean; capacity_clear: boolean; blockers: string[] };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const when = (value?: string) => value ? new Date(value).toLocaleString() : "未知";
const local = (value: string) => { const date = new Date(value); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
const states: Record<string, string> = { pending: "等待项目确认", ready: "各项目已同意，待独立应用", stopped: "已拒绝或撤回", applied: "已应用预约调整" };
function Issues({ values }: { values: Issue[] }) { return <>{values.map((value, index) => <p key={index} className="text-xs text-destructive">{value.reason ?? `${value.resource_name}：${when(value.start)} — ${when(value.end)}，需求 ${value.demand_units} / 可用 ${value.available_units}`}</p>)}</>; }
function Changes({ items }: { items: Item[] }) { return <>{items.map(item => <div key={item.reservation_id} className="my-2 border-l pl-2 text-xs"><p className="font-medium">{item.resource_name} · 项目顺位 {item.rank} · {item.original.state === "reserved" ? "调整已确认预约" : "接续确认原待办"}</p><p>原窗口 {when(item.original.window_start)} — {when(item.original.window_end)} · {item.original.parallel_units} 单位</p><p>目标窗口 {when(item.target.window_start)} — {when(item.target.window_end)} · {item.target.parallel_units} 单位 · {item.target.occupancy_policy === "working_only" ? "工作时段" : "持续占用"}</p><p className="whitespace-pre-wrap">影响及处置：{item.impact}</p><a className="text-primary underline" href={`/projects?project=${item.project_id}&tab=overview&resource_reservation_id=${item.reservation_id}#resource-reservations`}>查看原预约</a></div>)}</>; }

export function ResourceReallocations({ projectId, onChanged }: { projectId: string; onChanged: () => Promise<void> }) {
  return <ResourceReallocationsContent key={projectId} projectId={projectId} onChanged={onChanged} />;
}

function ResourceReallocationsContent({ projectId, onChanged }: { projectId: string; onChanged: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<{ items: Allocation[]; next: string | null; can_propose: boolean } | null>(null);
  const [resources, setResources] = useState<Resource[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});
  const [reviews, setReviews] = useState<Record<string, Review>>({});
  const [receipt, setReceipt] = useState("");
  const requests = useRef(new Map<string, string>());
  const base = `projects/${projectId}/execution`;
  async function load(before?: string) {
    setReviews({}); setConfirmed({});
    try {
      const result = await caseLinkRequest<{ items: Allocation[]; next: string | null; can_propose: boolean }>(`${base}/resource-reallocations${before ? `?before=${before}` : ""}`);
      setResources(result.can_propose ? (await caseLinkRequest<{ items: Resource[] }>("planning/resources")).items : []);
      setData(previous => before && previous ? { ...result, items: [...previous.items, ...result.items.filter(item => !previous.items.some(old => old.id === item.id))] } : result);
    } catch (failure) { setData(null); setResources([]); throw failure; }
  }
  async function refresh(before?: string) { setBusy(true); setError(""); try { await load(before); } catch (failure) { setError(failure instanceof Error ? failure.message : "跨项目调整暂不可用"); } finally { setBusy(false); } }
  async function proposalSaved(id: string) {
    setReceipt(`调整方案已保存，回执 ${id}。可刷新调整记录继续办理。`);
    try { await load(); } catch (failure) { setError(failure instanceof Error ? failure.message : "方案已保存，调整记录暂未刷新"); }
  }
  async function review(item: Allocation) {
    setBusy(true); setError(""); setConfirmed(previous => ({ ...previous, [item.id]: false }));
    setReviews(previous => { const next = { ...previous }; delete next[item.id]; return next; });
    try {
      const result = await caseLinkRequest<Review>(`${base}/resource-reallocation-preview`, { allocation_id: item.id, expected_digest: item.payload_digest });
      if (result.allocation_id !== item.id || result.payload_digest !== item.payload_digest || typeof result.sources_current !== "boolean" || typeof result.capacity_clear !== "boolean" || !Array.isArray(result.blockers) || !result.blockers.every(reason => typeof reason === "string")) throw new Error("当前核对结果不完整，请重新读取");
      setReviews(previous => ({ ...previous, [item.id]: result }));
    } catch (failure) { setError(failure instanceof Error ? failure.message : "当前条件核对未完成"); }
    finally { setBusy(false); }
  }
  async function act(item: Allocation, action: string) {
    const body = { allocation_id: item.id, expected_digest: item.payload_digest, reason: reasons[item.id], ...(action === "apply" ? {} : { action }) };
    const key = JSON.stringify(body); let id = requests.current.get(key); if (!id) { id = crypto.randomUUID(); requests.current.set(key, id); }
    setBusy(true); setError(""); setReceipt("");
    setConfirmed(previous => ({ ...previous, [item.id]: false }));
    setReviews(previous => { const next = { ...previous }; delete next[item.id]; return next; });
    try { await caseLinkRequest(`${base}/resource-reallocation-${action === "apply" ? "applications" : "decisions"}`, { ...body, request_id: id }); if (action === "apply") window.dispatchEvent(new Event("pdos:forecast-updated")); setReceipt(action === "apply" ? "整批预约调整已应用；请沿预测反馈核对剩余容量，并回查实际预约。" : "本次处置已记录，可刷新查看原回执。"); await load(); await onChanged(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "调整操作未完成"); }
    finally { setBusy(false); }
  }
  return <section id="resource-reallocations" className="space-y-3 rounded-md border p-3">
    <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => { setOpen(!open); if (!open) void refresh(); }}>{open ? "收起跨项目资源调整" : "跨项目资源改期与接续"}</Button>
    {open && <>
      <p className="text-xs text-muted-foreground">资源管理员提出调整，各受影响项目的当前负责人确认本项目影响后，管理员再独立应用。应用会同时释放所选旧预约、建立新占用并确认接续待办；任一项失败，整批保留原状。基线和交付承诺仍按各项目原流程办理。</p>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {receipt && <p role="status" className="text-sm text-primary">{receipt}</p>}
      {data?.can_propose && <ReallocationBuilder base={base} projectId={projectId} resources={resources} onSaved={proposalSaved} />}
      {data?.items.map(item => <details key={item.id} className="space-y-2 rounded-md border p-3"><summary className="cursor-pointer text-sm font-medium">{item.title} · {states[item.status]} · {when(item.created_at)}</summary>
        <p className="text-xs">已同意 {item.approved_count} / {item.project_count} 个项目。来源固定于提出时，后续确认及应用还会复核；资料变化须重新提出。</p>
        {(item.can_decide || item.can_apply) && <div className="space-y-2"><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void review(item)}>核对当前政策与占用</Button>{reviews[item.id] ? <><p className="text-xs">{reviews[item.id].sources_current && reviews[item.id].capacity_clear ? "当前来源与容量通过核对；提交时再次复核。" : "原方案当前不可同意或应用；请由资源管理员按当前资料重新提出。"}</p>{reviews[item.id].blockers.map((reason, index) => <p key={index} className="text-xs text-destructive">{reason}</p>)}</> : <p className="text-xs text-muted-foreground">同意或应用前，先读取当前政策、原预约和占用条件。</p>}</div>}
        {item.parts.map(part => <div key={part.project_id} className="space-y-1 border-l pl-2"><p className="text-sm font-medium">{part.body.project.name} · 确认人 {part.body.project.owner_name}</p><p className="text-xs whitespace-pre-wrap">{part.body.reason}</p><Changes items={part.body.items}/><Issues values={[...part.body.conflicts, ...part.body.unknown]}/>{!part.body.capacity_clear && <p className="text-xs text-destructive">整批仍有容量冲突或缺项，须调整方案后重新提出。</p>}</div>)}
        {item.decisions.map(decision => <p key={decision.id} className="text-xs">{decision.action === "approve" ? "同意" : decision.action === "reject" ? "拒绝" : "撤回"} · {when(decision.created_at)}：{decision.reason}</p>)}
        {(item.can_decide || item.can_withdraw || item.can_apply) && <div className="space-y-2"><label className="block text-sm">本次确认／处置说明<textarea required className={field} maxLength={2048} disabled={busy} value={reasons[item.id] ?? ""} onChange={event => { setReasons({ ...reasons, [item.id]: event.target.value }); setConfirmed({ ...confirmed, [item.id]: false }); }} /></label><label className="flex gap-2 text-xs"><input type="checkbox" disabled={busy} checked={!!confirmed[item.id]} onChange={event => setConfirmed({ ...confirmed, [item.id]: event.target.checked })} />已核对所示版本、原预约、调整后窗口及影响</label><div className="flex flex-wrap gap-2">{(item.can_decide ? ["approve", "reject"] : []).concat(item.can_withdraw ? ["withdraw"] : [], item.can_apply ? ["apply"] : []).map(action => <Button key={action} type="button" size="sm" variant={action === "reject" || action === "withdraw" ? "outline" : "default"} disabled={busy || !confirmed[item.id] || !reasons[item.id]?.trim() || ((action === "approve" || action === "apply") && (!reviews[item.id]?.sources_current || !reviews[item.id]?.capacity_clear))} onClick={() => void act(item, action)}>{action === "approve" ? "同意本项目调整" : action === "reject" ? "拒绝本项目调整" : action === "withdraw" ? "撤回整批方案" : "独立应用整批预约调整"}</Button>)}</div></div>}
        {item.application?.items.map(receipt => <p key={receipt.reservation_id} className="text-xs"><a className="text-primary underline" href={`/projects?project=${receipt.project_id}&tab=overview&resource_reservation_id=${receipt.reservation_id}#resource-reservations`}>查看应用后的实际预约</a></p>)}
      </details>)}
      {data?.next && <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void refresh(data.next!)}>更早的调整</Button>}
      <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => void refresh()}>刷新调整记录</Button>
    </>}
  </section>;
}

function ReallocationBuilder({ base, projectId, resources, onSaved }: { base: string; projectId: string; resources: Resource[]; onSaved: (id: string) => Promise<void> }) {
  const [resource, setResource] = useState(""); const [search, setSearch] = useState("");
  const [options, setOptions] = useState<Option[]>([]); const [next, setNext] = useState<string | null>(null);
  const [selected, setSelected] = useState<Selected[]>([]); const [title, setTitle] = useState(""); const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<{ result: Preview; body: object } | null>(null); const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [saved, setSaved] = useState(""); const request = useRef<{ key: string; id: string } | null>(null);
  const available = resources.filter(value => value.capacity);
  function update(index: number, patch: Partial<Selected>) { setSelected(selected.map((item, position) => index === position ? { ...item, ...patch } : item)); setPreview(null); setConfirmed(false); }
  async function find(before?: string) { setBusy(true); setError(""); try { const query = new URLSearchParams({ resource_id: resource, search, ...(before ? { before } : {}) }); const result = await caseLinkRequest<{ items: Option[]; next: string | null }>(`${base}/resource-reallocation-options?${query}`); setOptions(previous => before ? [...previous, ...result.items.filter(item => !previous.some(old => old.id === item.id))] : result.items); setNext(result.next); } catch (failure) { setError(failure instanceof Error ? failure.message : "预约读取失败"); } finally { setBusy(false); } }
  async function evaluate() {
    setBusy(true); setError(""); setPreview(null); setConfirmed(false);
    try {
      const inputs = { title, reason, items: selected.map(item => ({ reservation_id: item.original.id, expected_digest: item.original.payload_digest, impact: item.impact, target: { request_id: item.targetRequest, node_id: item.original.node_id, task_id: null, capacity_version_id: item.capacity, window_start: item.start === local(item.original.window_start) ? item.original.window_start : new Date(item.start).toISOString(), window_end: item.end === local(item.original.window_end) ? item.original.window_end : new Date(item.end).toISOString(), parallel_units: item.units, occupancy_policy: item.occupancy, basis: item.original.state === "proposed" ? item.original.basis : item.impact } })) };
      const result = await caseLinkRequest<Preview>(`${base}/resource-reallocation-preview`, { ...inputs, request_id: request.current?.id ?? crypto.randomUUID() });
      const key = JSON.stringify({ ...inputs, expected_preview_digest: result.preview_digest }); if (request.current?.key !== key) request.current = { key, id: crypto.randomUUID() };
      setPreview({ result, body: { ...inputs, request_id: request.current.id } });
    } catch (failure) { setError(failure instanceof Error ? failure.message : "调整预览失败"); }
    finally { setBusy(false); }
  }
  async function submit() { if (!preview) return; setBusy(true); setError(""); try { const result = await caseLinkRequest<{ id: string }>(`${base}/resource-reallocations`, { ...preview.body, expected_preview_digest: preview.result.preview_digest }); setSaved(result.id); setSelected([]); setPreview(null); setConfirmed(false); request.current = null; await onSaved(result.id); } catch (failure) { setError(failure instanceof Error ? failure.message : "调整保存或回执刷新未完成"); } finally { setBusy(false); } }
  return <details className="space-y-3 rounded-md border p-3"><summary className="cursor-pointer text-sm font-medium">提出跨项目改期／接续方案</summary>
    <p className="text-xs">选择 2—20 项实际预约，须涉及至少两个项目且包含本项目。已确认预约可改资源、日期或单位；待确认预约保留原请求，随整批接续确认。标题和总说明供受影响项目读取，各项目仅查看自己的明细。</p>
    <div className="grid gap-2 sm:grid-cols-2"><label className="text-sm">查找原资源<select className={field} value={resource} disabled={busy} onChange={event => { setResource(event.target.value); setOptions([]); setNext(null); }}><option value="">选择资源</option>{resources.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="text-sm">按项目名称筛选<input className={field} value={search} maxLength={100} disabled={busy} onChange={event => { setSearch(event.target.value); setOptions([]); setNext(null); }} /></label></div>
    <Button type="button" size="sm" variant="outline" disabled={busy || !resource} onClick={() => void find()}>查找实际预约</Button>
    {options.map(option => <label key={option.id} className="flex gap-2 text-xs"><input type="checkbox" disabled={busy || (selected.length >= 20 && !selected.some(item => item.original.id === option.id))} checked={selected.some(item => item.original.id === option.id)} onChange={event => { setPreview(null); setConfirmed(false); setSelected(event.target.checked ? [...selected, { original: option, capacity: option.capacity_version_id, start: local(option.window_start), end: local(option.window_end), units: option.parallel_units, occupancy: option.occupancy_policy, impact: "", targetRequest: crypto.randomUUID() }] : selected.filter(item => item.original.id !== option.id)); }} /><span>{option.project_name} · {option.state === "reserved" ? "已预约" : "待确认"} · {when(option.window_start)} — {when(option.window_end)} · {option.parallel_units} 单位<br />{option.basis}</span></label>)}
    {next && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void find(next)}>更多原预约</Button>}
    <form className="space-y-3" onSubmit={event => { event.preventDefault(); void evaluate(); }}>
      <label className="block text-sm">方案标题<input required className={field} maxLength={2048} disabled={busy} value={title} onChange={event => { setTitle(event.target.value); setPreview(null); }} /></label>
      <label className="block text-sm">调整目的与共同处置说明<textarea required className={field} maxLength={2048} disabled={busy} value={reason} onChange={event => { setReason(event.target.value); setPreview(null); }} /></label>
      {selected.map((item, index) => <div key={item.original.id} className="space-y-2 rounded-md border p-2"><p className="text-sm font-medium">{item.original.project_name} · {item.original.state === "reserved" ? "改期/调整" : "原待办接续确认"}</p><p className="text-xs">原窗口 {when(item.original.window_start)} — {when(item.original.window_end)}</p>
        <label className="block text-sm">目标资源与容量<select className={field} required disabled={busy || item.original.state === "proposed"} value={item.capacity} onChange={event => update(index, { capacity: event.target.value })}>{!available.some(value => value.capacity!.id === item.capacity) && <option value={item.capacity}>原容量已有新版本，请重新选择</option>}{available.map(value => <option key={value.id} value={value.capacity!.id}>{value.name} · v{value.capacity!.version}</option>)}</select></label>
        <div className="grid gap-2 sm:grid-cols-2">{(["start", "end"] as const).map(key => <label key={key} className="text-sm">{key === "start" ? "开始" : "结束"}（本地时间）<input required className={field} type="datetime-local" value={item[key]} disabled={busy || item.original.state === "proposed"} onChange={event => update(index, { [key]: event.target.value })} /></label>)}</div>
        <label className="block text-sm">并行单位<input required className={field} type="number" min="0.00000001" max="1000" step="any" disabled={busy || item.original.state === "proposed"} value={item.units} onChange={event => update(index, { units: event.target.value })} /></label>
        <label className="block text-sm">占用方式<select className={field} disabled={busy || item.original.state === "proposed"} value={item.occupancy} onChange={event => update(index, { occupancy: event.target.value })}><option value="working_only">工作时段占用</option><option value="through_waiting">整个窗口持续占用</option></select></label>
        <label className="block text-sm">本项目的时间、质量、费用影响及后续处置<textarea required className={field} maxLength={2048} disabled={busy} value={item.impact} onChange={event => update(index, { impact: event.target.value })} /></label>
      </div>)}
      <Button type="submit" size="sm" disabled={busy || selected.length < 2 || !selected.some(item => item.original.project_id === projectId)}>预览整批调整后的容量</Button>
    </form>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {saved && <p role="status" className="text-sm text-primary">调整方案已保存，回执 {saved}。可刷新调整记录继续办理。</p>}
    {preview && <div className="space-y-2 rounded-md border p-3"><p className="text-sm font-medium">{preview.result.snapshot.capacity_clear ? "调整后容量条件就绪，业务执行条件在应用时再次核对" : "仍有容量冲突或缺项，可保存供各方查看，暂不能同意或应用"}</p>{preview.result.snapshot.projects.map(project => <div key={project.id}><p className="text-sm">{project.name} · 项目确认人 {project.owner_name}</p><Changes items={preview.result.snapshot.items.filter(item => item.project_id === project.id)}/></div>)}<Issues values={[...preview.result.snapshot.conflicts, ...preview.result.snapshot.unknown]}/><label className="flex gap-2 text-xs"><input type="checkbox" disabled={busy} checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />已核对此版本，提交各受影响项目具名确认</label><Button type="button" size="sm" disabled={busy || !confirmed} onClick={() => void submit()}>保存调整方案</Button></div>}
  </details>;
}
