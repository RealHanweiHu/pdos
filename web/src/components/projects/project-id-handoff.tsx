"use client";

import Link from "next/link";
import { IdHandoffReceiverRenewal } from "./id-handoff-receiver-renewal";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";

type Person = { id: string; display_name: string };
type Target = { node_id: string; title: string; discipline: string; owner_user_id: string | null; receiver_user_id: string | null; expected_output: string; completion_criteria: string; target_digest: string; baseline_version: number };
type Residual = { description: string; owner_user_id: string; due_at: string };
type DraftItem = { item_key: string; title: string; criteria: string; document_id: string; residuals: Residual[] };
type Item = DraftItem & { id: string; handoff_id: string; artifact_snapshot: { filename: string } };
type Handoff = { replacement_handoff_id: string | null; id: string; freeze_id: string; version: number; target_node_id: string; receiver_user_id: string; previous_handoff_id: string | null; payload_digest: string; status: "submitted" | "accepted" | "returned"; current: boolean; basis_reason?: string | null; superseded: boolean; reason: string; created_at: string; snapshot: { receiver_renewal?: { previous_receiver_name: string; receiver_name: string; actor_name: string; reason: string }; items: (DraftItem & { artifact_snapshot: { filename: string } })[]; target: Target; revision: { id: string; version: number } } };
type Data = { active_freeze_ids:string[]; reacceptance_requirements:{id:string;freeze_id:string;target_node_id:string;snapshot:{current:{title:string}}}[]; targets: Target[]; handoffs: Handoff[]; items: Item[]; responses: { id: string; item_id: string; action: string; reason: string; created_at: string }[]; can_submit: boolean; can_respond: boolean };
type Props = { focusHandoffId?: string; onChanged?: () => void; projectId: string; freezeId: string; people: Person[]; artifacts: { id: string; kind: string; filename: string }[]; currentUserId: string; canManage: boolean; ownerUserId: string };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const statusNames = { submitted: "待逐项接收", accepted: "全部已接收", returned: "已退回补齐" };
function blankItem(): DraftItem { return { item_key: crypto.randomUUID(), title: "", criteria: "", document_id: "", residuals: [] }; }

