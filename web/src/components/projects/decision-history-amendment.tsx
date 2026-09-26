"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
type Evidence = { document: Row; correspondence: string };
const labels: Record<string, string> = { title: "标题", outcome: "历史结论", context: "背景", options_text: "考虑过的选项原文", trade_offs: "权衡", rationale: "理由", consequence: "后果及后续要求", historical_date: "历史日期", historical_approver: "历史批准人原文", historical_owner: "历史负责人原文", historical_kind: "历史决策类型原文", historical_state: "历史办理状态原文", external_ref: "历史决策编号", issue_ref: "历史问题编号或说明" };
const field = "w-full rounded-md border bg-background p-2 text-xs";
function show(value: unknown): string { return value == null || value === "" ? "未提供" : typeof value === "object" ? JSON.stringify(value) : String(value); }
function rows(value: unknown): Row[] { return Array.isArray(value) ? value.filter(isRecord) : []; }
export function DecisionHistoryAmendment({ projectId, sourceId, onChanged }: { projectId: string; sourceId: string; onChanged: () => Promise<void> }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [receipt, setReceipt] = useState<Row | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({}), [draft, setDraft] = useState<Record<string, string>>({}), [reason, setReason] = useState(""), [impact, setImpact] = useState(""), [ack, setAck] = useState(false);
  const [evidence, setEvidence] = useState<Evidence[]>([]), [documents, setDocuments] = useState<Row[] | null>(null), [originalDocument, setOriginalDocument] = useState<Row | null>(null), [cursor, setCursor] = useState<Row | null>(null), [search, setSearch] = useState(""), [savedSearch, setSavedSearch] = useState("");
  const pending = useRef<{ signature: string; id: string } | null>(null), base = `/api/projects/${projectId}/decision-intake-sources/${sourceId}`;
  async function request(path: string, body?: object) {
    const response = await fetch(`${base}${path}`, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" }), value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "历史内容更正暂不可用，请查询原回执");
    return value;
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "读取未完成"); } finally { setBusy(false); } }
  async function load(more = false) {
    const next = await request(`/amendments${more && data?.next_before_revision ? `?before_revision=${data.next_before_revision}` : ""}`);
    if (!Array.isArray(next.history) || typeof next.digest !== "string") throw new Error("历史更正资料不完整");
    setData(old => more && old ? { ...next, history: [...rows(old.history), ...rows(next.history).filter(item => !rows(old.history).some(prior => prior.id === item.id))] } : next); setAck(false);
  }
  async function find(more = false) {
    const query = new URLSearchParams({ search: more ? savedSearch : search });
    if (more && cursor) for (const key of ["before_created_at", "before_id"]) query.set(key, String(cursor[key]));
    const value = await request(`/amendment-evidence?${query}`);
    if (!Array.isArray(value.items) || !value.items.every(isRecord)) throw new Error("依据文件清单不完整");
    const next = value.items; setDocuments(old => more ? [...(old ?? []), ...next.filter(item => !old?.some(prior => prior.id === item.id))] : next); setOriginalDocument(isRecord(value.original) ? value.original : null); setCursor(isRecord(value.next) ? value.next : null); if (!more) setSavedSearch(search);
  }
  function choose(document: Row) {
    setEvidence(old => old.some(item => item.document.id === document.id) ? old.map(item => item.document.id === document.id ? { ...item, document } : item) : [...old, { document, correspondence: "" }]); setAck(false);
  }
  const current = data && isRecord(data.content) ? data.content : {}, original = data && isRecord(data.original) && isRecord(data.original.original) ? data.original.original : {};
  const keys = Object.keys(labels).filter(key => selected[key]), changed = keys.filter(key => (draft[key]?.trim() ? draft[key] : null) !== (current[key] ?? null));
  const valid = data?.can_amend === true && changed.length > 0 && keys.every(key => !["title", "outcome"].includes(key) || !!draft[key]?.trim()) && !!reason.trim() && !!impact.trim() && evidence.length > 0 && evidence.every(item => !!item.correspondence.trim()) && ack;
  async function save() {
    if (!data || !valid) return;
    const body = { expected_revision: data.revision, expected_digest: data.digest, changes: Object.fromEntries(keys.map(key => [key, draft[key]?.trim() ? draft[key] : null])), reason: reason.trim(), impact_note: impact.trim(), evidence: evidence.map(item => ({ document_id: item.document.id, expected_digest: item.document.digest, correspondence: item.correspondence.trim() })), acknowledge_history: true }, signature = JSON.stringify(body);
    if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    const result = await request("/amendments", { ...body, request_id: pending.current.id });
    if (!isRecord(result.receipt)) throw new Error("更正回执不完整，请重新查询历史");
    setReceipt(result.receipt); pending.current = null; setSelected({}); setDraft({}); setAck(false); await load(); await onChanged();
  }
  const fileChoices = [...(originalDocument ? [originalDocument] : []), ...(documents ?? []).filter(doc => doc.id !== originalDocument?.id)];
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(() => load()); }}><summary className="cursor-pointer font-medium">更正历史登记内容与依据</summary><div className="mt-3 space-y-3 text-xs">
    <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => load())}>读取当前内容与更正历史</Button>
    <p>更正生成新的历史记录，并更新本条来源的当前关联。原文和旧登记保留，历史人员与日期按资料记录；当前批准、关卡和实际执行结果仍沿原流程办理。</p>
    {data && data.can_amend !== true && <p>当前来源没有可更正的本源历史记录，或当前没有更正权限。可继续查看历史；已有正式批准决策须进入原业务流程办理。</p>}
    {data?.can_amend === true && <fieldset disabled={busy} className="space-y-3">
      <p className="font-medium">本次更正当前历史记录：{show(current.title)} · 来源版本 {show(data.revision)}</p>
      <div className="space-y-2">{Object.entries(labels).map(([key, label]) => { const raw = original[key === "options_text" ? "options" : key], cell = isRecord(raw) ? raw : {}; return <details key={key} className="rounded-md border p-2"><summary className="cursor-pointer">{label}{selected[key] ? " · 已选更正" : ""}</summary><p className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap">原件 {show(cell.cell)}：{show(cell.value)}</p><p className="max-h-40 overflow-auto whitespace-pre-wrap">当前登记：{show(current[key])}</p><label className="my-2 flex gap-2"><input type="checkbox" checked={!!selected[key]} onChange={e => { setSelected(old => ({ ...old, [key]: e.target.checked })); setDraft(old => ({ ...old, [key]: old[key] ?? (current[key] == null ? "" : String(current[key])) })); setAck(false); }}/>更正此字段{!["title", "outcome"].includes(key) ? "（留空表示未知或清空）" : ""}</label>{selected[key] && (key === "historical_date" ? <input type="date" aria-label={label} className={field} value={draft[key] ?? ""} onChange={e => { setDraft(old => ({ ...old, [key]: e.target.value })); setAck(false); }}/> : <textarea aria-label={label} className={field} maxLength={key === "title" ? 512 : 20000} value={draft[key] ?? ""} onChange={e => { setDraft(old => ({ ...old, [key]: e.target.value })); setAck(false); }}/>)}</details>; })}</div>
      <label className="block">具名更正依据<textarea className={field} maxLength={2000} value={reason} onChange={e => { setReason(e.target.value); setAck(false); }}/></label><label className="block">对已引用或已办业务的影响及后续处理<textarea className={field} maxLength={4000} value={impact} onChange={e => { setImpact(e.target.value); setAck(false); }}/></label>
      <div className="space-y-2 rounded-md border p-3"><p className="font-medium">选择实际依据文件，并说明与更正字段的对应关系</p><div className="flex gap-2"><input aria-label="依据文件名称" className={field} maxLength={200} placeholder="按文件名查找，留空查看项目内部文件" value={search} onChange={e => setSearch(e.target.value)}/><Button type="button" size="sm" variant="outline" onClick={() => void act(() => find())}>查找文件与原件</Button></div>
        {documents?.length === 0 && !originalDocument && <p>暂无匹配的内部项目文件。</p>}
        <div className="max-h-56 space-y-2 overflow-auto">{fileChoices.map(doc => { const prior = evidence.find(item => item.document.id === doc.id); return <div key={String(doc.id)} className="flex items-start gap-2 border-t pt-2"><span className="min-w-0 flex-1 break-words">{show(doc.filename)}{doc.id === originalDocument?.id ? " · 本条来源原件" : ""}{typeof doc.href === "string" && <a className="ml-2 text-primary underline" href={doc.href}>查看原件</a>}</span><Button type="button" size="sm" variant="outline" disabled={prior?.document.digest === doc.digest || !prior && evidence.length >= 10} onClick={() => choose(doc)}>{prior ? "采用当前文件版本" : "选择依据"}</Button></div>; })}</div>
        {cursor && <Button type="button" size="sm" variant="outline" onClick={() => void act(() => find(true))}>更多文件</Button>}
        {evidence.map(item => <div key={String(item.document.id)} className="space-y-2 border-t pt-2"><p>{show(item.document.filename)} · 已选版本摘要 {show(item.document.sha256)}</p><label className="block">支持哪些字段、更正后内容及原文位置<textarea className={field} maxLength={4000} value={item.correspondence} onChange={e => { setEvidence(old => old.map(v => v.document.id === item.document.id ? { ...v, correspondence: e.target.value } : v)); setAck(false); }}/></label><Button type="button" size="sm" variant="outline" onClick={() => { setEvidence(old => old.filter(v => v.document.id !== item.document.id)); setAck(false); }}>移除此依据</Button></div>)}
      </div>
      {!!changed.length && <div className="overflow-auto"><table className="w-full text-left"><thead><tr><th>字段</th><th>当前登记</th><th>更正后</th></tr></thead><tbody>{changed.map(key => <tr key={key} className="border-t"><th className="p-2 align-top font-normal">{labels[key]}</th><td className="max-w-80 whitespace-pre-wrap break-words p-2 align-top">{show(current[key])}</td><td className="max-w-80 whitespace-pre-wrap break-words p-2 align-top">{show(draft[key])}</td></tr>)}</tbody></table></div>}
      <label className="flex gap-2"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)}/>已逐项核对更正前后内容、实际文件依据与后续影响，确认保存新的历史记录并更新本来源关联；原记录保留。</label>
      <Button type="button" size="sm" disabled={!valid} onClick={() => void act(save)}>保存历史内容更正</Button>
    </fieldset>}
    {receipt && <p role="status">更正已保存，来源版本 {show(receipt.source_revision)}。<a className="ml-2 text-primary underline" href={`/projects?project=${projectId}&tab=decisions#decision-${receipt.replacement_decision_id}`}>查看更正后记录</a></p>}
    {data && rows(data.history).map(item => <details key={String(item.id)} className="rounded-md border p-3"><summary className="cursor-pointer">来源版本 {show(item.source_revision)} · {show(item.actor_name)} · {show(item.created_at)}</summary><p className="whitespace-pre-wrap">更正依据：{show(item.reason)}<br/>影响及处理：{show(item.impact_note)}</p><div className="my-2 flex gap-3"><a className="text-primary underline" href={`/projects?project=${projectId}&tab=decisions#decision-${item.previous_decision_id}`}>更正前记录</a><a className="text-primary underline" href={`/projects?project=${projectId}&tab=decisions#decision-${item.replacement_decision_id}`}>更正后记录</a></div>{isRecord(item.changes) && Object.entries(item.changes).map(([key, value]) => isRecord(value) && <div key={key} className="my-2 whitespace-pre-wrap border-t pt-2"><p className="font-medium">{labels[key] ?? key}</p><p>更正前：{show(value.before)}<br/>更正后：{show(value.after)}</p></div>)}{rows(item.evidence_current).map(ref => { const document = isRecord(ref.snapshot) ? ref.snapshot : {}; return <div key={String(ref.document_id)} className="my-2 border-t pt-2"><p>依据：{show(document.filename)}{ref.changed === true ? " · 当前文件已变化或不可读取，请重新核对" : ""}</p><p className="whitespace-pre-wrap">{show(ref.correspondence)}</p><a className="text-primary underline" href={`/projects?project=${projectId}&tab=documents&entity_id=${ref.document_id}`}>查看依据文件</a></div>; })}</details>)}
    {!!data?.next_before_revision && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => load(true))}>更早内容更正</Button>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
  </div></details>;
}
