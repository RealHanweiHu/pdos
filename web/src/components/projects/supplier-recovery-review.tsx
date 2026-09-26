"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";
import { responseBody } from "@/components/workspace-api";

const checks = { evidence_checked: "已逐份核对原证据位置与实际内容", verification_verified: "原验证要求已落实，包括适用的替代审批、验证或拆借授权", criteria_verified: "原恢复完成判据均已满足", remaining_resolved: "影响本次恢复的缺项均已解决" };
const defaults = { evidence_checked: false, verification_verified: false, criteria_verified: false, remaining_resolved: false };
async function call(url: string, body: Row): Promise<Row> { const response = await fetch(url, { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); const value = obj(await responseBody(response).catch(() => null)); if (!response.ok) throw new Error(text(obj(value.detail).message) || "核对结果未确认，请读取当前裁决"); return value; }
export function SupplierRecoveryReview({ projectId, itemId, resultId, onRecorded }: { projectId: string; itemId: string; resultId: string; onRecorded: () => Promise<void> }) {
  const [decision, setDecision] = useState("confirmed"), [reason, setReason] = useState(""), [followUp, setFollowUp] = useState("");
  const [confirmed, setConfirmed] = useState(defaults), [preview, setPreview] = useState<Row | null>(null), [finalCheck, setFinalCheck] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const attempts = useRef(new Map<string, string>());
  const base = `/api/projects/${projectId}/npi/supplier-recovery/items/${itemId}/reviews`;
  function clear() { setPreview(null); setFinalCheck(false); }
  function body() { const command = { result_id: resultId, decision, reason, follow_up: followUp, ...confirmed }; const key = JSON.stringify(command); let requestId = attempts.current.get(key); if (!requestId) { requestId = crypto.randomUUID(); attempts.current.set(key, requestId); } return { ...command, request_id: requestId }; }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "操作未完成"); } finally { setBusy(false); } }
  const source = obj(obj(preview?.snapshot).current_source), result = obj(obj(preview?.snapshot).result), report = obj(result.report), draft = obj(preview?.review);
  return <fieldset disabled={busy} className="space-y-3 rounded-md border p-3 text-sm"><legend className="font-medium">独立核对本次恢复结果</legend>
    <p className="text-xs text-muted-foreground">登记人和当前任务负责人不能自行确认。确认只对应这份结果及原业务证据；任务、问题和实际供应业务继续沿原流程办理。</p>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    <label className="block">核对结论<select className={field} value={decision} onChange={e => { setDecision(e.target.value); clear(); }}><option value="confirmed">确认本次恢复结果</option><option value="returned">退回补齐</option></select></label>
    <label className="block">核对依据与结论<textarea className={field} maxLength={4000} value={reason} onChange={e => { setReason(e.target.value); clear(); }}/></label>
    {decision === "returned" ? <label className="block">须补齐的内容、责任及后续要求<textarea className={field} maxLength={4000} value={followUp} onChange={e => { setFollowUp(e.target.value); clear(); }}/></label> : <div className="space-y-2">{Object.entries(checks).map(([k,label]) => <label className="flex items-start gap-2" key={k}><input type="checkbox" checked={confirmed[k as keyof typeof confirmed]} onChange={e => { setConfirmed(c => ({ ...c, [k]: e.target.checked })); clear(); }}/><span>{label}</span></label>)}</div>}
    <Button size="sm" variant="outline" disabled={!reason.trim() || (decision === "returned" ? !followUp.trim() : !Object.values(confirmed).every(Boolean))} onClick={() => void act(async () => { clear(); setPreview(await call(`${base}/preview`, body())); })}>预览原结果与本次裁决</Button>
    {preview && <section className="space-y-2 rounded-md border p-3"><h4 className="font-medium">将{draft.decision === "confirmed" ? "确认" : "退回"}结果 v{text(result.version)}</h4><p className="whitespace-pre-wrap">原判据：{text(obj(obj(result.source_snapshot).accepted_choice).completion_criteria)}</p><p className="whitespace-pre-wrap">实际结果：{text(report.actual_result)}</p><p className="whitespace-pre-wrap">验证回应：{text(report.verification_response)}</p><p className="whitespace-pre-wrap">判据回应：{text(report.criteria_response)}</p><p className="whitespace-pre-wrap">剩余：{text(report.remaining_work)}</p>{!!report.review_response && <p className="whitespace-pre-wrap">对前次退回的回应：{text(report.review_response)}</p>}
      {rows(obj(result.source_snapshot).evidence).map((e, i) => <p className="whitespace-pre-wrap" key={i}><a className="text-primary underline" href={`/projects?project=${projectId}&tab=documents&entity_id=${e.document_id}`}>{text(obj(e.document).filename)}</a> · {text(e.location)}：{text(e.supports)}</p>)}
      <p>{obj(preview.snapshot).sources_current === true ? "本版业务依据和核对范围当前一致" : "原依据已变化或不可用，本次仅可退回补齐"}</p>{rows(source.targets).map(t => <p key={text(t.reference_id)}>{text(obj(t.tooling).title) || text(obj(t.material).material_reference) || "原对象"} · {t.ready === true ? "实际业务条件满足" : "实际业务条件待补"}</p>)}
      <p className="whitespace-pre-wrap">本次裁决：{text(draft.reason)}</p>{!!draft.follow_up && <p className="whitespace-pre-wrap">后续要求：{text(draft.follow_up)}</p>}
      <label className="flex gap-2"><input type="checkbox" checked={finalCheck} onChange={e => setFinalCheck(e.target.checked)}/><span>已核对上述版本与证据，按本次结论具名记录。</span></label><Button size="sm" disabled={!finalCheck} onClick={() => void act(async () => { await call(base, { ...draft, expected_digest: preview.digest }); clear(); await onRecorded(); })}>记录独立裁决</Button>
    </section>}
  </fieldset>;
}
