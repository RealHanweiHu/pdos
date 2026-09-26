"use client";

import { useEffect, useState } from "react";
import { MeetingPlanningRuns } from "./meeting-planning-runs";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Kind = "task" | "issue" | "risk" | "decision";
type Source = { kind: Kind; id: string; title: string; digest: string; status: string; href: string; record: Record<string, unknown>; omitted_characters?: Record<string, number> };
type Person = { id: string; display_name: string; participation?: "organizer" | "required" | "optional" };
type Snapshot = { title: string; meeting_type: string; question: string; expected_output: string; timezone: string; proposed_start_at: string | null; proposed_end_at: string | null; participants: Person[]; sources: Source[]; reason: string; missing: string[]; author_name: string; author_id: string };
type Brief = { id: string; root_id: string; version: number; sequence: number; source_snapshot: Snapshot; source_digest: string; created_at: string };
export type MeetingPlanningSelection = { briefId: string; digest: string; label: string; ready: boolean };
type Data = { generation_available: boolean; generation_message: string; request_label: string | null; items: (Pick<Brief, "id" | "root_id" | "version" | "sequence" | "created_at"> & { title: string })[]; record: Brief | null; latest_id: string | null; source_changes: { kind: Kind; id: string; title: string; status: string; current: Source | null }[]; next_before_id: number | null; can_manage: boolean };
type Options = { items: Source[]; next_before: string | null; members: Person[]; actor_id: string; actor_name: string; templates: Record<string, { label: string }> };
type Form = { parent_id: string | null; title: string; meeting_type: string; question: string; expected_output: string; proposed_start_at: string; proposed_end_at: string; participants: { user_id: string; participation: "required" | "optional" }[]; sources: Source[]; reason: string };
type Draft = Omit<Form, "sources" | "proposed_start_at" | "proposed_end_at"> & { request_id: string; timezone: string; proposed_start_at: string | null; proposed_end_at: string | null; sources: { kind: Kind; id: string; expected_digest: string }[] };
const kinds: Record<Kind, string> = { task: "任务", issue: "问题", risk: "已确认风险", decision: "决策" };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const blank: Form = { parent_id: null, title: "", meeting_type: "special", question: "", expected_output: "", proposed_start_at: "", proposed_end_at: "", participants: [], sources: [], reason: "" };
function local(value: string | null) { if (!value) return ""; const date = new Date(value); const pad = (n: number) => String(n).padStart(2, "0"); return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`; }
class RequestError extends Error { constructor(message: string, readonly status: number) { super(message); } }
async function request(path: string, body?: object) {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response);
  if (!response.ok) throw new RequestError(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "请核对当前项目权限及起草资料", response.status);
  if (!isRecord(value)) throw new Error("未取得完整资料，请重试原请求");
  return value;
}
function Summary({ value }: { value: Snapshot }) {
  return <div className="space-y-2"><h5 className="font-medium">{value.title}</h5><p className="whitespace-pre-wrap">要解决的问题：{value.question}</p><p className="whitespace-pre-wrap">预期产出：{value.expected_output}</p><p>拟议时间：{value.proposed_start_at ? new Date(value.proposed_start_at).toLocaleString("zh-CN", { timeZone: value.timezone, timeZoneName: "short" }) : "待核对"} — {value.proposed_end_at ? new Date(value.proposed_end_at).toLocaleString("zh-CN", { timeZone: value.timezone, timeZoneName: "short" }) : "待核对"}</p><p>候选人员：{value.participants.map(p => `${p.display_name}（${p.participation === "organizer" ? "组织者" : p.participation === "required" ? "必需" : "可选"}）`).join("、")}</p>{value.sources.map(s => <details key={`${s.kind}:${s.id}`}><summary>{kinds[s.kind]}：{s.title} · {s.status}</summary><p className="break-all text-xs text-muted-foreground">版本摘要：{s.digest}</p><pre className="max-h-60 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted p-2">{JSON.stringify(s.record, null, 2)}</pre>{s.omitted_characters && Object.keys(s.omitted_characters).length > 0 && <p>所选字段为限定长度摘录；以下字段有未纳入文字：{Object.entries(s.omitted_characters).map(([key, count]) => `${key}（${count}字）`).join("、")}。请沿原业务记录继续核对。</p>}<a className="text-primary underline" href={s.href}>查看当前业务记录</a></details>)}{!!value.missing.length && <p>待补资料：{value.missing.join("；")}</p>}<p>填写人：{value.author_name} · {value.reason}</p></div>;
}

export function MeetingPlanning({ projectId, showRuns = true, initialBriefId, readOnly = false, initialQuestion = "", onSelected, onDraftDirtyChange }: { projectId: string; showRuns?: boolean; initialBriefId?: string; readOnly?: boolean; initialQuestion?: string; onSelected?: (value: MeetingPlanningSelection | null) => void; onDraftDirtyChange?: (dirty: boolean) => void }) {
  const path = `/api/projects/${projectId}/meetings`;
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [data, setData] = useState<Data | null>(null), [options, setOptions] = useState<Options | null>(null);
  const [form, setForm] = useState<Form | null>(null), [preview, setPreview] = useState<{ draft: Draft; snapshot: Snapshot; preview_digest: string } | null>(null), [pending, setPending] = useState(false);
  useEffect(() => { onDraftDirtyChange?.(!!form || !!preview || pending); }, [form, preview, pending, onDraftDirtyChange]);
  const [kind, setKind] = useState<Kind>("issue"), [query, setQuery] = useState("");
  async function load(id?: string, before?: number) {
    onSelected?.(null);
    const params = new URLSearchParams(); if (id) params.set("brief_id", id); if (before) params.set("before_id", String(before));
    const value = await request(`${path}/planning?${params}`);
    if (!Array.isArray(value.items) || typeof value.can_manage !== "boolean") throw new Error("起草资料未完整载入");
    const next = value as Data; setData(prior => before && prior ? { ...next, items: [...prior.items, ...next.items] } : next);
  }
  async function search(before?: string) {
    const params = new URLSearchParams({ kind, q: query }); if (before) params.set("before", before);
    const value = await request(`${path}/planning-options?${params}`);
    if (!Array.isArray(value.items) || !Array.isArray(value.members) || !isRecord(value.templates)) throw new Error("业务选项未完整载入");
    const next = value as Options; setOptions(prior => before && prior ? { ...next, items: [...prior.items, ...next.items] } : next);
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(""); try { await work(); } catch (error) { setError(error instanceof Error ? error.message : "办理未完成"); } finally { setBusy(false); } }
  function edit(brief?: Brief) {
    onSelected?.(null);
    if (!brief) { setForm({ ...blank, question: initialQuestion }); return; }
    const s = brief.source_snapshot;
    setForm({ ...s, parent_id: brief.id, proposed_start_at: local(s.proposed_start_at), proposed_end_at: local(s.proposed_end_at), participants: s.participants.filter(p => p.participation !== "organizer").map(p => ({ user_id: p.id, participation: p.participation === "optional" ? "optional" : "required" })), reason: "" });
  }
  async function prepare() {
    if (!form) return;
    const draft: Draft = { ...form, request_id: crypto.randomUUID(), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, proposed_start_at: form.proposed_start_at ? new Date(form.proposed_start_at).toISOString() : null, proposed_end_at: form.proposed_end_at ? new Date(form.proposed_end_at).toISOString() : null, sources: form.sources.map(s => ({ kind: s.kind, id: s.id, expected_digest: s.digest })) };
    const value = await request(`${path}/planning-preview`, draft);
    if (!isRecord(value.snapshot) || typeof value.preview_digest !== "string") throw new Error("预览未完整返回");
    setPreview({ ...value, draft } as { draft: Draft; snapshot: Snapshot; preview_digest: string });
  }
  async function save() {
    if (!preview) return;
    setPending(true);
    try {
      const value = await request(`${path}/planning`, { ...preview.draft, preview_digest: preview.preview_digest });
      if (value.id !== preview.draft.request_id || typeof value.version !== "number") throw new Error("原保存结果待确认，请重试原请求");
      setPending(false); setPreview(null); setForm(null); await load(String(value.id));
    } catch (error) { if (error instanceof RequestError && [400, 401, 403, 404, 409, 422].includes(error.status)) { setPending(false); setPreview(null); } throw error; }
  }
  const frozen = busy || !!preview || pending;
  return <section className="space-y-3 rounded-md border p-3 text-sm"><Button type="button" size="sm" variant="outline" disabled={frozen || !!form} aria-expanded={open} onClick={() => { setOpen(!open); if (!open) void act(async () => { await load(initialBriefId); await search(); }); }}>临时会议起草资料</Button>{open && <>
    <p>先保存本次问题、预期产出和具名候选，保留所选任务／问题／风险／决策的当前版本。拟议时间和候选名单仍待正式建会前核对。</p>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {data && options && <>
      {!readOnly && !form && !preview && <div className="flex gap-2"><Button type="button" size="sm" disabled={busy || !data.can_manage} onClick={() => edit()}>新建起草资料</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => load())}>我的全部起草版本</Button></div>}
      {form && <fieldset disabled={frozen} className="space-y-3 rounded-md border p-3"><p>本次组织候选：{options.actor_name}（本人）{form.parent_id && " · 修订原资料，新旧版本均保留"}</p><div className="grid gap-3 sm:grid-cols-2"><label>主题<input className={field} maxLength={240} value={form.title} onChange={e => setForm({ ...form, title: e.target.value })}/></label><label>会议类型<select className={field} value={form.meeting_type} onChange={e => setForm({ ...form, meeting_type: e.target.value })}>{Object.entries(options.templates).map(([id, t]) => <option key={id} value={id}>{t.label}</option>)}</select></label></div><label className="block">本次要解决的问题<textarea className={field} maxLength={10000} value={form.question} onChange={e => setForm({ ...form, question: e.target.value })}/></label><label className="block">希望形成的产出<textarea className={field} maxLength={5000} value={form.expected_output} onChange={e => setForm({ ...form, expected_output: e.target.value })}/></label><div className="grid gap-3 sm:grid-cols-2"><label>拟议开始（本机时区，可留空）<input className={field} type="datetime-local" value={form.proposed_start_at} onChange={e => setForm({ ...form, proposed_start_at: e.target.value })}/></label><label>拟议结束（本机时区，可留空）<input className={field} type="datetime-local" value={form.proposed_end_at} onChange={e => setForm({ ...form, proposed_end_at: e.target.value })}/></label></div>
        <details><summary>选择参会候选（已选 {form.participants.length} 人及本人）</summary><div className="max-h-64 overflow-auto">{options.members.filter(p => p.id !== options.actor_id).map(p => <label key={p.id} className="my-2 flex items-center gap-2"><span>{p.display_name}</span><select className="rounded-md border bg-background p-1" value={form.participants.find(item => item.user_id === p.id)?.participation ?? "none"} onChange={e => setForm({ ...form, participants: [...form.participants.filter(item => item.user_id !== p.id), ...(e.target.value === "none" ? [] : [{ user_id: p.id, participation: e.target.value as "required" | "optional" }])] })}><option value="none">不列为候选</option><option value="required">必需</option><option value="optional">可选</option></select></label>)}</div></details>
        {form.participants.map(p => <div key={p.user_id} className="flex items-center gap-2"><span>{options.members.find(m => m.id === p.user_id)?.display_name ?? data.record?.source_snapshot.participants.find(m => m.id === p.user_id)?.display_name ?? p.user_id} · {p.participation === "required" ? "必需" : "可选"}{!options.members.some(m => m.id === p.user_id) && " · 当前不在有效项目名单"}</span><Button type="button" size="sm" variant="ghost" onClick={() => setForm({ ...form, participants: form.participants.filter(m => m.user_id !== p.user_id) })}>移除候选</Button></div>)}
        <div className="space-y-2"><div className="flex flex-wrap items-end gap-2"><label>业务依据<select className={field} value={kind} onChange={e => { setKind(e.target.value as Kind); setOptions({ ...options, items: [], next_before: null }); }}>{Object.entries(kinds).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label><label>标题查找<input className={field} maxLength={200} value={query} onChange={e => { setQuery(e.target.value); setOptions({ ...options, items: [], next_before: null }); }}/></label><Button type="button" size="sm" variant="outline" onClick={() => void act(() => search())}>查找</Button></div><div className="max-h-60 space-y-2 overflow-auto rounded-md border p-2">{options.items.map(s => <label key={`${s.kind}:${s.id}`} className="flex gap-2"><input type="checkbox" checked={form.sources.some(p => p.kind === s.kind && p.id === s.id)} onChange={e => setForm({ ...form, sources: e.target.checked ? [...form.sources, s] : form.sources.filter(p => p.kind !== s.kind || p.id !== s.id) })}/><span>{s.title} · {s.status}</span></label>)}{options.next_before && <Button type="button" size="sm" variant="ghost" onClick={() => void act(() => search(options.next_before ?? undefined))}>更多业务记录</Button>}</div><p>已选 {form.sources.length}/30 项</p>{form.sources.map(s => <div key={`${s.kind}:${s.id}`} className="flex gap-2"><span>{kinds[s.kind]} · {s.title}</span><Button type="button" size="sm" variant="ghost" onClick={() => setForm({ ...form, sources: form.sources.filter(p => p.kind !== s.kind || p.id !== s.id) })}>移除</Button></div>)}</div>
        <label className="block">本次保存或修订说明<input className={field} maxLength={2048} value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })}/></label><Button type="button" size="sm" disabled={!form.title.trim() || !form.question.trim() || !form.expected_output.trim() || !form.reason.trim()} onClick={() => void act(prepare)}>核对本次资料</Button><Button type="button" size="sm" variant="ghost" onClick={() => setForm(null)}>放弃编辑</Button>
      </fieldset>}
      {preview && <div className="space-y-3 rounded-md border p-3"><Summary value={preview.snapshot}/><p>保存为起草资料，不创建会议或通知他人。</p><Button type="button" size="sm" disabled={busy} onClick={() => void act(save)}>{pending ? "核对原保存请求" : "确认保存本版资料"}</Button>{!pending && <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button>}</div>}
      {data.record && <article className="space-y-3 rounded-md border p-3"><p>第 {data.record.version} 版 · {new Date(data.record.created_at).toLocaleString()}</p><Summary value={data.record.source_snapshot}/>{data.record.id !== data.latest_id && <p>正在查看历史版本。<Button type="button" size="sm" variant="ghost" disabled={frozen || !!form} onClick={() => void act(() => load(data.latest_id ?? undefined))}>读取最新版</Button></p>}{!!data.source_changes.length && <div><p>相较本版，以下业务来源已变化：</p>{data.source_changes.map(item => <p key={`${item.kind}:${item.id}`}>{item.title} · {item.status === "changed" ? "内容或状态变化" : "当前不可用"}</p>)}<p>修订时请移除旧引用，重新查找并核对当前记录后保存新版本。</p></div>}<Button type="button" size="sm" variant="outline" disabled={readOnly || frozen || !!form || !data.can_manage || data.record.id !== data.latest_id} onClick={() => edit(data.record ?? undefined)}>基于本版修订</Button></article>}
      {showRuns && data.record && <MeetingPlanningRuns key={data.record.id} projectId={projectId} briefId={data.record.id} sourceDigest={data.record.source_digest} canGenerate={data.can_manage && !frozen && !form && data.record.id === data.latest_id && data.source_changes.length === 0} onShowBrief={id => void act(() => load(id))}/>}
      {onSelected && data.record && <div className="space-y-2"><p>{data.generation_message}</p><Button type="button" size="sm" disabled={frozen || !!form || !data.can_manage || data.record.id !== data.latest_id || data.source_changes.length > 0 || !data.request_label} onClick={() => { if (data.record && data.request_label) onSelected({ briefId: data.record.id, digest: data.record.source_digest, label: data.request_label, ready: data.generation_available }); }}>使用此版本作为本条起草要求</Button></div>}
      <details><summary>我的起草版本历史</summary>{!data.items.length && <p>暂无已保存资料。</p>}{data.items.map(item => <div key={item.id} className="my-2 flex flex-wrap items-center gap-2"><span>{item.title} · 第 {item.version} 版 · {new Date(item.created_at).toLocaleString()}</span><Button type="button" size="sm" variant="ghost" disabled={frozen || !!form} onClick={() => void act(() => load(item.id))}>查看资料</Button></div>)}{data.next_before_id && <Button type="button" size="sm" variant="outline" disabled={frozen || !!form} onClick={() => void act(() => load(data.record?.id, data.next_before_id ?? undefined))}>更早版本</Button>}</details>
    </>}
  </>}</section>;
}
