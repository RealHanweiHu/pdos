"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const text = (v: unknown) => v == null || v === "" ? "未记录" : String(v);
const items = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const field = "mt-1 w-full rounded-md border bg-background p-2 text-xs";
const taskStates: Record<string, string> = { todo: "待开始", in_progress: "进行中", blocked: "受阻", done: "已完成任务", skipped: "已跳过", pending_approval: "待批准" };
export function TestPreparationSummary({ preparation }: { preparation: unknown }) {
  if (!isRecord(preparation) || !isRecord(preparation.snapshot)) return <p className="text-xs text-muted-foreground">未固定执行工作包（旧记录或补录）。</p>;
  const p = preparation.snapshot;
  return <div className="space-y-1 rounded-md border p-2 text-xs"><p className="font-medium">执行工作包 v{text(preparation.revision_number)} · 要求样机 {text(p.required_sample_count)} 台</p><p className="whitespace-pre-wrap">计划测试条件：{text(p.conditions)}</p><p>计划环境：{text(p.environment)}</p><p className="whitespace-pre-wrap">交付要求：{text(p.expected_output)}</p><p className="whitespace-pre-wrap">资源说明：{text(p.resource_notes)}</p><p className="text-muted-foreground">以上为保存的准备要求；实际执行条件与测试结果另行登记。</p></div>;
}
function parse(value: unknown) {
  if (!isRecord(value) || !isRecord(value.state) || !isRecord(value.state.case) || !isRecord(value.state.plan)) throw new Error("工作包资料不完整");
  return { state: value.state, case: value.state.case, plan: value.state.plan, digest: String(value.digest),
    proposal: isRecord(value.reviewed_proposal) ? value.reviewed_proposal : null, preparation: isRecord(value.preparation) ? value.preparation : null, task: isRecord(value.task) ? value.task : null,
    execution: isRecord(value.execution) ? value.execution : {}, members: items(value.members), samples: items(value.samples), resources: items(value.resources), reservations: items(value.reservations), history: items(value.history) };
}
type Need = { resource_id: string; parallel_units: string; basis: string };
export function TestExecutionPreparation({ projectId, caseId, canEdit, onSaved }: { projectId: string; caseId: string; canEdit: boolean; onSaved: () => Promise<void> }) {
  const [data, setData] = useState<ReturnType<typeof parse> | null>(null);
  const [owner, setOwner] = useState(""), [start, setStart] = useState(""), [due, setDue] = useState(""), [count, setCount] = useState("1");
  const [samples, setSamples] = useState<string[]>([]), [conditions, setConditions] = useState(""), [environment, setEnvironment] = useState(""), [output, setOutput] = useState("");
  const [needs, setNeeds] = useState<Need[]>([]), [resourceNotes, setResourceNotes] = useState(""), [reason, setReason] = useState("");
  const [resolution, setResolution] = useState("");
  const [busy, setBusy] = useState(false), [dirty, setDirty] = useState(false), [error, setError] = useState<string | null>(null), [saved, setSaved] = useState(false);
  const request = useRef<{ signature: string; id: string } | null>(null);
  const base = `/api/projects/${projectId}/npi/test-cases/${caseId}/execution-preparation`;
  function accept(value: unknown) {
    const next = parse(value), p = isRecord(next.preparation?.snapshot) ? next.preparation.snapshot : next.proposal ?? {};
    setData(next); setOwner(typeof next.task?.assignee_user_id === "string" ? next.task.assignee_user_id : "");
    setStart(typeof next.task?.start_date === "string" ? next.task.start_date : ""); setDue(typeof next.task?.due_date === "string" ? next.task.due_date : "");
    setCount(next.proposal && !next.preparation && p.required_sample_count == null ? "" : String(p.required_sample_count ?? next.plan.sample_size ?? 1)); setSamples(Array.isArray(p.sample_ids) ? p.sample_ids.map(String) : []);
    setConditions(typeof p.conditions === "string" ? p.conditions : ""); setEnvironment(typeof p.environment === "string" ? p.environment : "");
    setOutput(typeof p.expected_output === "string" ? p.expected_output : ""); setResourceNotes(typeof p.resource_notes === "string" ? p.resource_notes : Array.isArray(p.resource_requirements) ? p.resource_requirements.map(String).join("\n") : "");
    setNeeds(items(p.resource_needs).map(r => ({ resource_id: String(r.resource_id), parallel_units: String(r.parallel_units), basis: String(r.basis) })));
    setResolution(typeof p.proposal_resolution_notes === "string" ? p.proposal_resolution_notes : "");
    setReason(""); setDirty(false);
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "工作包未保存"); } finally { setBusy(false); } }
  async function read() { const response = await fetch(base, { cache: "no-store" }); if (!response.ok) throw new Error("工作包资料暂不可用"); accept(await response.json()); }
  const editable = canEdit && data?.state.can_edit === true && !["done", "skipped"].includes(String(data.task?.status));
  return <details className="basis-full rounded-md border p-2" onToggle={event => { if (event.currentTarget.open && !data && !busy) void act(read); }}>
    <summary className="cursor-pointer text-sm font-medium">执行工作包：负责人、样机与资源</summary>
    <div className="mt-3 space-y-3 text-xs">
      {data && <>
        {data.task && <p>实际任务：<a className="text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${text(data.task.id)}`}>{text(data.task.title)}</a> · {taskStates[text(data.task.status)] ?? text(data.task.status)}。任务状态和测试结论分别办理。</p>}
        {data.proposal && <div className="space-y-1 rounded-md border p-2"><p>本项带有已审阅并应用到计划的执行准备要求。建议负责专业：{text(data.proposal.responsible_role)}。</p><p>核对依据：{text(data.proposal.basis)}</p>{Array.isArray(data.proposal.unresolved) && data.proposal.unresolved.length > 0 && <ul className="list-disc pl-5">{data.proposal.unresolved.map((value, i) => <li key={i}>原审阅时待补：{String(value)}</li>)}</ul>}{typeof data.proposal.source_finding_id === "string" && <a className="text-primary underline" href={`/ai-review?finding=${encodeURIComponent(data.proposal.source_finding_id)}`}>查看原建议及人工处理记录</a>}</div>}
        {data.preparation && <TestPreparationSummary preparation={data.preparation} />}
        {editable ? <form className="space-y-3" onChange={() => { setDirty(true); setSaved(false); }} onSubmit={event => { event.preventDefault(); void act(async () => {
          const body = { expected_digest: data.digest, assignee_user_id: owner, start_date: start || null, due_date: due, required_sample_count: Number(count), sample_ids: samples,
            conditions: conditions.trim(), environment: environment.trim(), expected_output: output.trim(), resource_notes: resourceNotes.trim(), reason: reason.trim(), proposal_resolution_notes: resolution.trim() || null,
            resource_needs: needs.map(n => ({ ...n, parallel_units: Number(n.parallel_units), basis: n.basis.trim() })) };
          const signature = JSON.stringify(body); if (request.current?.signature !== signature) request.current = { signature, id: crypto.randomUUID() };
          const response = await fetch(base, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...body, request_id: request.current.id }) });
          const value: unknown = await response.json(); if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) ? text(value.detail.message) : "工作包未保存，请重试原请求");
          accept(value); setSaved(true); await onSaved();
        }); }}><fieldset disabled={busy} className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2"><label>负责人<select required className={field} value={owner} onChange={e => setOwner(e.target.value)}><option value="">选择项目成员</option>{data.members.map(m => <option key={text(m.id)} value={text(m.id)}>{text(m.display_name)}</option>)}</select></label><label>要求样机数量<input required className={field} type="number" min={1} max={100000} step={1} value={count} onChange={e => setCount(e.target.value)} /></label><label>计划开始日期（可选）<input className={field} type="date" value={start} onChange={e => setStart(e.target.value)} /></label><label>计划完成日期<input required className={field} type="date" value={due} onChange={e => setDue(e.target.value)} /></label></div>
          <details><summary className="cursor-pointer">选择本阶段实际样机 · 已选 {samples.length} 台</summary><div className="max-h-52 space-y-1 overflow-auto py-2">{data.samples.map(s => <label key={text(s.id)} className="flex gap-2"><input type="checkbox" disabled={s.status === "scrapped"} checked={samples.includes(String(s.id))} onChange={e => setSamples(previous => e.target.checked ? [...previous, String(s.id)] : previous.filter(id => id !== String(s.id)))} />{text(s.serial_number)} · {text(s.build_code)}{s.status === "scrapped" ? " · 已报废" : ""}</label>)}</div></details>
          {samples.length < Number(count) && <p>待补实际样机 {Number(count) - samples.length} 台；可先保存准备要求，执行前补齐。</p>}
          <label className="block">测试条件<textarea required maxLength={10000} className={field} value={conditions} onChange={e => setConditions(e.target.value)} /></label><label className="block">环境要求或待确认项<textarea required maxLength={2000} className={field} value={environment} onChange={e => setEnvironment(e.target.value)} /></label><label className="block">任务交付要求<textarea required maxLength={10000} className={field} value={output} onChange={e => setOutput(e.target.value)} /></label>
          <div className="space-y-2"><p>资源需求</p>{needs.map((n, i) => <div key={i} className="grid gap-2 rounded-md border p-2 sm:grid-cols-2"><label>现有资源<select required className={field} value={n.resource_id} onChange={e => setNeeds(previous => previous.map((v, j) => i === j ? { ...v, resource_id: e.target.value } : v))}><option value="">请选择</option>{data.resources.map(r => <option key={text(r.id)} value={text(r.id)}>{text(r.name)}</option>)}</select></label><label>并行使用数量<input required className={field} type="number" min={0.00000001} max={1000} step="any" value={n.parallel_units} onChange={e => setNeeds(previous => previous.map((v, j) => i === j ? { ...v, parallel_units: e.target.value } : v))} /></label><label>使用依据<input required maxLength={2000} className={field} value={n.basis} onChange={e => setNeeds(previous => previous.map((v, j) => i === j ? { ...v, basis: e.target.value } : v))} /></label><Button type="button" size="sm" variant="outline" onClick={() => { setNeeds(previous => previous.filter((_, j) => i !== j)); setDirty(true); }}>移除</Button></div>)}<Button type="button" size="sm" variant="outline" disabled={needs.length >= 100} onClick={() => { setNeeds(previous => [...previous, { resource_id: "", parallel_units: "1", basis: "" }]); setDirty(true); }}>添加资源需求</Button></div>
          <label className="block">资源准备说明或缺项<textarea required maxLength={2000} className={field} value={resourceNotes} onChange={e => setResourceNotes(e.target.value)} /></label><label className="block">本版准备依据<textarea required maxLength={2000} className={field} value={reason} onChange={e => setReason(e.target.value)} /></label>
          {data.proposal && Array.isArray(data.proposal.unresolved) && data.proposal.unresolved.length > 0 && <label className="block">原待补条件的解决情况及依据<textarea required maxLength={4000} className={field} value={resolution} onChange={e => setResolution(e.target.value)} /></label>}
          <p>保存会{data.task ? "更新同一实际任务并追加工作包版本" : "创建具名任务并保存首版工作包"}。资源需求仍需在原资源流程预约。</p>
          <Button type="submit" size="sm" disabled={!owner || !due || !reason.trim() || (!!data.proposal && Array.isArray(data.proposal.unresolved) && data.proposal.unresolved.length > 0 && !resolution.trim())}>确认保存工作包与任务</Button>
        </fieldset></form> : <p>当前仅查看准备要求与历史；新的执行安排请在最新计划的待测项中办理。</p>}
        {data.preparation && <div className="space-y-1 rounded-md border p-2"><p>当前工作包已确认通过且附证据的实际样机：{text(data.execution.passed_sample_count)} 台。历史未固定工作包的测试：{text(data.execution.unbound_run_count)} 次。</p><p className="text-muted-foreground">按不同实际样机计数，仍需核对失败、复测范围与项目验收条件。</p>{items(data.execution.runs).map(run => <p key={text(run.id)}><a className="text-primary underline" href={`/projects?project=${projectId}&tab=quality&test_case_id=${caseId}&test_run_id=${text(run.id)}`}>第{text(run.run_number)}次测试</a> · {({ in_progress: "进行中", passed: "通过", failed: "失败", aborted: "终止", planned: "计划中" } as Record<string, string>)[text(run.status)] ?? text(run.status)}</p>)}</div>}
        <details><summary className="cursor-pointer">查看实际资源预约 · {data.reservations.length} 条</summary>{data.reservations.map(r => <p key={text(r.id)}>{text(data.resources.find(x => x.id === r.resource_id)?.name)} · {text(r.window_start)}—{text(r.window_end)} · 数量{text(r.parallel_units)} · {({ active: "有效", released: "已释放", cancelled: "已取消" } as Record<string, string>)[text(r.state)] ?? text(r.state)}</p>)}{!data.reservations.length && <p>当前没有绑定该任务的实际预约记录。</p>}</details>
        {data.history.length > 0 && <details><summary className="cursor-pointer">最近 {data.history.length} 个准备版本</summary>{data.history.map(p => <div className="my-2" key={text(p.id)}><p>{text(p.created_at)} · 依据：{isRecord(p.snapshot) ? text(p.snapshot.reason) : "未记录"}</p><TestPreparationSummary preparation={p} /></div>)}</details>}
      </>}
      {saved && <p role="status">工作包及实际任务已保存。</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
      <Button type="button" size="sm" variant="outline" disabled={busy || dirty} onClick={() => void act(read)}>刷新工作包与实际状态</Button>
      {dirty && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(read)}>放弃未保存修改并重读</Button>}
    </div>
  </details>;
}
