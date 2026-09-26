"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const obj = (v: unknown): Row => isRecord(v) ? v : {};
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const text = (v: unknown) => v == null ? "" : String(v);
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

export function ChangeExecutionFollowup({ projectId, ecrId, bindingId, itemKey, resultId, expectedDigest, onChanged, onDirtyChange }: {
  projectId: string; ecrId: string; bindingId: string; itemKey: string; resultId: string; expectedDigest: string; onChanged: () => Promise<void>; onDirtyChange: (dirty: boolean) => void;
}) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState("new"), [choices, setChoices] = useState<Row[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [values, setValues] = useState({ title: "", stage: "", owner: "", start: "", due: "", description: "", output: "", criteria: "", reason: "", existingId: "" });
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);
  const attempt = useRef<{ signature: string; id: string } | null>(null);
  const base = `/api/projects/${projectId}/changes`;
  const update = (key: keyof typeof values, value: string) => setValues(old => ({ ...old, [key]: value }));
  async function request(path: string, body?: unknown): Promise<Row> {
    const response = await fetch(base + path, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const value: unknown = await response.json();
    if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "后续任务未保存，请重试");
    return value;
  }
  async function act(fn: () => Promise<void>) { setBusy(true); setError(null); try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "办理失败"); } finally { setBusy(false); } }
  async function existing(more = false) {
    const value = await request(`/ecrs/${ecrId}/execution-tasks/choices${more && cursor ? `?after_id=${cursor}` : ""}`);
    setChoices(old => more ? [...old, ...rows(value.tasks)] : rows(value.tasks));
    setCursor(typeof value.next_after_id === "string" ? value.next_after_id : null);
  }
  const selected = obj(choices.find(c => obj(c.task).id === values.existingId)?.task);
  const person = (id: unknown) => text(rows(data?.members).find(m => m.id === id)?.display_name ?? id);
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(async () => setData(await request(`/ecrs/${ecrId}/execution-tasks`))); }}>
    <summary className="cursor-pointer font-medium">按本版结果安排后续补齐任务</summary>
    <div className="mt-3 space-y-2">
      <p>保留原任务、结果及退回意见，新任务在项目任务和 My Work 中办理。新结果需回应此处安排的补齐要求。</p>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {data && <form onSubmit={e => { e.preventDefault(); void act(async () => {
        const assignment = { item_key: itemKey, completion_criteria: values.criteria.trim(), ...(mode === "new" ? { new_task: { title: values.title.trim(), stage_id: values.stage, assignee_user_id: values.owner, start_date: values.start || null, due_date: values.due, description: values.description.trim(), expected_output: values.output.trim() } } : { existing_task_id: values.existingId, existing_task_digest: choices.find(c => obj(c.task).id === values.existingId)?.digest }) };
        const payload = { expected_digest: expectedDigest, source_result_id: resultId, reason: values.reason.trim(), assignment };
        const signature = JSON.stringify(payload);
        if (attempt.current?.signature !== signature) attempt.current = { signature, id: crypto.randomUUID() };
        await request(`/execution-items/${bindingId}/follow-ups`, { ...payload, request_id: attempt.current.id });
        onDirtyChange(false);
        await onChanged();
      }); }}><fieldset disabled={busy} className="space-y-3" onChange={() => onDirtyChange(true)}>
        <label className="block">任务安排<select className={field} value={mode} onChange={e => { setMode(e.target.value); if (e.target.value === "existing" && !choices.length) void act(() => existing()); }}><option value="new">创建后续任务</option><option value="existing">核对后关联未结束任务</option></select></label>
        {mode === "new" ? <>
          <label className="block">任务标题<input required maxLength={512} className={field} value={values.title} onChange={e => update("title", e.target.value)}/></label>
          <div className="grid gap-2 sm:grid-cols-2">
            <label>阶段<select required className={field} value={values.stage} onChange={e => update("stage", e.target.value)}><option value="">请选择</option>{rows(data.stages).map(s => <option key={text(s.id)} value={text(s.id)}>{text(s.name)}</option>)}</select></label>
            <label>具名负责人<select required className={field} value={values.owner} onChange={e => update("owner", e.target.value)}><option value="">请选择</option>{rows(data.members).map(m => <option key={text(m.id)} value={text(m.id)}>{text(m.display_name)}</option>)}</select></label>
            <label>计划开始<input className={field} type="date" value={values.start} onChange={e => update("start", e.target.value)}/></label>
            <label>计划截止<input required className={field} type="date" min={values.start || undefined} value={values.due} onChange={e => update("due", e.target.value)}/></label>
          </div>
          <label className="block">补齐工作范围<textarea required maxLength={10000} className={field} value={values.description} onChange={e => update("description", e.target.value)}/></label>
          <label className="block">预期交付物<textarea required maxLength={10000} className={field} value={values.output} onChange={e => update("output", e.target.value)}/></label>
        </> : <>
          <label className="block">原项目任务<select required className={field} value={values.existingId} onChange={e => update("existingId", e.target.value)}><option value="">请选择</option>{choices.map(c => <option key={text(obj(c.task).id)} value={text(obj(c.task).id)}>{text(obj(c.task).title)}</option>)}</select></label>
          {values.existingId && <p>原负责人：{person(selected.assignee_user_id)} · 截止：{text(selected.due_date)} · 交付要求：{text(selected.expected_output)}</p>}
          {cursor && <Button type="button" size="sm" variant="outline" onClick={() => void act(() => existing(true))}>更多原任务</Button>}
        </>}
        <label className="block">本次补齐的完成判据<textarea required maxLength={10000} className={field} value={values.criteria} onChange={e => update("criteria", e.target.value)}/></label>
        <label className="block">根据本版结果 / 退回意见，需要补齐什么<textarea required maxLength={4000} className={field} value={values.reason} onChange={e => update("reason", e.target.value)}/></label>
        <div className="flex gap-2"><Button type="submit" size="sm">保存具名后续任务</Button><Button type="button" size="sm" variant="outline" onClick={() => { setValues({title:"",stage:"",owner:"",start:"",due:"",description:"",output:"",criteria:"",reason:"",existingId:""});attempt.current=null;onDirtyChange(false); }}>放弃未保存安排</Button></div>
      </fieldset></form>}
      {!data && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => setData(await request(`/ecrs/${ecrId}/execution-tasks`)))}>读取任务安排资料</Button>}
    </div>
  </details>;
}
