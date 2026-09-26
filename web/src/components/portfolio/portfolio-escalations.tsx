"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";

const states: Record<string, string> = { pending: "待接手", accept: "已接手", update: "跟进中", return: "已退回", close: "本次跟进已结束", withdraw: "已撤回" };
const actions: Record<string, string> = { accept: "接手", update: "记录进展", return: "退回", close: "结束本次跟进", withdraw: "撤回" };
const terminal = ["return", "close", "withdraw"];
function message(error: unknown) { return error instanceof Error ? error.message : "办理未完成，请核对后重试"; }

export function EscalationForm({ source, onSaved, onCancel }: { source: Row; onSaved: () => void; onCancel: () => void }) {
  const [people, setPeople] = useState<Row[]>([]), [recipient, setRecipient] = useState(""), [due, setDue] = useState("");
  const [reason, setReason] = useState(""), [outcome, setOutcome] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [preview, setPreview] = useState<Row | null>(null), [previewSignature, setPreviewSignature] = useState(""), [confirmed, setConfirmed] = useState(false);
  const nonce = useRef<{ signature: string; id: string } | null>(null);
  const sourceBody = { project_id: source.project_id, source_kind: source.kind, source_id: source.id, expected_source_digest: source.source_digest };
  const draft = { ...sourceBody, recipient_user_id: recipient, due_date: due, reason, requested_outcome: outcome };
  const signature = JSON.stringify(draft), fresh = signature === previewSignature;
  const sourceSignature = JSON.stringify(sourceBody);
  useEffect(() => {
    let current = true;
    caseLinkRequest<Row>("planning/portfolio-escalation-options", JSON.parse(sourceSignature)).then(value => { if (current) setPeople(rows(value.people)); }).catch(e => { if (current) setError(message(e)); });
    return () => { current = false; };
  }, [sourceSignature]);
  async function prepare() {
    setBusy(true); setError(""); setConfirmed(false); setPreview(null);
    try { const value = await caseLinkRequest<Row>("planning/portfolio-escalation-preview", draft); setPreview(value); setPreviewSignature(signature); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function save() {
    if (!preview || !fresh || !confirmed) return;
    const body = { ...draft, expected_preview_digest: preview.preview_digest }, key = JSON.stringify(body);
    if (nonce.current?.signature !== key) nonce.current = { signature: key, id: crypto.randomUUID() };
    setBusy(true); setError("");
    try { await caseLinkRequest("planning/portfolio-escalation-requests", { ...body, request_id: nonce.current.id }); nonce.current = null; onSaved(); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  return <form className="space-y-3 rounded-lg border border-primary/30 p-4" onSubmit={e => { e.preventDefault(); void prepare(); }}>
    <h3 className="font-medium">升级跟进 · {text(source.title)}</h3>
    <p className="text-xs text-muted-foreground">请指定本项目内部负责人。预览时会核对接收人的原事项读取权限；发起跟进不增加资料权限，也不代替原批准和执行。</p>
    <fieldset disabled={busy} className="grid gap-3 sm:grid-cols-2">
      <label className="text-sm">接收人<select required className={field} value={recipient} onChange={e => setRecipient(e.target.value)}><option value="">请选择负责人</option>{people.map(p => <option key={text(p.id)} value={text(p.id)}>{text(p.display_name)}</option>)}</select></label>
      <label className="text-sm">跟进期限<input required type="date" className={field} value={due} onChange={e => setDue(e.target.value)} /></label>
      <label className="text-sm">升级原因<textarea required maxLength={4000} className={field} value={reason} onChange={e => setReason(e.target.value)} /></label>
      <label className="text-sm">希望协调的具体结果<textarea required maxLength={4000} className={field} value={outcome} onChange={e => setOutcome(e.target.value)} /></label>
    </fieldset>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <div className="flex gap-2"><Button size="sm" type="submit" disabled={busy}>核对并预览</Button><Button size="sm" variant="outline" type="button" disabled={busy} onClick={onCancel}>取消</Button></div>
    {preview && <div className="space-y-2 rounded-md bg-muted/40 p-3 text-sm"><p>{text(preview.label)}：{text(obj(preview.source).title)}</p><p>交给 {text(obj(preview.recipient).display_name)}，期限 {text(obj(preview.command).due_date)}</p><p className="whitespace-pre-wrap">原因：{text(obj(preview.command).reason)}</p><p className="whitespace-pre-wrap">期望结果：{text(obj(preview.command).requested_outcome)}</p><a className="text-primary underline" href={text(preview.href)}>核对原事项</a>{!fresh && <p>内容已修改，请重新预览。</p>}<label className="flex gap-2"><input type="checkbox" checked={confirmed && fresh} disabled={!fresh || busy} onChange={e => setConfirmed(e.target.checked)} />确认以上负责人、期限和跟进内容</label><Button type="button" size="sm" disabled={busy || !fresh || !confirmed} onClick={() => void save()}>保存升级跟进</Button></div>}
  </form>;
}

function EscalationRecord({ item, canReply, onSaved }: { item: Row; canReply: boolean; onSaved: () => void }) {
  const state = text(item.state), snapshot = obj(item.snapshot), source = obj(snapshot.source);
  const allowed = !canReply || terminal.includes(state) ? [] : [
    ...(item.is_recipient === true ? [
      ...(item.source_available === true && item.source_pending === true && state === "pending" ? ["accept"] : []),
      ...(item.source_available === true && ["accept", "update"].includes(state) ? [...(item.source_pending === true ? ["update"] : []), "close"] : []), "return",
    ] : []), ...(item.is_sender === true ? ["withdraw"] : []),
  ];
  const [action, setAction] = useState(""), [note, setNote] = useState(""), [evidence, setEvidence] = useState(""), [due, setDue] = useState(text(item.current_due_date));
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [history, setHistory] = useState<Row | null>(null);
  const nonce = useRef<{ signature: string; id: string } | null>(null);
  async function reply() {
    if (!allowed.includes(action)) return;
    const body = { escalation_id: item.id, expected_version: item.reply_version, action, note, evidence: action === "close" ? evidence : null, due_date: ["accept", "update"].includes(action) ? due : null };
    const signature = JSON.stringify(body);
    if (nonce.current?.signature !== signature) nonce.current = { signature, id: crypto.randomUUID() };
    setBusy(true); setError("");
    try { await caseLinkRequest("planning/portfolio-escalation-replies", { ...body, request_id: nonce.current.id }); nonce.current = null; setAction(""); setNote(""); setEvidence(""); setHistory(null); onSaved(); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function readHistory(more = false) {
    setBusy(true); setError("");
    try { const value = await caseLinkRequest<Row>("planning/portfolio-escalation-history", { escalation_id: item.id, before_version: more ? history?.next_before_version : null }); setHistory(old => more ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  return <article className="space-y-3 rounded-md border p-3">
    <div className="flex flex-wrap justify-between gap-2"><h4 className="text-sm font-medium">{text(source.title) || "原事项内容当前不可读取"}</h4><span className={`text-xs ${item.overdue === true ? "text-destructive" : "text-muted-foreground"}`}>{states[state] ?? state}{item.overdue === true ? " · 跟进已逾期" : ""}</span></div>
    <p className="text-xs text-muted-foreground">{text(item.sender_name)} → {text(item.recipient_name)} · 当前期限 {text(item.current_due_date)} · 发起于 {text(item.created_at)}</p>
    {item.source_available === true ? <><p className="whitespace-pre-wrap text-sm">原因：{text(item.reason)}</p><p className="whitespace-pre-wrap text-sm">希望协调：{text(item.requested_outcome)}</p><a className="text-sm text-primary underline" href={text(item.href)}>打开原事项核对并办理</a>{item.source_pending !== true ? <p className="text-xs text-muted-foreground">原事项已不在当前待办队列，具体状态请在原入口核对；不能据此认定已经完成。</p> : item.source_current !== true && <p className="text-xs text-muted-foreground">原事项内容已有变化；以上保留发起时的原因和期望结果，请先核对当前资料。</p>}</> : <p className="text-xs text-muted-foreground">当前原资料权限不足，跟进正文和历史意见已隐藏；仍可按本人身份退回或撤回。</p>}
    {allowed.length > 0 && <form className="space-y-3" onSubmit={e => { e.preventDefault(); void reply(); }}><fieldset className="space-y-3" disabled={busy}><label className="block text-sm">本次办理<select required className={field} value={action} onChange={e => setAction(e.target.value)}><option value="">请选择</option>{allowed.map(a => <option key={a} value={a}>{actions[a]}</option>)}</select></label>{action && <><label className="block text-sm">办理说明<textarea required maxLength={4000} className={field} value={note} onChange={e => setNote(e.target.value)} /></label>{["accept", "update"].includes(action) && <label className="block text-sm">本次明确的跟进期限<input required type="date" className={field} value={due} onChange={e => setDue(e.target.value)} /></label>}{action === "close" && <><label className="block text-sm">实际协调结果及依据<textarea required maxLength={4000} className={field} value={evidence} onChange={e => setEvidence(e.target.value)} /></label><p className="text-xs text-muted-foreground">结束的是本次跟进。原事项的批准、问题关闭和实际执行须在原入口另行办理。</p></>}<Button size="sm" type="submit">保存办理回执</Button></>}</fieldset></form>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void readHistory()}>读取／刷新跟进历史</Button>
    {history && <div className="space-y-2">{rows(history.items).length === 0 && <p className="text-xs">尚无办理回执。</p>}{rows(history.items).map(v => <div key={text(v.id)} className="rounded-md bg-muted/40 p-3 text-xs"><p>第 {text(v.version)} 次 · {actions[text(v.action)] ?? text(v.action)} · {text(v.created_at)}</p><p>办理人编号：{text(v.created_by_user_id)}</p><p className="whitespace-pre-wrap">{text(v.note) || "当前无权读取意见"}</p>{v.evidence != null && <p className="whitespace-pre-wrap">结果依据：{text(v.evidence)}</p>}{v.due_date != null && <p>当次期限：{text(v.due_date)}</p>}</div>)}{history.next_before_version != null && <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void readHistory(true)}>继续读取历史</Button>}</div>}
  </article>;
}

export function EscalationInbox({ refreshKey }: { refreshKey: number }) {
  const [data, setData] = useState<Row | null>(null), [mode, setMode] = useState("all"), [closed, setClosed] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [loaded, setLoaded] = useState("");
  const signature = JSON.stringify({ mode, include_closed: closed }), fresh = signature === loaded;
  const [epoch, setEpoch] = useState(0);
  async function read(more = false) {
    setBusy(true); setError("");
    try { const value = await caseLinkRequest<Row>("planning/portfolio-escalations", { ...JSON.parse(signature), offset: more ? data?.next_offset ?? 0 : 0, revision: more ? data?.revision : null }); setData(old => more ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); setLoaded(signature); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  useEffect(() => {
    if (refreshKey === 0 && epoch === 0) return;
    let current = true;
    caseLinkRequest<Row>("planning/portfolio-escalations", { mode: "all", include_closed: true, offset: 0, revision: null }).then(value => { if (current) { setData(value); setMode("all"); setClosed(true); setLoaded(JSON.stringify({ mode: "all", include_closed: true })); } }).catch(e => { if (current) setError(message(e)); });
    return () => { current = false; };
  }, [refreshKey, epoch]);
  return <div className="space-y-3 border-t pt-4"><h3 className="font-medium">我的升级跟进</h3><p className="text-xs text-muted-foreground">仅显示本人发起或接收且当前有权读取项目的跟进。保存与办理发生在站内，不发送外部消息。</p><form className="flex flex-wrap items-end gap-3" onSubmit={e => { e.preventDefault(); void read(); }}><label className="text-sm">范围<select disabled={busy} className={field} value={mode} onChange={e => setMode(e.target.value)}><option value="all">本人发起和接收</option><option value="sent">本人发起</option><option value="received">本人接收</option></select></label><label className="flex gap-2 text-sm"><input type="checkbox" disabled={busy} checked={closed} onChange={e => setClosed(e.target.checked)} />包含已结束、退回和撤回</label><Button type="submit" size="sm" disabled={busy}>读取／刷新跟进</Button></form>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}{data && <><p className="text-xs text-muted-foreground">本次共 {text(data.total)} 项，读取于 {text(data.as_of)}。{!fresh && "筛选已改变，请重新读取。"}</p>{rows(data.items).length === 0 && <p className="text-sm">本次范围内暂无跟进。</p>}{rows(data.items).map(item => <EscalationRecord key={`${item.id}:${item.reply_version}:${item.source_available}:${item.source_pending}`} item={item} canReply={data.can_reply === true} onSaved={() => setEpoch(v => v + 1)} />)}{data.next_offset != null && <Button type="button" variant="outline" size="sm" disabled={busy || !fresh} onClick={() => void read(true)}>继续读取跟进</Button>}</>}</div>;
}
