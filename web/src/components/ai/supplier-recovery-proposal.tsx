"use client";

import { SupplierRecoveryResults } from "@/components/projects/supplier-recovery-results";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";
import { isRecord, responseBody } from "@/components/workspace-api";
import { Statement } from "./change-work-package-proposal";

const kinds: Record<string, string> = { expediting: "催交", substitution: "替代验证", borrowing: "拆借核对", tooling_recovery: "工装恢复" };
const filled = (v: unknown) => typeof v === "string" && !!v.trim() && v.length <= 4000;
export function supplierRecoveryReady(payload: Row): boolean {
  const review = obj(payload.review), choices = rows(review.choices), options = rows(obj(payload.assessment).options);
  return payload.details_confirmed === true && filled(review.reason) && filled(review.scope_and_limits)
    && choices.length === options.length && new Set(choices.map(c => c.key)).size === options.length
    && options.every(o => choices.some(c => c.key === o.key)) && choices.some(c => c.disposition === "adopt")
    && choices.every(c => filled(c.reason) && (c.disposition === "exclude" || c.disposition === "adopt"
      && filled(c.description) && filled(c.verification) && filled(c.completion_criteria)
      && filled(c.missing_resolution) && !!c.owner_user_id && /^\d{4}-\d{2}-\d{2}$/.test(text(c.due_date))));
}
async function read(projectId: string, findingId?: string): Promise<Row> {
  const response = await fetch(`/api/projects/${projectId}/npi/supplier-recovery/work-packages${findingId ? `?finding_id=${findingId}` : ""}`, { cache: "no-store" });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "暂不能读取当前项目成员和恢复工作，请刷新后核对");
  return value;
}
function Input({ label, value, onChange, maxLength = 4000 }: { label: string; value: unknown; onChange: (value: string) => void; maxLength?: number }) {
  return <label className="block">{label}<textarea className={field} maxLength={maxLength} value={text(value)} onChange={e => onChange(e.target.value)}/></label>;
}
export function SupplierRecoveryProposalView({ projectId, payload, onChange }: { projectId: string; payload: Row; onChange?: (p: Row) => void }) {
  const [context, setContext] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const assessment = obj(payload.assessment), labels = obj(payload.reference_labels), options = rows(assessment.options), review = obj(payload.review), choices = rows(review.choices);
  const update = (patch: Row) => onChange?.({ ...payload, review: { ...review, ...patch }, details_confirmed: false });
  const change = (key: unknown, patch: Row) => update({ choices: choices.map(c => c.key === key ? { ...c, ...patch } : c) });
  async function load(start = false) {
    setBusy(true); setError(null);
    try {
      setContext(await read(projectId));
      if (start) update({ reason: "", scope_and_limits: "", choices: options.map(o => ({ key: o.key, disposition: "", reason: "", description: o.description, verification: Array.isArray(o.required_verification) ? o.required_verification.join("\n") : "", completion_criteria: o.completion_criteria ?? "", missing_resolution: "", owner_user_id: null, stage_id: null, due_date: null, communication_draft: o.communication_draft ?? "" })) });
    } catch (e) { setError(e instanceof Error ? e.message : "读取未完成"); } finally { setBusy(false); }
  }
  return <div className="space-y-3 p-3 text-sm">
    <a className="text-primary underline" href={`/projects?project=${projectId}&tab=materials`}>查看原供应与工装记录</a>
    <p>接受保存人工核对结果；独立应用后，每个采用项建立一条具名任务。任务完成后仍须回原业务登记实际到货、技术验证、拆借授权或工装可用证据。</p>
    <p className="whitespace-pre-wrap">本次范围与限制：{text(assessment.coverage_limits)}</p>
    {Array.isArray(assessment.missing) && assessment.missing.length > 0 && <p>共同待补：{assessment.missing.map(String).join("；")}</p>}
    <section className="space-y-2"><h4 className="font-medium">原资料观察</h4>{rows(assessment.observations).map((s, i) => <Statement key={i} value={s} labels={labels}/>)}</section>
    {options.map(o => <article className="space-y-2 rounded-md border p-3" key={text(o.key)}>
      <h4 className="font-medium">{kinds[text(o.kind)]} · {text(o.description)}</h4>
      <p>实际对象：{Array.isArray(o.target_reference_ids) ? o.target_reference_ids.map(id => text(labels[String(id)]) || String(id)).join("；") : "待核对"}</p>
      <Statement value={obj(o.basis)} labels={labels}/>
      <p className="whitespace-pre-wrap">原验证要求：{Array.isArray(o.required_verification) ? o.required_verification.map(String).join("；") : "待补"}</p>
      <p>原完成判据：{text(o.completion_criteria) || "待补"}</p>
      {Array.isArray(o.missing) && o.missing.length > 0 && <p>待补：{o.missing.map(String).join("；")}</p>}
      {!!o.communication_draft && <details><summary className="cursor-pointer">原沟通文案（未发送）</summary><p className="whitespace-pre-wrap">{text(o.communication_draft)}</p></details>}
    </article>)}
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {onChange && !payload.review && <Button size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>逐项核对方案与责任日期</Button>}
    {payload.review != null && <><Button size="sm" variant="outline" disabled={busy} onClick={() => void load()}>读取当前项目成员与阶段</Button>
      <fieldset disabled={!onChange || busy} className="space-y-3"><legend className="font-medium">人工核对及实际应用内容</legend>
        {choices.map(c => <article className="space-y-2 rounded-md border p-3" key={text(c.key)}>
          <h5 className="font-medium">{kinds[text(options.find(o => o.key === c.key)?.kind)]} · {text(options.find(o => o.key === c.key)?.description)}</h5>
          <label className="block">本次处理<select className={field} value={text(c.disposition)} onChange={e => change(c.key, { disposition: e.target.value })}><option value="">请选择</option><option value="adopt">采用，建立待执行任务</option><option value="exclude">本次不采用</option></select></label>
          <Input label="采用、调整或不采用的实际依据" value={c.reason} onChange={reason => change(c.key, { reason })}/>
          {c.disposition === "adopt" && <>
            <Input label="实际任务内容与范围" value={c.description} onChange={description => change(c.key, { description })}/>
            <Input label="实际验证要求（含替代、拆借或可用性确认）" value={c.verification} onChange={verification => change(c.key, { verification })}/>
            <Input label="任务完成判据及所需证据" value={c.completion_criteria} onChange={completion_criteria => change(c.key, { completion_criteria })}/>
            <Input label="共同及本项缺失资料的补齐办法、责任与办理顺序；无缺项也请说明" value={c.missing_resolution} onChange={missing_resolution => change(c.key, { missing_resolution })}/>
            <label className="block">具名负责人<select className={field} value={text(c.owner_user_id)} onChange={e => change(c.key, { owner_user_id: e.target.value || null })}><option value="">请选择当前内部项目成员</option>{!!c.owner_user_id && !rows(context?.members).some(m => m.id === c.owner_user_id) && <option value={text(c.owner_user_id)}>原选人员：{text(c.owner_user_id)}（请核对当前资格）</option>}{rows(context?.members).map(m => <option key={text(m.id)} value={text(m.id)}>{text(m.name)}</option>)}</select></label>
            <label className="block">任务所属阶段<select className={field} value={text(c.stage_id)} onChange={e => change(c.key, { stage_id: e.target.value || null })}><option value="">项目级任务</option>{!!c.stage_id && !rows(context?.stages).some(s => s.id === c.stage_id) && <option value={text(c.stage_id)}>原选阶段：{text(c.stage_id)}</option>}{rows(context?.stages).map(s => <option key={text(s.id)} value={text(s.id)}>{text(s.name)}</option>)}</select></label>
            <label className="block">目标日期<input type="date" className={field} value={text(c.due_date)} onChange={e => change(c.key, { due_date: e.target.value || null })}/></label>
            <Input label="人工核对的沟通文案（可留空，应用不会发送）" maxLength={6000} value={c.communication_draft} onChange={communication_draft => change(c.key, { communication_draft })}/>
          </>}
        </article>)}
        <Input label="本次接受理由" value={review.reason} onChange={reason => update({ reason })}/>
        <Input label="整体执行范围、排除项及尚未解决的限制" value={review.scope_and_limits} onChange={scope_and_limits => update({ scope_and_limits })}/>
        <label className="flex items-start gap-2"><input type="checkbox" checked={payload.details_confirmed === true} onChange={e => onChange?.({ ...payload, details_confirmed: e.target.checked })}/><span>已逐项核对原依据、采用范围、负责人和日期、验证与缺项处理，可据此建立待执行工作。</span></label>
      </fieldset></>}
  </div>;
}

