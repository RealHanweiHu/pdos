"use client";

import { useRef, useState } from "react";
import { FirmwareTaskResults } from "./firmware-task-results";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const obj = (v: unknown): Row => isRecord(v) ? v : {};
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const text = (v: unknown) => v == null || v === "" ? "未记录" : String(v);
const purposes: Record<string, string> = { investigation: "复现与调查", verification: "验证待定影响", regression: "回归验证", coordination: "专业协同" };
const statuses: Record<string, string> = { todo: "待执行", in_progress: "进行中", blocked: "阻塞", done: "已完成", skipped: "已跳过", pending_approval: "待批准" };
const input = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

export function FirmwareTaskSummary({ value, projectId }: { value: unknown; projectId: string }) {
  if (!isRecord(value) || !isRecord(value.package) || !isRecord(value.binding)) return null;
  const p = value.package, snapshot = obj(p.snapshot), binding = obj(value.binding.snapshot);
  return <div className="space-y-2 rounded-md border p-3 text-xs">
    <p className="font-medium">固件 {text(snapshot.firmware_version)} · 工作包资料 v{text(p.revision_number)} · {purposes[text(binding.purpose)] ?? text(binding.purpose)}</p>
    <p className="whitespace-pre-wrap">工作来源：{text(binding.basis)}</p>
    <p className="whitespace-pre-wrap">工作包完成判据：{text(binding.completion_criteria)}</p>
    <p className="whitespace-pre-wrap">观察事实：{text(snapshot.observations)}</p>
    <p className="whitespace-pre-wrap">调查假设（待证实）：{text(snapshot.hypotheses)}</p>
    <p className="whitespace-pre-wrap">未知影响与待补：{text(snapshot.unknowns)}</p>
    <p className="text-muted-foreground">任务执行状态与实际回归结论分别留存。请在原逐次测试记录登记结果和证据。</p>
    <a className="text-primary underline" href={`/projects?project=${projectId}&tab=quality&firmware_package_id=${encodeURIComponent(String(p.id))}`}>打开原固件工作包、来源与实际任务</a>
  </div>;
}