export function ProjectIdHandoff({ projectId, freezeId, people, artifacts, currentUserId, canManage, ownerUserId, focusHandoffId, onChanged }: Props) {
  const [data, setData] = useState<Data | null>(null); const [targetId, setTargetId] = useState(""); const [receiver, setReceiver] = useState("");
  const [items, setItems] = useState<DraftItem[]>([]); const [reason, setReason] = useState(""); const [notes, setNotes] = useState<Record<string,string>>({});
  const [renewalLock, setRenewalLock] = useState<string | null>(null), [renewedId, setRenewedId] = useState<string | null>(null);
  const [editingOpen,setEditingOpen]=useState(false);
  const [previous, setPrevious] = useState<string | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null); const [notice, setNotice] = useState<string | null>(null);
  const ids = useRef(new Map<string,string>()); const path = `projects/${projectId}/execution/id-design/handoffs`;
  useEffect(() => { let live = true; caseLinkRequest<Data>(path).then((value) => { if (live) setData(value); }).catch((error: unknown) => { if (live) setError(error instanceof Error ? error.message : "交接记录读取失败"); }); return () => { live = false; }; }, [path]);
  const target = data?.targets.find((row) => row.node_id === targetId);
  const handoffs = data?.handoffs.filter((row) => row.freeze_id === freezeId && (!focusHandoffId || row.id === focusHandoffId)) ?? [];
  const canSubmit = data?.active_freeze_ids.includes(freezeId) && data?.can_submit && (canManage || ownerUserId === currentUserId);
  const person = (id: string) => people.find((row) => row.id === id)?.display_name ?? "原责任人";
  function changeItem(index: number, change: Partial<DraftItem>) { setItems(items.map((item,i) => i === index ? { ...item, ...change } : item)); }
  async function send(endpoint: string, body: object, message: string): Promise<boolean> {
    const key = JSON.stringify({ endpoint, body }); let id=ids.current.get(key); if (!id) { id=crypto.randomUUID(); ids.current.set(key,id); }
    setBusy(true); setError(null); setNotice(null);
    try { await caseLinkRequest(endpoint, { ...body, request_id:id }); setData(await caseLinkRequest<Data>(path)); setNotice(message); onChanged?.(); return true; }
    catch(error) { setError(error instanceof Error ? error.message : "交接办理失败"); return false; }
    finally { setBusy(false); }
  }
  function resubmit(handoff: Handoff) {
    setEditingOpen(true);
    setTargetId(handoff.target_node_id); setReceiver(handoff.receiver_user_id); setPrevious(handoff.id); setReason("");
    setItems((data?.items.filter((row) => row.handoff_id === handoff.id) ?? []).map((row) => ({ item_key:row.item_key, title:row.title, criteria:row.criteria, document_id:row.document_id, residuals:row.residuals.map((residual) => ({ ...residual, due_at: "" })) })));
    setNotice("已载入原交接内容；请按当前责任与反馈补齐证据，并重新安排遗留期限后提交新轮次。");
  }
  async function submit() {
    if (!target) return;
    const success = await send(path, { freeze_id:freezeId, target_node_id:target.node_id, expected_target_digest:target.target_digest, receiver_user_id:receiver, expected_previous_handoff_id:previous, reason,
      items:items.map((item) => ({ ...item, residuals:item.residuals.map((row) => ({ ...row, due_at:new Date(row.due_at).toISOString() })) })) }, "交接已提交，等待接收人逐项验收。");
    if(success) { setEditingOpen(false); setItems([]); setTargetId(""); setReceiver(""); setPrevious(null); setReason(""); }
  }
  return <section className="space-y-3 border-t pt-3">
    <p className="text-sm font-medium">下游接口交接</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-sm">{notice}</p>}
    <p className="text-xs text-muted-foreground">交接引用本次冻结设计与下游正式节点。每项明确证据和验收标准；有遗留项时，接收人同时确认其责任和处理期限。</p>
    {renewedId ? <p role="status">新接收轮次已保存，原签名保留。<Link className="text-primary underline" href={`/projects?project=${projectId}&tab=overview&id_handoff=${renewedId}&id_freeze=${freezeId}`}>打开新轮次逐项办理</Link></p> : null}
    {data && !data.active_freeze_ids.includes(freezeId) && <p className="text-xs text-muted-foreground">此冻结版本未启用或已被替代，当前仅查看历史交接。</p>}
    {data?.reacceptance_requirements.filter(row=>row.freeze_id===freezeId&&!handoffs.some(handoff=>handoff.target_node_id===row.target_node_id&&!handoff.superseded)).map(row=><div className="space-y-2 rounded-md border p-2 text-xs" key={row.id}><p>{row.snapshot.current.title}：新版本尚未提交交接。</p>{canSubmit&&<Button type="button" size="sm" variant="outline" onClick={()=>{setEditingOpen(true);setTargetId(row.target_node_id);setReceiver("");setPrevious(null);setItems([blankItem()]);}}>准备此节点新交接</Button>}</div>)}
    {canSubmit && (!focusHandoffId || editingOpen) && <details open={editingOpen} onToggle={event=>setEditingOpen(event.currentTarget.open)}><summary className="cursor-pointer text-sm">{previous ? "补齐并重新提交" : "准备下游交接"}</summary>
      <form className="mt-3 space-y-3" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <label className="block text-sm">下游正式节点<select className={field} required disabled={busy || !!renewalLock || !!previous} value={targetId} onChange={(event) => { setTargetId(event.target.value); setReceiver(""); }}><option value="">选择计划节点</option>{data?.targets.map((row) => <option key={row.node_id} value={row.node_id}>{row.discipline} · {row.title}</option>)}</select></label>
        {target && <p className="text-xs">正式基线 v{target.baseline_version} · 预期输出：{target.expected_output} · 完成标准：{target.completion_criteria}</p>}
        <label className="block text-sm">实际接收人<select className={field} required disabled={busy || !!renewalLock || !target} value={receiver} onChange={(event) => setReceiver(event.target.value)}><option value="">选择下游责任人 / 接收人</option>{people.filter((row) => row.id !== currentUserId && (row.id === target?.owner_user_id || row.id === target?.receiver_user_id)).map((row) => <option key={row.id} value={row.id}>{row.display_name}</option>)}</select></label>
        {target && !people.some((row) => row.id !== currentUserId && [target.owner_user_id,target.receiver_user_id].includes(row.id)) && <p className="text-xs">当前节点没有可独立接收的有效成员，请先在正式计划中确认责任安排。</p>}
        {items.map((item,index) => <fieldset key={item.item_key} className="space-y-2 rounded-md border p-3"><legend className="px-1 text-xs">交付项 {index+1}</legend>
          <label className="block text-xs">交付内容<input className={field} required maxLength={2048} disabled={busy || !!renewalLock} value={item.title} onChange={(event) => changeItem(index,{ title:event.target.value })} /></label>
          <label className="block text-xs">验收标准<textarea className={field} required maxLength={2048} disabled={busy || !!renewalLock} value={item.criteria} onChange={(event) => changeItem(index,{ criteria:event.target.value })} /></label>
          <label className="block text-xs">实际交付文档<select className={field} required disabled={busy || !!renewalLock} value={item.document_id} onChange={(event) => changeItem(index,{ document_id:event.target.value })}><option value="">选择项目文档</option>{artifacts.filter((row) => row.kind === "document").map((row) => <option key={row.id} value={row.id}>{row.filename}</option>)}</select></label>
          {item.residuals.map((residual,rindex) => { const update = (change: Partial<Residual>) => changeItem(index,{ residuals:item.residuals.map((row,i) => i === rindex ? { ...row,...change } : row) }); return <div className="space-y-2 rounded-md border p-2" key={rindex}>
            <label className="block text-xs">遗留内容<textarea className={field} required maxLength={2048} disabled={busy || !!renewalLock} value={residual.description} onChange={(event) => update({ description:event.target.value })} /></label>
            <label className="block text-xs">遗留责任人<select className={field} required disabled={busy || !!renewalLock} value={residual.owner_user_id} onChange={(event) => update({ owner_user_id:event.target.value })}><option value="">选择实际成员</option>{people.map((row) => <option key={row.id} value={row.id}>{row.display_name}</option>)}</select></label>
            <label className="block text-xs">处理期限<input className={field} type="datetime-local" required disabled={busy || !!renewalLock} value={residual.due_at} onChange={(event) => update({ due_at:event.target.value })} /></label>
            <Button type="button" size="sm" variant="ghost" disabled={busy || !!renewalLock} onClick={() => changeItem(index,{ residuals:item.residuals.filter((_,i) => i !== rindex) })}>移除此遗留项</Button>
          </div>; })}
          <div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || !!renewalLock || item.residuals.length>=20} onClick={() => changeItem(index,{ residuals:[...item.residuals,{ description:"",owner_user_id:"",due_at:"" }] })}>添加遗留安排</Button><Button type="button" size="sm" variant="ghost" disabled={busy || !!renewalLock} onClick={() => setItems(items.filter((_,i) => i!==index))}>移除此交付项</Button></div>
        </fieldset>)}
        <Button type="button" size="sm" variant="outline" disabled={busy || !!renewalLock || items.length>=30} onClick={() => setItems([...items,blankItem()])}>添加交付项</Button>
        <label className="block text-sm">交接 / 补齐说明<textarea className={field} required maxLength={2048} disabled={busy || !!renewalLock} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
        <div className="flex gap-2"><Button size="sm" disabled={busy || !!renewalLock || !target || !items.length}>提交交接</Button>{previous && <Button type="button" size="sm" variant="ghost" disabled={busy || !!renewalLock} onClick={() => { setPrevious(null); setTargetId(""); setItems([]); }}>取消补齐</Button>}</div>
      </form>
    </details>}
    {data && focusHandoffId && !handoffs.length ? <p className="text-destructive">原交接不属于所选冻结版本或当前不可读取，请重新打开。</p> : null}
    {handoffs.map((handoff) => <article key={handoff.id} className="space-y-2 border-t pt-3">
      <p className="text-sm font-medium">{handoff.snapshot.target.title} · 交接第 {handoff.version} 轮 · {statusNames[handoff.status]}{handoff.superseded ? "（已有后续轮次）" : ""}</p>
      {handoff.previous_handoff_id ? <Link className="text-primary underline text-xs" href={`/projects?project=${projectId}&tab=overview&id_handoff=${handoff.previous_handoff_id}&id_freeze=${freezeId}`}>回看上一轮交接与原意见</Link> : null}
      {handoff.replacement_handoff_id ? <Link className="text-primary underline text-xs" href={`/projects?project=${projectId}&tab=overview&id_handoff=${handoff.replacement_handoff_id}&id_freeze=${freezeId}`}>打开后续交接轮次</Link> : null}
      {handoff.snapshot.receiver_renewal ? <p className="text-xs">接收责任调整：{handoff.snapshot.receiver_renewal.previous_receiver_name} → {handoff.snapshot.receiver_renewal.receiver_name}；办理人 {handoff.snapshot.receiver_renewal.actor_name} · {handoff.snapshot.receiver_renewal.reason}</p> : null}
      <p className="text-xs">设计 v{handoff.snapshot.revision.version} · 接收人：{person(handoff.receiver_user_id)} · {handoff.reason}</p>
      {!handoff.current && <p className="text-xs text-destructive">{handoff.basis_reason ?? "下游节点或责任已变化，历史接收记录不能代表当前安排。"}</p>}
      {data?.items.filter((row) => row.handoff_id===handoff.id).map((item) => { const response=data.responses.find((row) => row.item_id===item.id); const actionable=handoff.status==='submitted' && !handoff.superseded && !response && data.can_respond && handoff.receiver_user_id===currentUserId; return <div key={item.id} className="space-y-2 rounded-md border p-3 text-xs">
        <p className="font-medium">{item.title}</p><p className="whitespace-pre-wrap">验收标准：{item.criteria}</p><p>交付文档：{item.artifact_snapshot.filename}</p>
        {item.residuals.map((row,index) => <p className="whitespace-pre-wrap" key={index}>遗留：{row.description} · {person(row.owner_user_id)} · {new Date(row.due_at).toLocaleString()}</p>)}
        {response && <p>{response.action==='accept' ? '已接收' : '已退回'}：{response.reason} · {new Date(response.created_at).toLocaleString()}</p>}
        {actionable && <div><label>验收依据 / 缺项说明<textarea className={field} maxLength={2048} disabled={busy || !!renewalLock} value={notes[item.id] ?? ""} onChange={(event) => setNotes({ ...notes,[item.id]:event.target.value })} /></label><div className="mt-2 flex gap-2">{(['accept','return'] as const).map((action) => <Button key={action} type="button" size="sm" variant={action==='accept' ? 'default' : 'outline'} disabled={busy || !!renewalLock || !notes[item.id]?.trim() || (action==='accept' && !handoff.current)} onClick={() => void send(`${path}/items/${item.id}`,{ expected_digest:handoff.payload_digest, action, reason:notes[item.id] },action==='accept' ? '此项已接收。' : '交接已退回，请交付人补齐后重新提交。')}>{action==='accept' ? '验收此项' : '退回补齐'}</Button>)}</div></div>}
      </div>; })}
      {canSubmit && handoff.status === "submitted" && !handoff.superseded ? <IdHandoffReceiverRenewal projectId={projectId} original={handoff} people={people} choices={people.filter(person => person.id !== currentUserId && person.id !== handoff.receiver_user_id && data?.targets.some(target => target.node_id === handoff.target_node_id && [target.owner_user_id, target.receiver_user_id].includes(person.id)))} disabled={busy || (!!renewalLock && renewalLock !== handoff.id)} onLock={locked => setRenewalLock(locked ? handoff.id : null)} onChanged={async id => { setRenewedId(id); setData(await caseLinkRequest<Data>(path)); onChanged?.(); }}/> : null}
      {canSubmit && (handoff.status==='returned' || !handoff.current) && !handoff.superseded && <Button type="button" size="sm" variant="outline" disabled={busy || !!renewalLock} onClick={() => resubmit(handoff)}>{handoff.current ? "按退回意见补齐" : "按当前责任重新交接"}</Button>}
    </article>)}
    <Button type="button" size="sm" variant="ghost" disabled={busy || !!renewalLock} onClick={() => { setBusy(true); caseLinkRequest<Data>(path).then(setData).catch((error: unknown) => setError(error instanceof Error ? error.message : "读取失败")).finally(() => setBusy(false)); }}>刷新交接</Button>
  </section>;
}