export function SupplierRecoveryAppliedTasks({ projectId, findingId }: { projectId: string; findingId: string }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  async function load() { setBusy(true); setError(null); try { setData(await read(projectId, findingId)); } catch (e) { setError(e instanceof Error ? e.message : "读取未完成"); } finally { setBusy(false); } }
  const statuses: Record<string, string> = { todo: "待执行", in_progress: "办理中", done: "已完成", blocked: "受阻", skipped: "已跳过", pending_approval: "待批准" };
  return <details className="space-y-2 rounded-md border p-3 text-sm" onToggle={e => { if (e.currentTarget.open && !data && !busy) void load(); }}><summary className="cursor-pointer">实际恢复任务与当前进展</summary><Button size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新实际任务</Button>{error && <p role="alert" className="text-destructive">{error}</p>}{data && !data.application && <p>尚无已应用工作。</p>}{rows(data?.items).map(item => <article key={text(item.task_id)} className="space-y-1 border-l pl-3"><a className="text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${item.task_id}`}>{text(item.title)}</a><p>{statuses[text(item.status)] ?? text(item.status)} · {text(item.owner_name) || "当前待分派"} · {text(item.due_date) || "未设日期"}</p><p className="whitespace-pre-wrap">{text(item.expected_output)}</p>{!!item.item_id && <SupplierRecoveryResults projectId={projectId} itemId={text(item.item_id)}/>}</article>)}<p className="text-xs text-muted-foreground">此处展示任务状态；实际供应恢复以原供应／工装记录及核验证据为准。</p></details>;
}
