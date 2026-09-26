"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import { SampleConfigurationSnapshot } from "./sample-configuration-snapshot";

type Row = Record<string, unknown>;
type Reference = { run_id: string; digest: string; snapshot: Row; assessment: Row; role: "verification" | "comparison"; scope: string };
const obj = (v: unknown): Row => isRecord(v) ? v : {};
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const text = (v: unknown) => v == null || v === "" ? "未记录" : String(v);
const input = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const states: Record<string, string> = { passed: "通过", failed: "失败", planned: "计划中", in_progress: "进行中", aborted: "终止" };
const outcomes: Record<string, string> = { recorded: "已记录执行说明", needs_follow_up: "仍需后续处理", scope_verified: "已核对本次限定范围" };
const fields = { tested_scope: "本次实际验证或处理范围", excluded_scope: "未覆盖的范围与限制", criteria_assessment: "逐项完成判据的核对说明", follow_up: "仍需补测、处置或交接的内容", reason: "本次登记或修订依据" };
type Fields = Record<keyof typeof fields, string>;
const blank = (): Fields => Object.fromEntries(Object.keys(fields).map(k => [k, ""])) as Fields;
function runLabel(run: Row) { return `${text(obj(run.case).title)} · 第 ${text(run.run_number)} 次 · ${states[text(run.status)] ?? text(run.status)}`; }
function RunEvidence({ run, assessment, projectId }: { run: Row; assessment: Row; projectId: string }) {
  const evidence = obj(run.evidence), basis = obj(run.verification_basis);
  return <div className="space-y-1 text-xs">
    <p className="font-medium">{runLabel(run)}</p>
    <p>{run.draft_state === "confirmed" ? "已确认" : "未确认草稿"} · 实际测试时间：{run.execution_time_source === "system_completion" || run.execution_time_precision === "unknown" ? "尚未明确" : text(run.executed_at)}</p>
    <p className="whitespace-pre-wrap">方法：{text(basis.method)}</p><p className="whitespace-pre-wrap">判据：{text(basis.acceptance_criteria)}</p>
    <SampleConfigurationSnapshot revision={run.configuration} />
    <p>原证据：{text(evidence.filename)} · {assessment.eligible ? "登记条件齐备，仍需专业核对适用范围" : "存在验证缺口"}</p>
    {Array.isArray(assessment.gaps) && assessment.gaps.length > 0 && <ul className="list-disc pl-4 text-primary">{assessment.gaps.map((gap, i) => <li key={i}>{String(gap)}</li>)}</ul>}
    <p className="whitespace-pre-wrap">测试结果说明：{text(run.result_notes)}</p>
    <a className="mr-3 text-primary underline" href={`/projects?project=${projectId}&tab=quality&test_case_id=${text(run.test_case_id)}&test_run_id=${text(run.id)}`}>查看原始测试与实测数据</a>
    {evidence.id != null && <a className="text-primary underline" href={`/projects?project=${projectId}&tab=documents&entity_id=${text(evidence.id)}`}>查看原报告</a>}
  </div>;
}
export function FirmwareTaskResults({ projectId, bindingId, canEdit }: { projectId: string; bindingId: string; canEdit: boolean }) {
  const [data, setData] = useState<Row | null>(null), [history, setHistory] = useState<Row[]>([]), [nextRevision, setNextRevision] = useState<number | null>(null);
  const [options, setOptions] = useState<Row[]>([]), [cursor, setCursor] = useState<string | null>(null), [selected, setSelected] = useState<Reference[]>([]);
  const [values, setValues] = useState<Fields>(blank), [outcome, setOutcome] = useState("needs_follow_up");
  const [busy, setBusy] = useState(false), [dirty, setDirty] = useState(false), [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null);
  const attempt = useRef<{ signature: string; id: string } | null>(null);
  const base = `/api/projects/${projectId}/npi/firmware-task-results/${bindingId}`;
  async function request(path = "", body?: unknown): Promise<Row> {
    const response = await fetch(`${base}${path}`, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const result: unknown = await response.json();
    if (!response.ok || !isRecord(result)) throw new Error(isRecord(result) && isRecord(result.detail) && typeof result.detail.message === "string" ? result.detail.message : "结果登记未完成，请核对后重试");
    return result;
  }
  async function act(fn: () => Promise<void>) { setBusy(true); setError(null); try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "结果办理未完成"); } finally { setBusy(false); } }
  async function read(more = false) { const result = await request(more && nextRevision ? `?before_revision=${nextRevision}` : ""); if (!more) setData(result); setHistory(old => more ? [...old, ...rows(result.history)] : rows(result.history)); setNextRevision(typeof result.next_revision === "number" ? result.next_revision : null); }
  async function readRuns(more = false) { const result = await request(`/runs${more && cursor ? `?after_id=${cursor}` : ""}`); setOptions(old => more ? [...old, ...rows(result.items)] : rows(result.items)); setCursor(typeof result.next_cursor === "string" ? result.next_cursor : null); }
  function edit() { setDirty(true); setNotice(null); }
  function clear() { setSelected([]); setValues(blank()); setOutcome("needs_follow_up"); setDirty(false); attempt.current = null; }
  const verifications = selected.filter(s => s.role === "verification");
  const ready = data && Object.values(values).every(v => v.trim()) && selected.every(s => s.scope.trim() && s.snapshot.draft_state === "confirmed") && (outcome !== "scope_verified" || (data.can_verify_scope === true && verifications.length > 0 && verifications.every(s => s.assessment.eligible === true)));
  return <details className="mt-2 rounded-md border p-2" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(() => read()); }}>
    <summary className="cursor-pointer text-sm font-medium">执行结果与回归对应</summary>
    <div className="mt-3 space-y-3 text-xs">
      <p className="text-muted-foreground">逐次测试和原报告保留原始事实。本处记录它们对应的工作范围、专业核对与未覆盖部分；该记录不自动完成任务或批准固件发布。</p>
      {data && <>
        <p className="whitespace-pre-wrap">工作包完成判据：{text(obj(obj(data.binding).snapshot).completion_criteria)}</p>
        {!data.can_verify_scope && <p className="text-primary">本资料或任务已有新版，或引用来源已变化。可以登记历史执行证据和待办；确认新范围须先办理最新工作包。</p>}
        {canEdit && <form className="space-y-3" onSubmit={e => { e.preventDefault(); void act(async () => {
          const payload = { expected_digest: data.digest, outcome, ...Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v.trim()])), runs: selected.map(s => ({ run_id: s.run_id, expected_digest: s.digest, role: s.role, scope: s.scope.trim() })) };
          const signature = JSON.stringify(payload); if (attempt.current?.signature !== signature) attempt.current = { signature, id: crypto.randomUUID() };
          const result = await request("", { ...payload, request_id: attempt.current.id }); clear(); setNotice(`结果对应 v${text(result.revision_number)} 已登记。`); await read();
        }); }}><fieldset disabled={busy} className="space-y-3">
          <label className="block">本次处理结论<select className={input} value={outcome} onChange={e => { setOutcome(e.target.value); edit(); }}>{Object.entries(outcomes).map(([key, label]) => <option key={key} value={key} disabled={key === "scope_verified" && data.can_verify_scope !== true}>{label}</option>)}</select></label>
          <div className="grid gap-3 sm:grid-cols-2">{Object.entries(fields).map(([key, label]) => <label key={key}>{label}<textarea className={input} required maxLength={key === "reason" ? 4000 : 10000} value={values[key as keyof Fields]} onChange={e => { setValues({ ...values, [key]: e.target.value }); edit(); }} /></label>)}</div>
          <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" size="sm" onClick={() => void act(() => readRuns())}>读取本项目逐次测试</Button>{cursor && <Button type="button" variant="outline" size="sm" onClick={() => void act(() => readRuns(true))}>更多测试</Button>}</div>
          <div className="max-h-96 space-y-2 overflow-y-auto">{options.map(row => { const run = obj(row.snapshot); return <details className="rounded-md border p-2" key={text(row.run_id)}><summary className="cursor-pointer">{runLabel(run)}</summary><div className="mt-2 space-y-2"><RunEvidence run={run} assessment={obj(row.assessment)} projectId={projectId} /><Button type="button" size="sm" variant="outline" disabled={run.draft_state !== "confirmed" || (selected.length >= 100 && !selected.some(s => s.run_id === row.run_id))} onClick={() => { const old = selected.find(s => s.run_id === row.run_id); const next: Reference = { run_id: String(row.run_id), digest: String(row.digest), snapshot: run, assessment: obj(row.assessment), role: old?.role ?? "verification", scope: old?.scope ?? "" }; setSelected(old ? selected.map(s => s.run_id === next.run_id ? next : s) : [...selected, next]); edit(); }}>{selected.some(s => s.run_id === row.run_id) ? "重新核对此测试引用" : "关联此测试"}</Button></div></details>; })}</div>
          {selected.map((ref, i) => <div key={ref.run_id} className="space-y-2 rounded-md border p-2"><RunEvidence run={ref.snapshot} assessment={ref.assessment} projectId={projectId} /><label className="block">证据用途<select className={input} value={ref.role} onChange={e => { setSelected(selected.map((s, n) => n === i ? { ...s, role: e.target.value as Reference["role"] } : s)); edit(); }}><option value="verification">本次范围的验证证据</option><option value="comparison">对照 / 历史证据</option></select></label><label className="block">此记录实际覆盖哪项要求<textarea className={input} required maxLength={4000} value={ref.scope} onChange={e => { setSelected(selected.map((s, n) => n === i ? { ...s, scope: e.target.value } : s)); edit(); }} /></label><Button type="button" variant="outline" size="sm" onClick={() => { setSelected(selected.filter((_, n) => n !== i)); edit(); }}>移除此测试引用</Button></div>)}
          {outcome === "scope_verified" && <p className="text-muted-foreground">至少一条本次验证记录，且全部已确认通过、具原报告、真实时间、方法判据和同固件样机配置。结论仅覆盖上方逐项说明的范围。</p>}
          <Button type="submit" size="sm" disabled={!ready}>登记新的结果对应版本</Button>
        </fieldset></form>}
      </>}
      {notice && <p role="status">{notice}</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
      <div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || dirty} onClick={() => void act(() => read())}>刷新结果与工作包状态</Button>{dirty && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => { clear(); void act(() => read()); }}>放弃未保存输入并刷新</Button>}</div>
      {history.map(record => { const s = obj(record.snapshot), changed = rows(record.current_evidence).some(r => r.changed === true); return <details className="rounded-md border p-2" key={text(record.id)}><summary className="cursor-pointer">结果对应 v{text(record.revision_number)} · {outcomes[text(s.outcome)] ?? text(s.outcome)}{changed ? " · 原证据已有变化" : ""}</summary><div className="mt-2 space-y-2"><p>登记人：{text(record.created_by_name)} · {text(record.created_at)} · 资料 v{text(s.package_revision)}</p><p className="text-muted-foreground">以下为保存时的核对范围与证据快照。当前任务、资料及原始测试状态仍需分别核对。</p>{Object.entries(fields).map(([key, label]) => <p key={key} className="whitespace-pre-wrap"><strong>{label}：</strong>{text(s[key])}</p>)}{rows(s.runs).map(ref => <div key={text(ref.run_id)} className="rounded-md border p-2"><p>{ref.role === "comparison" ? "对照证据" : "本次验证证据"}：{text(ref.scope)}</p><RunEvidence run={obj(ref.snapshot)} assessment={obj(ref.assessment)} projectId={projectId} /></div>)}</div></details>; })}
      {nextRevision && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => read(true))}>更早的结果对应</Button>}
    </div>
  </details>;
}
