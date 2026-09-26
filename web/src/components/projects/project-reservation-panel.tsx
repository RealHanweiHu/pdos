"use client";

import { PortfolioSelectionInbox } from "@/components/portfolio/portfolio-selections";
import { ResourceReallocations } from "./resource-reallocations";
import { ResourcePriorityPolicy } from "./resource-priority-policy";
import { QualityResponsibility } from "@/components/quality/quality-responsibility";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ProjectScheduleNodes, nodeKinds } from "./project-schedule-nodes";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";

type Reservation = { priority_policy?: { version: number; rank: number; valid_until: string } | null; owner_name: string | null; resource_user_id: string | null; resource_user_name: string | null; resource_id: string; capacity_version_id: string; id: string; resource_name: string; task_id: string | null; node_title: string; node_kind: string; node_id: string; owner_user_id: string; version: number; state: "proposed" | "reserved" | "released" | "cancelled"; window_start: string; window_end: string; parallel_units: string; occupancy_policy: string; basis: string; payload_digest: string; contract: { approval: { approved_by_user_id: string; approved_at: string } | null; release_reason: string | null } };
type Replacement = { id: string; previous_reservation_id: string; replacement_reservation_id: string; created_at: string; reason: string; snapshot: { previous: Pick<Reservation, "id" | "resource_id" | "window_start" | "window_end" | "parallel_units">; replacement: Pick<Reservation, "id" | "resource_id" | "window_start" | "window_end" | "parallel_units"> } };
type State = { nodes: { id: string; task_id: string | null; node_kind: string; title: string }[]; replacements: Replacement[]; items: Reservation[]; has_more: boolean; tasks: { id: string; title: string; status: string }[]; has_more_tasks: boolean; can_propose: boolean; can_reserve: boolean; project_status: string };
type Resource = { id: string; name: string; capacity: { id: string; version: number; parallel_units: string; window_start: string; window_end: string; basis: string } | null };
type Receipt = { id: string; actor_user_id: string; created_at: string; reason: string; snapshot: Reservation };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const labels = { proposed: "待确认提案", reserved: "已预约", released: "已释放", cancelled: "已取消" };

function reservationLocal(value: string) { const date=new Date(value); return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16); }
function ReplacementForm({ item, resources, busy, save }: { item: Reservation; resources: Resource[]; busy: boolean; save: (body: object) => Promise<void> }) {
  const [capacity, setCapacity]=useState(item.capacity_version_id); const [start, setStart]=useState(reservationLocal(item.window_start)); const [end,setEnd]=useState(reservationLocal(item.window_end)); const [units,setUnits]=useState(item.parallel_units); const [occupancy,setOccupancy]=useState(item.occupancy_policy); const [reason,setReason]=useState(""); const [confirmed,setConfirmed]=useState(false);
  const available=resources.filter((resource)=>resource.capacity);
  return <details className="space-y-2 rounded-md border p-3"><summary className="cursor-pointer text-sm">调整此预约的时间、资源或数量</summary><form className="space-y-2" onChange={()=>setConfirmed(false)} onSubmit={(event)=>{event.preventDefault(); void save({ expected_digest:item.payload_digest, capacity_version_id:capacity, window_start:new Date(start).toISOString(), window_end:new Date(end).toISOString(), parallel_units:units, occupancy_policy:occupancy, reason });}}>
    <p className="text-xs text-muted-foreground">保留所属业务节点和预约负责人。旧预约释放与新预约确认同时生效；新预约失败时旧预约仍保留。</p>
    <label className="block text-sm">调整后的资源与容量版本<select className={field} required value={capacity} onChange={(event)=>setCapacity(event.target.value)}>{!available.some((resource)=>resource.capacity?.id===capacity) && <option value={capacity}>原容量已有新版本，请重新选择</option>}{available.map((resource)=><option key={resource.id} value={resource.capacity!.id}>{resource.name} · v{resource.capacity!.version}</option>)}</select></label>
    <div className="grid gap-2 sm:grid-cols-2"><label className="text-sm">开始（本地时间）<input className={field} type="datetime-local" required value={start} onChange={(event)=>setStart(event.target.value)} /></label><label className="text-sm">结束（本地时间）<input className={field} type="datetime-local" required value={end} onChange={(event)=>setEnd(event.target.value)} /></label></div>
    <label className="block text-sm">调整后的并行单位<input className={field} type="number" min="0.00000001" max="1000" step="any" required value={units} onChange={(event)=>setUnits(event.target.value)} /></label>
    <label className="block text-sm">占用方式<select className={field} value={occupancy} onChange={(event)=>setOccupancy(event.target.value)}><option value="working_only">资源日历的工作时段</option><option value="through_waiting">全窗口持续占用</option></select></label>
    <label className="block text-sm">调整原因<textarea className={field} required maxLength={2048} value={reason} onChange={(event)=>setReason(event.target.value)} /></label>
    <label className="flex gap-2 text-sm"><input type="checkbox" checked={confirmed} onChange={(event)=>{event.stopPropagation();setConfirmed(event.target.checked);}} />已核对调整前后内容，确认替换此预约</label><Button type="submit" size="sm" disabled={busy || !confirmed || !available.some((resource)=>resource.capacity?.id===capacity)}>同时释放旧预约并确认新预约</Button>
  </form></details>;
}

