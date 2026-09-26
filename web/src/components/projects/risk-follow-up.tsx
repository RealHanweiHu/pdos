"use client";

import { RiskFollowupResults } from "./risk-followup-results";
import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
type Basis = { risk: Row; references: { kind: string; label: string; items: Row[] }[] };
type Receipt = { source_changed: boolean; request_id: string; task_id: string; actor_user_id: string; actor_name: string; created_at: string; reason: string; basis: Basis; original: Row; task: Row; href: string };
type Prepared = { digest: string; basis: Basis; can_create: boolean; stages: { id: string; name: string }[]; people: { id: string; display_name: string }[]; recent: Receipt[]; has_more: boolean };
type Draft = { title: string; description: string; assignee_user_id: string; stage_id: string; due_date: string; expected_output: string; reason: string };
type RequestBody = { request_id: string; expected_digest: string; reason: string; new_task: Omit<Draft, "reason"> };
const empty: Draft = { title: "", description: "", assignee_user_id: "", stage_id: "", due_date: "", expected_output: "", reason: "" };
const control = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const str = (value: unknown) => value == null ? "" : String(value);
const status: Record<string, string> = { todo: "待开始", in_progress: "进行中", blocked: "受阻", pending_approval: "待批准", done: "已完成", skipped: "已跳过" };
function isBasis(v: unknown): v is Basis { return isRecord(v) && isRecord(v.risk) && Array.isArray(v.references) && v.references.every(g => isRecord(g) && typeof g.kind === "string" && typeof g.label === "string" && Array.isArray(g.items) && g.items.every(isRecord)); }
function isReceipt(v: unknown): v is Receipt { return isRecord(v) && typeof v.source_changed === "boolean" && typeof v.request_id === "string" && typeof v.task_id === "string" && typeof v.actor_user_id === "string" && typeof v.actor_name === "string" && typeof v.created_at === "string" && typeof v.reason === "string" && typeof v.href === "string" && v.href.startsWith("/projects?") && isBasis(v.basis) && isRecord(v.original) && isRecord(v.task); }
class FollowupError extends Error { constructor(message: string, public status: number) { super(message); } }

