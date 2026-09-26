"use client";

import { SupplierRecoveryReview } from "./supplier-recovery-review";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";
import { responseBody } from "@/components/workspace-api";

type Evidence = { document_id: string; location: string; supports: string };
type Draft = { disposition: string; actual_result: string; verification_response: string; criteria_response: string; remaining_work: string; review_response: string; evidence: Evidence[] };
const labels: Record<string, string> = { progress: "进展记录", ready_for_review: "提交恢复结果待核对", unable_to_recover: "当前无法恢复" };
const blank = (): Draft => ({ disposition: "progress", actual_result: "", verification_response: "", criteria_response: "", remaining_work: "", review_response: "", evidence: [] });
async function call(url: string, body?: Row): Promise<Row> {
  const response = await fetch(url, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value = obj(await responseBody(response).catch(() => null));
  if (!response.ok) throw new Error(text(obj(value.detail).message) || "结果暂未确认，请读取原记录后再办理");
  return value;
}
function TextInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) { return <label className="block">{label}<textarea className={field} maxLength={4000} value={value} onChange={e => onChange(e.target.value)}/></label>; }
function Sources({ projectId, value }: { projectId: string; value: Row }) {
  return <section className="space-y-2 rounded-md border p-3 text-xs"><p>对应原任务：{text(obj(value.task).title)}</p><p className="whitespace-pre-wrap">原采用判据：{text(obj(value.accepted_choice).completion_criteria)}</p>{rows(value.targets).map(t => <div key={text(t.reference_id)}><p>{text(t.reference_id).startsWith("tooling_round:") ? text(obj(t.tooling).title) : text(obj(t.material).material_reference) || "原物料异常"} · {t.ready === true ? "当前有合格供给核对／实际工装可用依据" : "原业务条件尚未满足，请回原记录核对"}</p><a className="text-primary underline" href={text(t.reference_id).startsWith("tooling_round:") ? `/projects?project=${projectId}&tab=materials&tooling_round_id=${text(t.reference_id).split(":")[1]}` : `/projects?project=${projectId}&tab=work-items&entity_id=${text(t.issue_id)}`}>查看实际业务记录</a></div>)}</section>;
}
export function SupplierRecoveryResults({ projectId, itemId }: { projectId: string; itemId: string }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [notice, setNotice] = useState("");
  const [draft, setDraft] = useState<Draft>(blank), [preview, setPreview] = useState<Row | null>(null), [checked, setChecked] = useState(false), [lookup, setLookup] = useState("");
  const attempts = useRef(new Map<string, string>());
  const base = `/api/projects/${projectId}/npi/supplier-recovery/items/${itemId}/results`;
  function update(patch: Partial<Draft>) { setDraft(d => ({ ...d, ...patch })); setPreview(null); setChecked(false); }
  async function load(more = false) { const result = await call(`${base}${more && data?.next_before_version ? `?before_version=${data.next_before_version}` : ""}`); setData(old => more && old ? { ...result, items: [...rows(old.items), ...rows(result.items)] } : result); }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "操作未完成"); } finally { setBusy(false); } }
  function body() { const command = { ...draft, expected_version: Number(data?.latest_version ?? 0), response_to_review_id: obj(data?.latest_review).decision === "returned" ? obj(data?.latest_review).id : null }; const key = JSON.stringify(command); let id = attempts.current.get(key); if (!id) { id = crypto.randomUUID(); attempts.current.set(key, id); } return { ...command, request_id: id }; }
  function add(id: string) { if (!id || draft.evidence.length >= 20) return; update({ evidence: [...draft.evidence, { document_id: id, location: "", supports: "" }] }); }
  const ready = (obj(data?.latest_review).decision !== "returned" || !!draft.review_response.trim()) && [draft.actual_result, draft.verification_response, draft.criteria_response, draft.remaining_work].every(s => !!s.trim()) && draft.evidence.length > 0 && draft.evidence.every(e => !!e.document_id && !!e.location.trim() && !!e.supports.trim());
  const stateLabels: Record<string, string> = { no_result: "尚未登记", in_progress: "进展记录，尚未提交核对", pending_review: "等待独立核对", returned: "已退回，须补齐后提交新结果", confirmed: "本版恢复结果已独立确认", source_changed: "依据或核对范围变化，须重新核对" };
  return <details className="space-y-3 rounded-md border p-3 text-sm" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(() => load()); }}><summary className="cursor-pointer">登记实际结果、证据与后续处理</summary>
    <p className="text-xs text-muted-foreground">由当前任务负责人登记，保留每版原资料。提交待核对后仍需独立确认；登记结果不关闭问题，也不写入到货、拆借或技术批准。</p>
    {error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}
    <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => load())}>读取当前资料与历史</Button>
    {data && (data.current_error ? <p className="text-xs">{text(data.current_error)}</p> : <Sources projectId={projectId} value={obj(data.current)}/>)}
    {data && <p className="font-medium">{stateLabels[text(data.recovery_state)]}</p>}
    {data?.latest_review != null && <section className="space-y-1 rounded-md border p-3"><p>最新独立裁决：{obj(data.latest_review).decision === "confirmed" ? "确认" : "退回"} · {text(obj(data.latest_review).reviewer_name)}</p><p className="whitespace-pre-wrap">{text(obj(obj(data.latest_review).review).reason)}</p><p className="whitespace-pre-wrap">{text(obj(obj(data.latest_review).review).follow_up)}</p></section>}
    {data?.can_review === true && <SupplierRecoveryReview key={text(data.latest_result_id)} projectId={projectId} itemId={itemId} resultId={text(data.latest_result_id)} onRecorded={() => load()}/>}
    {data?.can_report === true && <fieldset disabled={busy} className="space-y-2"><legend className="font-medium">追加结果版本</legend>
      <label className="block">本次结果<select className={field} value={draft.disposition} onChange={e => update({ disposition: e.target.value })}>{Object.entries(labels).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      {obj(data.latest_review).decision === "returned" && <TextInput label="逐项回应上次退回要求（将绑定原裁决）" value={draft.review_response} onChange={review_response => update({ review_response })}/>}
      <TextInput label="实际结果及发生范围" value={draft.actual_result} onChange={actual_result => update({ actual_result })}/>
      <TextInput label="对原验证要求的逐项回应及尚未验证内容" value={draft.verification_response} onChange={verification_response => update({ verification_response })}/>
      <TextInput label="对原完成判据的逐项回应" value={draft.criteria_response} onChange={criteria_response => update({ criteria_response })}/>
      <TextInput label="剩余缺项、后续责任与处理；无剩余也请说明" value={draft.remaining_work} onChange={remaining_work => update({ remaining_work })}/>
      <label className="block">添加原项目证据<select className={field} value="" onChange={e => add(e.target.value)}><option value="">请选择文件（最多20个位置）</option>{rows(data.documents).map(d => <option key={text(d.id)} value={text(d.id)}>{text(d.filename)}</option>)}</select></label>
      {data.more_documents === true && <p className="text-xs">仅显示最近100个文件，可从项目文档复制更早文件标识。</p>}
      <div className="flex gap-2"><label className="flex-1 text-xs">已有项目文件标识<input className={field} value={lookup} onChange={e => setLookup(e.target.value)}/></label><Button size="sm" variant="outline" onClick={() => { add(lookup.trim()); setLookup(""); }}>添加</Button></div>
      {draft.evidence.map((e, index) => <section className="space-y-2 rounded-md border p-3" key={index}><a className="text-primary underline" href={`/projects?project=${projectId}&tab=documents&entity_id=${e.document_id}`}>{text(rows(data.documents).find(d => d.id === e.document_id)?.filename) || "查看原文件"}</a><TextInput label="原文页码、段落或表格位置" value={e.location} onChange={location => update({ evidence: draft.evidence.map((v, i) => i === index ? { ...v, location } : v) })}/><TextInput label="该位置支持的实际结果／验证判据" value={e.supports} onChange={supports => update({ evidence: draft.evidence.map((v, i) => i === index ? { ...v, supports } : v) })}/><Button size="sm" variant="outline" onClick={() => update({ evidence: draft.evidence.filter((_, i) => i !== index) })}>移除此位置</Button></section>)}
      <Button size="sm" variant="outline" disabled={!ready} onClick={() => void act(async () => { setPreview(await call(`${base}/preview`, body())); setChecked(false); })}>预览本次结果与原业务依据</Button>
      {preview && <section className="space-y-2 rounded-md border p-3"><p className="font-medium">将保存：{labels[text(obj(preview.report).disposition)]}</p><Sources projectId={projectId} value={obj(preview.source)}/><p className="whitespace-pre-wrap">{text(obj(preview.report).actual_result)}</p>{!!obj(preview.report).review_response && <p className="whitespace-pre-wrap">对原退回的回应：{text(obj(preview.report).review_response)}</p>}<p className="whitespace-pre-wrap">验证回应：{text(obj(preview.report).verification_response)}</p><p className="whitespace-pre-wrap">判据回应：{text(obj(preview.report).criteria_response)}</p><p className="whitespace-pre-wrap">后续：{text(obj(preview.report).remaining_work)}</p>{rows(obj(preview.source).evidence).map((e, i) => <p key={i}>{text(obj(e.document).filename)} · {text(e.location)}：{text(e.supports)}</p>)}<label className="flex gap-2"><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)}/><span>已核对实际业务依据、证据位置和本次结果。</span></label><Button size="sm" disabled={!checked} onClick={() => void act(async () => { const result = await call(base, { ...obj(preview.report), expected_digest: preview.digest }); setPreview(null); setChecked(false); setDraft(blank()); setNotice(`已登记结果版本 v${result.version}，原资料保留；待核对结果尚未独立确认。`); await load(); })}>具名保存本次结果</Button></section>}
    </fieldset>}
    {rows(data?.items).map(r => <details className="space-y-2 rounded-md border p-3" key={text(r.id)}><summary className="cursor-pointer">v{text(r.version)} · {labels[text(obj(r.report).disposition)]} · {new Date(text(r.created_at)).toLocaleString()}</summary><p>{r.sources_current === true ? "本版任务及原业务依据当前一致" : "本版依据已变化或不可用，请重新核对并登记新版本"}</p><p className="text-xs">具名登记：{text(r.author_name) || text(r.created_by_user_id)}</p>{["actual_result", "verification_response", "criteria_response", "remaining_work", "review_response"].map(k => <p className="whitespace-pre-wrap" key={k}>{text(obj(r.report)[k])}</p>)}{r.review != null && <section className="border-l pl-3"><p>原独立裁决：{obj(r.review).decision === "confirmed" ? "确认" : "退回"} · {text(obj(r.review).reviewer_name)}</p><p className="whitespace-pre-wrap">{text(obj(obj(r.review).review).reason)}</p><p className="whitespace-pre-wrap">{text(obj(obj(r.review).review).follow_up)}</p></section>}<Sources projectId={projectId} value={obj(r.source_snapshot)}/>{rows(obj(r.source_snapshot).evidence).map((e, i) => <p className="whitespace-pre-wrap" key={i}><a className="text-primary underline" href={`/projects?project=${projectId}&tab=documents&entity_id=${e.document_id}`}>{text(obj(e.document).filename)}</a> · {text(e.location)}：{text(e.supports)}</p>)}</details>)}
    {!!data?.next_before_version && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => load(true))}>更早20版结果</Button>}
  </details>;
}