export function ProjectReservationPanel({ projectId, userId }: { projectId: string; userId: string }) {
  const params = useSearchParams();
  const value = params.get("resource_reservation_id");
  const node = params.get("reservation_node_id");
  const resource = params.get("reservation_resource_id");
  const proposalNode = node && /^[0-9a-f-]{36}$/i.test(node) ? node : undefined;
  const proposalResource = resource && /^[0-9a-f-]{36}$/i.test(resource) ? resource : undefined;
  const targetId = value && /^[0-9a-f-]{36}$/i.test(value) ? value : undefined;
  return <ReservationPanel key={`${projectId}:${targetId ?? "all"}:${proposalNode ?? ""}:${proposalResource ?? ""}`} projectId={projectId} userId={userId} targetId={targetId} proposalNode={proposalNode} proposalResource={proposalResource}/>;
}
function ReservationPanel({ projectId, userId, targetId, proposalNode, proposalResource }: { projectId: string; userId: string; targetId?: string; proposalNode?: string; proposalResource?: string }) {
  const [open, setOpen] = useState(!!targetId || !!proposalNode);
  const [proposalOpen, setProposalOpen] = useState(!!proposalNode);
  const [data, setData] = useState<State | null>(null);
  const [resources, setResources] = useState<Resource[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [task, setTask] = useState(proposalNode ? `node:${proposalNode}` : "");
  const [capacity, setCapacity] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [units, setUnits] = useState("");
  const [policy, setPolicy] = useState("working_only");
  const [basis, setBasis] = useState("");
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [history, setHistory] = useState<Record<string, Receipt[]>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [ownerLock, setOwnerLock] = useState<string | null>(null);
  const ids = useRef(new Map<string, string>());
  const base = `projects/${projectId}/resource-reservations`;
  const listPath = `${base}${targetId ? `?target_id=${encodeURIComponent(targetId)}` : ""}`;
  useEffect(() => {
    if (!targetId && !proposalNode) return;
    let active = true;
    void Promise.all([caseLinkRequest<State>(listPath), caseLinkRequest<{ items: Resource[] }>("planning/resources")]).then(([state, choices]) => { if (active) { setData(state); setResources(choices.items); if (proposalNode) { const capacity = choices.items.find(item => item.id === proposalResource)?.capacity; setCapacity(capacity?.id ?? ""); if (!state.nodes.some(item => item.id === proposalNode)) { setTask(""); setError("链接中的业务节点当前不可预约，请核对状态或重新选择。"); } else if (!capacity) setError("关联资源尚无可选容量，请核对资源配置后重试。"); } } }).catch(failure => { if (active) setError(failure instanceof Error ? failure.message : "原预约暂不可用"); });
    return () => { active = false; };
  }, [listPath, targetId, proposalNode, proposalResource]);
  async function load() {
    const [state, choices] = await Promise.all([caseLinkRequest<State>(listPath), caseLinkRequest<{ items: Resource[] }>("planning/resources")]);
    setData(state); setResources(choices.items);
  }
  async function refresh() { setBusy(true); setError(null); try { await load(); } catch (failure) { setError(failure instanceof Error ? failure.message : "预约暂不可用"); } finally { setBusy(false); } }
  async function send(path: string, body: object) {
    setBusy(true); setError(null); setNotice(null);
    const key = JSON.stringify({ path, body });
    let id = ids.current.get(key); if (!id) { id = crypto.randomUUID(); ids.current.set(key, id); }
    try { await caseLinkRequest(path, { ...body, request_id: id }); await load(); setHistory({}); setNotice("预约操作已保存。"); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "预约操作未完成"); }
    finally { setBusy(false); }
  }
  async function readHistory(id: string) { setBusy(true); setError(null); try { const result = await caseLinkRequest<{ items: Receipt[] }>(`${base}/${id}`); setHistory({ ...history, [id]: result.items }); } catch (failure) { setError(failure instanceof Error ? failure.message : "历史暂不可用"); } finally { setBusy(false); } }
  const selected = resources.find((resource) => resource.capacity?.id === capacity);
  return <section id="resource-reservations" className="mt-6 space-y-3 rounded-lg border p-4">
    <ResourceReallocations projectId={projectId} onChanged={load} />
    <PortfolioSelectionInbox key={projectId} projectId={projectId} />
    <Button type="button" size="sm" variant="outline" disabled={busy || !!ownerLock} onClick={() => { setOpen(!open); if (!open) void refresh(); }}>{open ? "收起项目资源预约" : "项目资源预约"}</Button>
    {open && <div className="space-y-3">
      {error && <p className="text-sm text-destructive" role="alert">{error}</p>}{notice && <p className="text-sm" role="status">{notice}</p>}
      <p className="text-xs text-muted-foreground">提案不占用容量。项目批准执行后，由资源管理员独立确认，按固定政策的项目级别及提案顺序检查实际区间容量；不会抢占其他预约。正式预约可同事务替换资源、窗口或数量；提案调整时取消原提案后重新提出。</p>
      {targetId && <p className="text-sm">当前为移交清单指定的原预约。<a className="text-primary underline" href={`/projects?project=${projectId}&tab=overview`}>查看本项目全部预约</a></p>}
      {data?.can_reserve&&<details className="space-y-2"><summary className="cursor-pointer text-sm">资源管理员：配置优先级政策</summary>{resources.map(r=><ResourcePriorityPolicy key={r.id} resourceId={r.id} resourceName={r.name}/>)}</details>}
      <ProjectScheduleNodes projectId={projectId} onRegistered={() => void refresh()} />
      {data?.can_propose && <details open={proposalOpen} onToggle={event => setProposalOpen(event.currentTarget.open)} className="space-y-3"><summary className="cursor-pointer text-sm font-medium">提出业务资源预约</summary><form className="space-y-3" onSubmit={(event) => { event.preventDefault(); void send(base, { ...(task.startsWith("node:") ? { node_id: task.slice(5) } : { task_id: task }), capacity_version_id: capacity, window_start: new Date(start).toISOString(), window_end: new Date(end).toISOString(), parallel_units: units, occupancy_policy: policy, basis }); }}>
        <label className="block text-sm">实际任务或已登记的业务节点<select required className={field} value={task} onChange={(event) => setTask(event.target.value)}><option value="">选择预约对象</option>{data.nodes.map((item) => <option value={`node:${item.id}`} key={item.id}>{nodeKinds[item.node_kind]} · {item.title}</option>)}{data.tasks.filter((item) => !data.nodes.some((node) => node.task_id === item.id)).map((item) => <option value={item.id} key={item.id}>任务 · {item.title}</option>)}</select></label>
        {data.has_more_tasks && <p className="text-xs">当前列出前 1000 个未结束任务。</p>}
        <label className="block text-sm">共享资源及容量版本<select required className={field} value={capacity} onChange={(event) => setCapacity(event.target.value)}><option value="">选择已配置资源</option>{resources.filter((resource) => resource.capacity).map((resource) => <option key={resource.id} value={resource.capacity!.id}>{resource.name} · 容量 v{resource.capacity!.version}</option>)}</select></label>
        {selected?.capacity && <p className="text-xs text-muted-foreground">声明容量 {selected.capacity.parallel_units} 单位 · {new Date(selected.capacity.window_start).toLocaleString()} — {new Date(selected.capacity.window_end).toLocaleString()}<br />{selected.capacity.basis}</p>}
        <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">开始（浏览器时区）<input required type="datetime-local" className={field} value={start} onChange={(event) => setStart(event.target.value)} /></label><label className="text-sm">结束（浏览器时区）<input required type="datetime-local" className={field} value={end} onChange={(event) => setEnd(event.target.value)} /></label></div>
        <label className="block text-sm">占用并行单位<input required type="number" min="0.00000001" max="1000" step="any" className={field} value={units} onChange={(event) => setUnits(event.target.value)} /></label>
        <label className="block text-sm">占用方式<select className={field} value={policy} onChange={(event) => setPolicy(event.target.value)}><option value="working_only">窗口内资源日历的工作时段</option><option value="through_waiting">整个窗口持续占用（含等待及非工作时段）</option></select></label>
        <label className="block text-sm">预约依据<textarea required maxLength={2048} className={field} value={basis} onChange={(event) => setBasis(event.target.value)} /></label>
        <Button type="submit" size="sm" disabled={busy || !!ownerLock || !task || !capacity}>保存预约提案</Button>
      </form></details>}
      {data?.items.map((item) => <article id={`reservation-${item.id}`} className="space-y-2 rounded-md border p-3" key={item.id}>
        <QualityResponsibility projectId={projectId} kind="reservation" recordId={item.id} disabled={busy || !!ownerLock && ownerLock !== item.id} onLock={value => setOwnerLock(value ? item.id : null)} onChanged={() => load()}/>
        <p className="text-sm">预约办理负责人：{item.owner_name ?? "原人员"}{item.resource_user_id && <><br/>实际占用人员：{item.resource_user_name ?? "原人员"}（调整预约负责人不会改变此人员）</>}</p>
        {item.priority_policy?<p className="text-xs">采用政策 v{item.priority_policy.version} · 本项目级别 {item.priority_policy.rank} · 有效至 {new Date(item.priority_policy.valid_until).toLocaleString()}；确认时复核当前版本。</p>:<p className="text-xs">历史固定规则；旧待确认提案须按当前优先级政策重提。已确认预约保留。</p>}<p className="text-sm font-medium">{item.resource_name} · {labels[item.state]} · v{item.version}</p>
        <p className="text-sm">{item.node_title ?? data.tasks.find((value) => value.id === item.task_id)?.title ?? "项目排程节点"} · {item.parallel_units} 单位 · {item.occupancy_policy === "working_only" ? "资源工作时段" : "全窗口持续占用"}</p>
        <p className="text-xs">{new Date(item.window_start).toLocaleString()} — {new Date(item.window_end).toLocaleString()}</p><p className="whitespace-pre-wrap text-xs text-muted-foreground">{item.basis}</p>
        {item.contract.approval && <p className="text-xs">确认时间：{new Date(item.contract.approval.approved_at).toLocaleString()}</p>}{item.contract.release_reason && <p className="text-xs">释放/取消原因：{item.contract.release_reason}</p>}
        {(item.state === "proposed" || item.state === "reserved") && (data.can_reserve || item.owner_user_id === userId) && <><label className="block text-sm">办理说明<input className={field} maxLength={2048} value={reasons[item.id] ?? ""} onChange={(event) => setReasons({ ...reasons, [item.id]: event.target.value })} /></label><div className="flex flex-wrap gap-2">
          {item.state === "proposed" && data.can_reserve && <Button type="button" size="sm" disabled={busy || !!ownerLock || !reasons[item.id]?.trim() || !["approved", "active"].includes(data.project_status)} onClick={() => void send(`${base}/${item.id}`, { action: "reserve", expected_digest: item.payload_digest, reason: reasons[item.id] })}>确认并占用容量</Button>}
          {item.state === "reserved" && <Button type="button" size="sm" variant="outline" disabled={busy || !!ownerLock || !reasons[item.id]?.trim()} onClick={() => void send(`${base}/${item.id}`, { action: "release", expected_digest: item.payload_digest, reason: reasons[item.id] })}>释放容量</Button>}
          <Button type="button" size="sm" variant="ghost" disabled={busy || !!ownerLock || !reasons[item.id]?.trim()} onClick={() => void send(`${base}/${item.id}`, { action: "cancel", expected_digest: item.payload_digest, reason: reasons[item.id] })}>取消预约</Button>
        </div></>}
        {data.can_propose && (item.state === "proposed" || item.state === "cancelled") && <Button size="sm" type="button" variant="outline" disabled={busy || !!ownerLock} onClick={() => { setTask(`node:${item.node_id}`); setCapacity(""); setStart(reservationLocal(item.window_start)); setEnd(reservationLocal(item.window_end)); setUnits(item.parallel_units); setPolicy(item.occupancy_policy); setBasis(item.basis); setProposalOpen(true); }}>载入原节点和时段，选择新资源提案</Button>}
        {item.state === "reserved" && data.can_reserve && ["approved", "active"].includes(data.project_status) && <ReplacementForm item={item} resources={resources} busy={busy || !!ownerLock} save={(body)=>send(`${base}/${item.id}/replacement`,body)} />}
        {data.replacements.filter((replacement)=>replacement.previous_reservation_id===item.id || replacement.replacement_reservation_id===item.id).map((replacement)=><details key={replacement.id} className="rounded-md border p-2 text-xs"><summary className="cursor-pointer">{replacement.previous_reservation_id===item.id ? "已调整为新预约" : "由原预约调整而来"} · {new Date(replacement.created_at).toLocaleString()}</summary><p>{replacement.reason}</p>{(["previous", "replacement"] as const).map((kind)=>{const record=replacement.snapshot[kind];return <div key={kind} className="my-2"><p className="font-medium">{kind==="previous" ? "调整前" : "调整后"} · {resources.find((resource)=>resource.id===record.resource_id)?.name ?? "原资源"} · {record.parallel_units} 单位</p><p>{new Date(record.window_start).toLocaleString()} — {new Date(record.window_end).toLocaleString()}</p><a className="text-primary underline" href={`/projects?project=${projectId}&tab=overview&resource_reservation_id=${record.id}`}>打开{kind === "previous" ? "原" : "新"}预约</a></div>;})}</details>)}
        <Button type="button" size="sm" variant="ghost" disabled={busy || !!ownerLock} onClick={() => void readHistory(item.id)}>查看办理历史</Button>
        {history[item.id]?.map((receipt) => <p className="border-t pt-2 text-xs" key={receipt.id}>{new Date(receipt.created_at).toLocaleString()} · {labels[receipt.snapshot.state]} · {receipt.reason}</p>)}
      </article>)}
      {data?.has_more && <p className="text-xs">显示最近 200 条预约。</p>}
      <Button type="button" size="sm" variant="ghost" disabled={busy || !!ownerLock} onClick={() => void refresh()}>刷新资源与预约</Button>
    </div>}
  </section>;
}