export function FirmwarePackageTasks({ projectId, packageId, canEdit, canRecordResults = canEdit }: { projectId: string; packageId: string; canEdit: boolean; canRecordResults?: boolean }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null);
  const [mode, setMode] = useState("new"), [existing, setExisting] = useState(""), [purpose, setPurpose] = useState("verification");
  const [title, setTitle] = useState(""), [stage, setStage] = useState(""), [owner, setOwner] = useState(""), [start, setStart] = useState(""), [due, setDue] = useState("");
  const [output, setOutput] = useState(""), [description, setDescription] = useState(""), [criteria, setCriteria] = useState(""), [basis, setBasis] = useState("");
  const attempt = useRef<{ signature: string; id: string } | null>(null);
  const base = `/api/projects/${projectId}/npi/firmware-work-packages/${packageId}/tasks`;
  async function request(body?: unknown): Promise<Row> {
    const response = await fetch(base, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const value: unknown = await response.json();
    if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "任务办理未完成，请核对后重试");
    return value;
  }
  async function act(fn: () => Promise<void>) { setBusy(true); setError(null); try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "任务办理未完成"); } finally { setBusy(false); } }
  async function read() { setData(await request()); }
  function reset() { setTitle(""); setStage(""); setOwner(""); setStart(""); setDue(""); setOutput(""); setDescription(""); setCriteria(""); setBasis(""); setExisting(""); setMode("new"); setDirty(false); attempt.current = null; }
  function edit() { setDirty(true); setNotice(null); }
  const selected = rows(data?.previous_tasks).find(v => obj(v.task).id === existing);
  const newReady = title.trim() && stage && owner && due && output.trim() && description.trim() && (!start || start <= due);
  const ready = !!data && data.can_prepare === true && criteria.trim() && basis.trim() && (mode === "new" ? newReady : !!selected);
  const member = (id: unknown) => text(rows(data?.members).find(m => m.id === id)?.display_name ?? id);
  return <details className="mt-3 rounded-md border p-2" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(read); }}>
    <summary className="cursor-pointer text-sm font-medium">验证与协同 · 实际任务</summary>
    <div className="mt-3 space-y-3 text-xs">
      <p className="text-muted-foreground">将核对后的验证或协同要求交给具名负责人。任务沿项目任务和 My Work 办理；更换工作包资料时可继续承接同固件版本未结束的原任务。</p>
      {data && <>
        {!data.can_prepare && <p className="text-primary">此资料已有新版或引用来源已变化。现有任务保留追溯；新增或承接任务请先核对并修订最新工作包。</p>}
        {rows(data.tasks).length === 0 ? <p>本资料版本尚未办理实际任务。</p> : rows(data.tasks).map(binding => { const task = obj(binding.task), snapshot = obj(binding.snapshot); return <article key={text(binding.id)} className="space-y-1 rounded-md border p-2"><p><a className="text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${text(task.id)}`}>{text(task.title)}</a> · {statuses[text(task.status)] ?? text(task.status)} · {snapshot.mode === "carried" ? "承接原任务" : "创建任务"}</p><p>负责人：{member(task.assignee_user_id)} · 截止：{text(task.due_date)}</p><p>当前交付要求：{text(task.expected_output)}</p><p>完成判据：{text(snapshot.completion_criteria)}</p><p>任务完成依据：{text(task.completion_evidence_ref)}</p><p className="whitespace-pre-wrap">关联依据：{text(snapshot.basis)}</p><FirmwareTaskResults projectId={projectId} bindingId={text(binding.id)} canEdit={canRecordResults} /></article>; })}
        {canEdit && data.can_prepare === true && <form className="space-y-3" onSubmit={e => { e.preventDefault(); void act(async () => {
          const payload = { expected_digest: data.digest, purpose, completion_criteria: criteria.trim(), basis: basis.trim(), ...(mode === "new" ? { new_task: { title: title.trim(), stage_id: stage, assignee_user_id: owner, start_date: start || null, due_date: due, expected_output: output.trim(), description: description.trim() } } : { existing_task_id: existing, existing_task_digest: selected?.digest }) };
          const signature = JSON.stringify(payload); if (attempt.current?.signature !== signature) attempt.current = { signature, id: crypto.randomUUID() };
          const result = await request({ ...payload, request_id: attempt.current.id }); reset(); setNotice(`实际任务已${mode === "new" ? "创建" : "承接"}，可从任务列表继续办理。`); await read(); if (!result.task_id) throw new Error("已返回办理回执，请刷新核对任务列表");
        }); }}><fieldset disabled={busy} className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2"><label>办理方式<select className={input} value={mode} onChange={e => { setMode(e.target.value); edit(); }}><option value="new">创建一个实际任务</option><option value="carry" disabled={!rows(data.previous_tasks).length}>承接此前资料的原任务</option></select></label><label>工作用途<select className={input} value={purpose} onChange={e => { setPurpose(e.target.value); edit(); }}>{Object.entries(purposes).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label></div>
          {mode === "carry" ? <><label className="block">选择同固件版本尚未结束的原任务<select required className={input} value={existing} onChange={e => { setExisting(e.target.value); edit(); }}><option value="">请选择</option>{rows(data.previous_tasks).map(v => { const t = obj(v.task); return <option key={text(t.id)} value={text(t.id)}>{text(t.title)} · {statuses[text(t.status)] ?? text(t.status)}</option>; })}</select></label>{selected && <p>原负责人：{member(obj(selected.task).assignee_user_id)} · 原截止日期：{text(obj(selected.task).due_date)} · 原交付要求：{text(obj(selected.task).expected_output)}。责任或日期调整请在原任务办理。</p>}</> : <>
            <label className="block">实际任务标题<input required className={input} maxLength={512} value={title} onChange={e => { setTitle(e.target.value); edit(); }} /></label>
            <div className="grid gap-3 sm:grid-cols-2"><label>项目阶段<select required className={input} value={stage} onChange={e => { setStage(e.target.value); edit(); }}><option value="">请选择</option>{rows(data.stages).map(s => <option key={text(s.id)} value={text(s.id)}>{text(s.name)}</option>)}</select></label><label>具名负责人<select required className={input} value={owner} onChange={e => { setOwner(e.target.value); edit(); }}><option value="">请选择</option>{rows(data.members).map(m => <option key={text(m.id)} value={text(m.id)}>{text(m.display_name)}</option>)}</select></label><label>计划开始日期<input type="date" className={input} value={start} onChange={e => { setStart(e.target.value); edit(); }} /></label><label>计划截止日期<input required type="date" className={input} min={start || undefined} value={due} onChange={e => { setDue(e.target.value); edit(); }} /></label></div>
            <label className="block">任务范围、条件与执行说明<textarea required maxLength={10000} className={input} value={description} onChange={e => { setDescription(e.target.value); edit(); }} /></label><label className="block">预期交付物<textarea required maxLength={10000} className={input} value={output} onChange={e => { setOutput(e.target.value); edit(); }} /></label>
          </>}
          <label className="block">本工作包指定的完成判据<textarea required maxLength={10000} className={input} value={criteria} onChange={e => { setCriteria(e.target.value); edit(); }} /></label><label className="block">对应哪项未知影响、验证要求或协同需要<textarea required maxLength={4000} className={input} value={basis} onChange={e => { setBasis(e.target.value); edit(); }} /></label>
          <Button type="submit" size="sm" disabled={!ready}>{mode === "new" ? "确认创建实际任务" : "确认承接原任务"}</Button>
        </fieldset></form>}
      </>}
      {notice && <p role="status">{notice}</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
      <Button type="button" size="sm" variant="outline" disabled={busy || dirty} onClick={() => void act(read)}>刷新任务及来源状态</Button>{dirty && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => { reset(); void act(read); }}>放弃未保存输入并刷新</Button>}
    </div>
  </details>;
}