export function RiskFollowUp({ projectId, riskId }: { projectId: string; riskId: string }) {
  const [data, setData] = useState<Prepared | null>(null), [draft, setDraft] = useState<Draft>(empty);
  const [preview, setPreview] = useState<RequestBody | null>(null), [pending, setPending] = useState<RequestBody | null>(null);
  const [result, setResult] = useState<Receipt | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [lookup, setLookup] = useState("");
  const base = `/api/projects/${encodeURIComponent(projectId)}/risks/${encodeURIComponent(riskId)}/follow-up`;
  async function request(body?: RequestBody, id?: string): Promise<unknown> {
    const response = await fetch(`${base}${id ? `?request_id=${encodeURIComponent(id)}` : ""}`, {
      method: body ? "POST" : "GET", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined,
    });
    const value = await responseBody(response);
    if (!response.ok) throw new FollowupError(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "未取得任务办理结果，请保留原请求编号回查", response.status);
    return value;
  }
  async function load() {
    setBusy(true); setError(""); setPreview(null);
    try {
      const value = await request();
      if (!isRecord(value) || typeof value.digest !== "string" || !isBasis(value.basis) || typeof value.can_create !== "boolean" || typeof value.has_more !== "boolean" ||
        !Array.isArray(value.stages) || !value.stages.every(s => isRecord(s) && typeof s.id === "string" && typeof s.name === "string") ||
        !Array.isArray(value.people) || !value.people.every(p => isRecord(p) && typeof p.id === "string" && typeof p.display_name === "string") ||
        !Array.isArray(value.recent) || !value.recent.every(isReceipt)) throw new Error("任务准备资料不完整，请刷新重试");
      const prepared = value as Prepared;
      setData(prepared);
      setDraft(old => ({ ...old, title: old.title || `核对风险：${str(prepared.basis.risk.title)}`.slice(0, 512) }));
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); setData(null); }
    finally { setBusy(false); }
  }
  async function submit(body: RequestBody, replay = false) {
    setBusy(true); setError(""); setPending(body); setLookup(body.request_id);
    try {
      const value = await request(body);
      if (!isReceipt(value)) throw new Error("任务回执不完整，请用原请求编号回查");
      setResult(value); setPending(null); setPreview(null); setData(null); setDraft(empty);
    } catch (e) {
      const rejected = e instanceof FollowupError && (replay ? [409, 422] : [400, 401, 403, 404, 409, 422]).includes(e.status);
      if (rejected) { setPending(null); setPreview(null); setData(null); }
      setError(e instanceof Error ? e.message : "提交未完成");
    } finally { setBusy(false); }
  }
  async function read() {
    const id = pending?.request_id ?? lookup.trim();
    if (!id) return;
    setBusy(true); setError("");
    try {
      const value = await request(undefined, id);
      if (!isReceipt(value)) throw new Error("任务回执不完整");
      setResult(value);
      if (pending?.request_id === value.request_id) { setPending(null); setPreview(null); setData(null); setDraft(empty); }
    } catch (e) { setError(`${e instanceof Error ? e.message : "回查失败"}；未查到回执不代表之前没有提交，可稍后继续回查。`); }
    finally { setBusy(false); }
  }
  function receipt(value: Receipt) {
    return <div className="space-y-2 rounded-lg border p-3" key={value.request_id}>
      <p className="font-medium"><Link className="text-primary underline" href={value.href}>{str(value.task.title)}</Link> · {status[str(value.task.status)] ?? str(value.task.status)}</p>
      <p>{value.source_changed ? "风险或所引用业务已有变化，请按当前资料核对处理范围；原安排仍保留。" : "当前风险及原引用范围与安排时一致。"}</p>
      <p>原安排依据：{value.reason}</p><p>当前交付要求：{str(value.task.expected_output)}</p>
      <p>当前实际完成证据：{str(value.task.completion_evidence_ref) || "尚未登记"}</p>
      <p className="text-muted-foreground">原安排人 {value.actor_name} · {new Date(value.created_at).toLocaleString("zh-CN")} · 原风险版本 {str(value.basis.risk.updated_at)} · 请求 {value.request_id}</p>
      <RiskFollowupResults projectId={projectId} riskId={riskId} taskId={value.task_id} />
      <details><summary className="cursor-pointer">原安排及引用范围</summary><div className="mt-2 space-y-2">
        <p>原负责人：{str(value.original.assignee_name)} · 原日期：{str(value.original.due_date)}</p>
        <p>原交付要求：{str(value.original.expected_output)}</p>
        {value.basis.references.map(g => <details key={g.kind}><summary>{g.label}：{g.items.length} 条</summary><ul className="mt-1 space-y-1">{g.items.map(i => <li key={str(i.id)}>{str(i.title)} · 原状态 {status[str(i.status)] ?? str(i.status)}</li>)}</ul></details>)}
      </div></details>
    </div>;
  }
  return <details className="mt-3 rounded-lg border p-3 text-xs" onToggle={e => { if (e.currentTarget === e.target && e.currentTarget.open && !data && !busy && !pending && !result) void load(); }}>
    <summary className="cursor-pointer font-medium">安排风险处理任务 / 查看处理结果</summary>
    <div className="mt-3 space-y-3">
      <p className="text-muted-foreground">保存当前风险和实际业务引用，安排具名处理任务。任务进入负责人的 My Work；任务完成不自动关闭风险，也不改写原会议或阶段评审。</p>
      <Button type="button" variant="outline" size="sm" disabled={busy || !!pending} onClick={() => void load()}>刷新资料与已有任务（保留输入）</Button>
      {error ? <p role="alert" className="text-destructive">{error}</p> : null}
      {data ? <>
        <p className="font-medium">{str(data.basis.risk.title)} · 当前风险版本 {str(data.basis.risk.updated_at)}</p>
        <p>{data.basis.references.map(g => `${g.label} ${g.items.length} 条`).join("；")}</p>
        {data.recent.length ? <details><summary className="cursor-pointer">已有处理任务（最近{data.recent.length}条{data.has_more ? "，更多任务见业务引用" : ""}）</summary><div className="mt-2 space-y-2">{data.recent.map(receipt)}</div></details> : null}
        {!data.can_create ? <p>当前风险状态或本人权限不允许安排新任务。</p> : <form onSubmit={e => {
          e.preventDefault();
          const { reason, ...newTask } = draft;
          setPreview({ request_id: crypto.randomUUID(), expected_digest: data.digest, reason, new_task: newTask });
        }} className="space-y-3">
          <fieldset disabled={busy || !!preview || !!pending} className="space-y-3 disabled:opacity-60">
            <label className="block">处理依据 / 需要纠正的影响<textarea className={control} required maxLength={4000} value={draft.reason} onChange={e => setDraft({ ...draft, reason: e.target.value })} /></label>
            <label className="block">任务标题<input className={control} required maxLength={512} value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} /></label>
            <label className="block">具体工作范围<textarea className={control} required maxLength={10000} value={draft.description} onChange={e => setDraft({ ...draft, description: e.target.value })} /></label>
            <div className="grid gap-3 sm:grid-cols-2"><label>具名负责人<select className={control} required value={draft.assignee_user_id} onChange={e => setDraft({ ...draft, assignee_user_id: e.target.value })}><option value="">选择本项目成员</option>{data.people.map(p => <option key={p.id} value={p.id}>{p.display_name}</option>)}</select></label><label>执行阶段<select className={control} required value={draft.stage_id} onChange={e => setDraft({ ...draft, stage_id: e.target.value })}><option value="">选择阶段</option>{data.stages.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label></div>
            <label className="block">完成日期<input type="date" className={control} required value={draft.due_date} onChange={e => setDraft({ ...draft, due_date: e.target.value })} /></label>
            <label className="block">预期输出和验收要求<textarea className={control} required maxLength={10000} value={draft.expected_output} onChange={e => setDraft({ ...draft, expected_output: e.target.value })} /></label>
            <Button type="submit" size="sm">预览任务安排</Button>
          </fieldset>
        </form>}
      </> : null}
      {preview && data ? <div className="space-y-2 rounded-lg border border-primary/40 p-3" role="region" aria-label="风险处理任务预览">
        <p className="font-medium">将创建：{preview.new_task.title}</p><p>负责人：{data.people.find(p => p.id === preview.new_task.assignee_user_id)?.display_name} · 完成日期：{preview.new_task.due_date}</p>
        <p>工作范围：{preview.new_task.description}</p><p>交付要求：{preview.new_task.expected_output}</p><p>处理依据：{preview.reason}</p>
        <p className="text-muted-foreground">确认时重核风险和引用范围，变化后须刷新。已有任务请优先继续原任务。</p>
        <div className="flex gap-2"><Button type="button" size="sm" disabled={busy || !!pending} onClick={() => void submit(preview)}>确认安排实际任务</Button><Button type="button" size="sm" variant="outline" disabled={busy || !!pending} onClick={() => setPreview(null)}>返回修改</Button></div>
      </div> : null}
      {pending ? <div className="space-y-2 rounded-lg border p-3"><p>请求结果待确认：{pending.request_id}</p><div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void read()}>回查结果</Button><Button type="button" size="sm" disabled={busy} onClick={() => void submit(pending, true)}>用原请求重试</Button></div></div> : null}
      {result ? receipt(result) : null}
      <div className="flex flex-wrap items-end gap-2"><label className="min-w-48 flex-1">按本人请求编号回查<input className={control} value={lookup} disabled={busy || !!pending} onChange={e => setLookup(e.target.value)} /></label><Button type="button" size="sm" variant="outline" disabled={busy || !lookup.trim()} onClick={() => void read()}>回查任务</Button></div>
    </div>
  </details>;
}
