"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Binding = { id: string; version: number; mode: string; target_point: string; node_ids: string[]; ready_at: string | null; created_at: string; created_by_user_id: string; reason: string; snapshot: Record<string, unknown> };
type State = { nodes: { id: string; node_key: string; title: string | null; node_kind: string }[]; history: Binding[]; selected?: Binding | null; current: { source_digest: string; review_current: boolean; latest_review: { id: string; version: number; disposition: string }; supply_ready: boolean; material: { required: string; unit: string; allocated_on_hand: string } | null }; baseline_id: string | null };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const modes: Record<string, string> = { waiting: "可用时间未知", estimate: "采用明确预计可用时间", released: "解除本异常的全部排程影响" };
const localValue = (value: string | null) => { if (!value) return ""; const date = new Date(value); const pad = (number: number) => String(number).padStart(2, "0"); return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`; };
async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "排程影响暂不可用，请核对当前权限和原记录");
  return value as T;
}
export function MaterialScheduleBinding({ projectId, exceptionId, canEdit }: { projectId: string; exceptionId: string; canEdit: boolean }) {
  const [data, setData] = useState<State | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState("waiting"), [point, setPoint] = useState("start"), [nodes, setNodes] = useState<string[]>([]), [ready, setReady] = useState("");
  const [reason, setReason] = useState(""), [checked, setChecked] = useState(false), [notice, setNotice] = useState<string | null>(null), [version, setVersion] = useState("");
  const ids = useRef(new Map<string, string>());
  const path = `/api/projects/${projectId}/npi/material-exceptions/${exceptionId}/schedule`;
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "操作未完成"); } finally { setBusy(false); } }
  async function load() { const value = await request<State>(path); setData(value); setChecked(false); const latest = value.history[0]; if (latest) { setMode(latest.mode); setPoint(latest.target_point); setNodes(latest.node_ids); setReady(localValue(latest.ready_at)); } }
  async function save() {
    if (!data || !checked) return;
    if (mode === "estimate" && (!ready || Number.isNaN(new Date(ready).getTime()))) throw new Error("请填写明确的预计可用时间");
    const body = { expected_version: data.history[0]?.version ?? 0, review_id: data.current.latest_review.id, source_digest: data.current.source_digest, mode, target_point: point, node_ids: mode === "released" ? [] : nodes, ready_at: mode === "estimate" ? new Date(ready).toISOString() : null, reason };
    const signature = JSON.stringify(body); let requestId = ids.current.get(signature); if (!requestId) { requestId = crypto.randomUUID(); ids.current.set(signature, requestId); }
    setNotice(`请求 ${requestId}；相同输入重试复用原记录。`);
    await request<Binding>(path, { ...body, request_id: requestId }); setNotice("排程影响已保存。请回正式排程重新计算预测；旧预测会保留并提示依据变化。"); setReason(""); await load();
  }
  return <details className="rounded-md border p-3" onToggle={event => { if (event.currentTarget.open && !data && !busy) void act(load); }}><summary className="cursor-pointer text-sm font-medium">本异常对正式节点的预测影响</summary><div className="mt-2 space-y-3"><p className="text-xs">仅改变预测所用条件。未知供给使所选节点及其后续预测待定；明确预计时间用于开始或剩余工作恢复下限。已发生的实际记录保持不变，Gate准入和正式承诺沿原流程办理。</p><Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>读取当前核对与正式节点</Button>{error && <p role="alert" className="text-xs text-destructive">{error}</p>}{notice && <p role="status" className="break-all text-xs">{notice}</p>}
    {data && <><p className="text-xs">当前物料核对 v{data.current.latest_review.version} · {data.current.review_current ? "供给依据一致" : "来源已变化，先在原异常追加具名核对"}{data.current.supply_ready && " · 合格现货已具名核对齐备"}</p>{!data.baseline_id && <p className="text-xs">尚无完整正式计划；先完善计划后选择实际节点。</p>}
      {canEdit && <fieldset disabled={busy} className="space-y-3"><label className="block text-xs">处理方式<select className={field} value={mode} onChange={event => { setMode(event.target.value); setChecked(false); }}>{Object.entries(modes).map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></label>
      {mode !== "released" && <><label className="block text-xs">物料在哪一步需要<select className={field} value={point} onChange={event => { setPoint(event.target.value); setChecked(false); }}><option value="start">节点开始前</option><option value="remaining">剩余工作恢复前</option></select></label><p className="text-xs">“开始前”不改已经发生的开始事实；在途工作需等待物料时，明确选“剩余工作恢复前”。</p><div className="max-h-72 space-y-2 overflow-auto rounded-md border p-2">{data.nodes.map(node => <label className="block text-xs" key={node.id}><input type="checkbox" checked={nodes.includes(node.id)} onChange={event => { setNodes(event.target.checked ? [...nodes, node.id] : nodes.filter(id => id !== node.id)); setChecked(false); }}/> {node.node_key} · {node.title ?? node.node_kind}</label>)}{nodes.filter(id => !data.nodes.some(node => node.id === id)).map(id => <label key={id} className="block text-xs text-destructive"><input type="checkbox" checked onChange={() => { setNodes(nodes.filter(value => value !== id)); setChecked(false); }}/> {id} 已不在当前正式计划，请取消选择后重新明确范围</label>)}</div></>}
      {mode === "estimate" && <label className="block text-xs">预计可用时间（本机时区 {Intl.DateTimeFormat().resolvedOptions().timeZone}）<input className={field} type="datetime-local" value={ready} onChange={event => { setReady(event.target.value); setChecked(false); }}/><span>请根据实际联系记录、供给与质量条件核对；这是一条预测假设，不会登记为正式供应承诺。</span></label>}
      {mode === "released" && <p className="text-xs">本次解除该异常原版本列出的全部节点影响；原版本和原问题保留。</p>}
      <label className="block text-xs">影响范围、预计依据或解除原因<textarea className={field} maxLength={2048} value={reason} onChange={event => { setReason(event.target.value); setChecked(false); }}/></label><label className="block text-xs"><input type="checkbox" checked={checked} onChange={event => setChecked(event.target.checked)}/> 已核对本异常最新具名记录、所选节点及时间口径</label><Button size="sm" disabled={!checked || !reason.trim() || !data.current.review_current || (mode !== "released" && (!nodes.length || nodes.length > 100)) || (mode === "released" && !data.history.length)} onClick={() => void act(save)}>保存独立预测影响版本</Button></fieldset>}
      <a className="text-xs text-primary underline" href={`/projects?project=${projectId}&tab=overview#schedule-forecasts`}>到正式排程重新计算预测并核对后续影响</a>
      <details><summary className="cursor-pointer text-xs">最近20次影响版本及指定历史</summary>{data.history.map(row => <details className="mt-2 rounded-md border p-2" key={row.id}><summary className="cursor-pointer text-xs">v{row.version} · {modes[row.mode]} · {row.target_point === "start" ? "开始前" : "剩余工作恢复前"} · {row.node_ids.length} 个节点</summary><p className="text-xs">{new Date(row.created_at).toLocaleString()} · {row.created_by_user_id} · {row.reason}</p><p className="text-xs">预计时间 {row.ready_at ? new Date(row.ready_at).toLocaleString() : "无"}</p><pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(row.snapshot, null, 2)}</pre></details>)}<label className="block text-xs">指定历史版本<input className={field} inputMode="numeric" value={version} onChange={event => setVersion(event.target.value)}/></label><Button size="sm" variant="outline" disabled={busy || !/^[1-9]\d*$/.test(version)} onClick={() => void act(async () => { const value = await request<State>(`${path}?version=${version}`); setData({ ...data, selected: value.selected }); })}>读取历史版本</Button>{data.selected && <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(data.selected, null, 2)}</pre>}</details>
    </>}
  </div></details>;
}
