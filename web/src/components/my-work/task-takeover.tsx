"use client";

import { TaskTakeoverKnowledge, type KnowledgeReference, type KnowledgeChoice } from "./task-takeover-knowledge";
import { TaskTakeoverResiduals, type Residual } from "./task-takeover-residuals";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const row = (v: unknown): Row => isRecord(v) ? v : {};
const text = (v: unknown) => v == null ? "" : String(v);
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const sections = { goal: "目标与预期输出", constraints: "有效约束与完成标准", confirmed_facts: "已确认事实及原依据", open_items: "遗留项与具名责任", next_steps: "下一步与接续位置" };
const actions: Record<string, string> = { submitted: "待接收", accepted: "已接收", returned: "退回补齐" };
class PacketError extends Error { constructor(message: string, public status: number) { super(message); } }
export function TaskTakeover({ projectId, taskId, onChanged, initiallyOpen = false }: { projectId: string; taskId: string; onChanged?: () => void; initiallyOpen?: boolean }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [content, setContent] = useState<Record<string, string>>({}), [note, setNote] = useState(""), [checked, setChecked] = useState<string[]>([]);
  const [preview, setPreview] = useState<Row | null>(null), [pending, setPending] = useState<Row | null>(null), [saved, setSaved] = useState<Row | null>(null);
  const [residuals, setResiduals] = useState<Residual[] | null>(null), [checkedResiduals, setCheckedResiduals] = useState<string[]>([]);
  const [knowledge, setKnowledge] = useState<KnowledgeReference[] | null>(null), [checkedKnowledge, setCheckedKnowledge] = useState<string[]>([]);
  const [older, setOlder] = useState<Row[]>([]), [historyCursor, setHistoryCursor] = useState<number | null>(null);
  const base = `/api/projects/${projectId}/tasks/${taskId}/takeover`;
  async function request(body?: Row, requestId?: string): Promise<Row> {
    const response = await fetch(`${base}${requestId ? `?request_id=${requestId}` : ""}`, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
    const value = await responseBody(response);
    if (!response.ok) throw new PacketError(text(row(row(value).detail).message) || "未取得交接回执，请按原请求回查", response.status);
    if (!isRecord(value)) throw new Error("交接内容不完整");
    return value;
  }
  async function load() {
    setBusy(true); setError(""); setPreview(null); setChecked([]); setCheckedResiduals([]); setCheckedKnowledge([]);
    try {
      const value = await request();
      if (typeof value.digest !== "string" || !isRecord(value.source) || !Array.isArray(value.history)) throw new Error("交接依据不完整，请刷新");
      setData(value); setOlder([]); setHistoryCursor(typeof value.next_before_revision === "number" ? value.next_before_revision : null);
      setResiduals(old => old ?? rows(value.residual_sources).map(item => ({ kind: text(item.kind), id: text(item.id), expected_digest: text(item.expected_digest), note: text(item.note), snapshot: row(item.snapshot), changed: item.changed === true })));
      setKnowledge(old => old ?? rows(value.knowledge_sources).map(item => ({ push_id: text(item.push_id), content_sha256: text(item.content_sha256), note: text(item.note) })));
      const source = row(value.source), draft = row(row(row(value.submission).payload).content);
      setContent(old => Object.fromEntries(Object.keys(sections).map(key => [key, old[key] ?? (typeof draft[key] === "string" ? draft[key] : key === "goal" ? [text(row(source.task).title), text(source.expected_output)].filter(Boolean).join("\n") : key === "constraints" ? text(source.completion_criteria) : "")])));
    } catch (e) { setData(null); setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  async function save(body: Row, lookup = false) {
    setPending(body); setBusy(true); setError("");
    try {
      const value = await request(lookup ? undefined : body, lookup ? text(body.request_id) : undefined);
      if (value.request_id !== body.request_id || typeof value.id !== "string") throw new Error("回执不完整，请回查原请求");
      setSaved(value); setPending(null); setPreview(null); setNote(""); onChanged?.(); await load();
    } catch (e) {
      if (!lookup && e instanceof PacketError && [400, 401, 403, 409, 422].includes(e.status)) { setPending(null); setPreview(null); setData(null); }
      setError(e instanceof Error ? e.message : "提交结果不确定");
    } finally { setBusy(false); }
  }
  function prepare(action: string) {
    setPreview({ request_id: crypto.randomUUID(), expected_digest: data?.digest, action, note: note.trim(), ...(action === "submitted" ? { content, knowledge: knowledge ?? [], residuals: (residuals ?? []).map(({ kind, id, expected_digest, note }) => ({ kind, id, expected_digest, note })) } : { submission_id: row(data?.latest).id, checked_sections: checked, checked_residuals: checkedResiduals, checked_knowledge: checkedKnowledge }) });
  }
  function packet(value: Row) {
    const payload = row(value.payload), facts = row(payload.content), source = row(value.basis);
    return <div className="space-y-2 rounded-md border p-3" key={text(value.id)}><p className="font-medium">第{text(value.revision)}版 · {actions[text(value.action)]} · {text(payload.actor_name)} → {text(payload.receiver_name)}</p><p>{text(value.created_at)} · {text(payload.note)}</p>
      {rows(payload.residual_sources).map(item => <div className="rounded-md border p-2" key={`${item.kind}:${item.id}`}><Link className="text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${item.id}`}>{text(row(item.snapshot).title)}</Link><p>交接时：{text(row(item.snapshot).owner_name) || "未指定"} · {text(row(item.snapshot).due_date) || "未设期限"} · {text(row(item.snapshot).status)}</p><p>{text(item.note)}</p></div>)}
      {rows(payload.knowledge_sources).map((item, index) => <div className="rounded-md border p-2" key={text(item.push_id)}><p>关联经验 {index + 1} · 原采用回执：{text(item.feedback_id)}</p><p className="break-all text-muted-foreground">固定版本：{text(item.content_sha256)}</p><p className="whitespace-pre-wrap">{text(item.note)}</p></div>)}
      {value.action === "submitted" ? <><p>固定任务：{text(row(source.task).title)} · {source.plan ? `正式基线 v${text(row(source.plan).baseline_version)}` : "未绑定正式基线"}</p><p>当时预期输出：{text(source.expected_output) || "待补齐"}</p><p>当时完成标准：{text(source.completion_criteria) || "待补齐"}</p>{Object.entries(sections).map(([key, label]) => <div key={key}><strong>{label}</strong><p className="whitespace-pre-wrap">{text(facts[key])}</p></div>)}</> : null}</div>;
  }
  async function loadEarlier() {
    if (busy || historyCursor === null) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`${base}/history?before_revision=${historyCursor}`, { cache: "no-store" });
      const value = await responseBody(response);
      if (!response.ok || !isRecord(value) || !Array.isArray(value.items) || !(value.next_before_revision === null || typeof value.next_before_revision === "number")) throw new Error("更早交接记录暂不可读取，请重试");
      setOlder(previous => [...previous, ...rows(value.items)]); setHistoryCursor(value.next_before_revision);
    } catch (e) { setError(e instanceof Error ? e.message : "历史读取失败"); }
    finally { setBusy(false); }
  }
  const submission = row(data?.submission);
  const residualViews = rows(data?.residual_sources);
  const knowledgeViews = rows(data?.knowledge_sources);
  const knowledgeChoices: KnowledgeChoice[] = rows(row(data?.knowledge_options).items).filter(item => ["push_id", "content_sha256", "title", "href"].every(key => typeof item[key] === "string") && text(item.href).startsWith("/knowledge?")).map(item => ({ push_id: text(item.push_id), content_sha256: text(item.content_sha256), note: "", title: text(item.title), href: text(item.href), applicability: text(item.applicability) }));
  const validKnowledge = (knowledge ?? []).every(item => item.note.trim() && knowledgeChoices.some(choice => choice.push_id === item.push_id && choice.content_sha256 === item.content_sha256));
  const validResiduals = (residuals ?? []).every(item => item.note.trim() && !item.changed);
  return <details open={initiallyOpen || undefined} className="rounded-lg border p-3 text-xs" onToggle={e => { if (e.target === e.currentTarget && e.currentTarget.open && !data && !busy && !pending) void load(); }}>
    <summary className="cursor-pointer font-medium">持久交接包 / 接收与退回</summary>
    <div className="mt-3 space-y-3"><p className="text-muted-foreground">由交付人整理给当前任务负责人。保存后可重新打开接续；接收确认资料交接，原任务完成与正式计划、专业交付验收继续按原流程办理。有交接包的任务需当前负责人接收后才能完成。</p>
      <Button type="button" size="sm" variant="outline" disabled={busy || !!pending} onClick={() => void load()}>刷新当前交接依据</Button>
      {error ? <p role="alert" className="text-destructive">{error}</p> : null}
      {saved ? <p role="status">交接回执已保存：{actions[text(saved.action)]} · 第{text(saved.revision)}版</p> : null}
      {submission.id ? packet(submission) : null}
      {data?.residuals_changed === true ? <p className="text-destructive">实际遗留项已变化，接收前需交付人补齐新版。</p> : null}
      {residualViews.map(item => <p key={`${item.kind}:${item.id}`}>当前遗留项：{text(row(item.current).title) || "当前不可读取"} · {text(row(item.current).owner_name) || "负责人待补齐"} · {text(row(item.current).due_date) || "期限待补齐"} · {text(row(item.current).status)}</p>)}
      {knowledgeViews.length ? <section className="space-y-2 rounded-md border p-3"><p className="font-medium">当前关联经验</p>{knowledgeViews.map((item, index) => <div key={text(item.push_id)}>{item.available === true && text(item.href).startsWith("/knowledge?") ? <><Link className="text-primary underline" href={text(item.href)}>{text(item.title)}</Link><p>{text(item.applicability)}</p></> : <p className="text-destructive">经验 {index + 1} 当前不可读取或依据已变化，接收前请退回补齐。</p>}<p className="whitespace-pre-wrap">本任务适用说明：{text(item.note)}</p></div>)}</section> : null}
      {data?.source_changed === true ? <p className="text-destructive">原交接依据已有变化，接收前需交付人补齐新版。</p> : null}
      {data?.can_submit === true && !pending ? <form onSubmit={e => { e.preventDefault(); prepare("submitted"); }} className="space-y-2"><fieldset disabled={busy || !!preview} className="space-y-2">{Object.entries(sections).map(([key, label]) => <label className="block" key={key}>{label}<textarea required maxLength={key === "confirmed_facts" || key === "open_items" ? 10000 : 5000} className="mt-1 w-full rounded-md border bg-background p-2 text-sm" value={content[key] ?? ""} onChange={e => setContent(old => ({ ...old, [key]: e.target.value }))}/></label>)}<TaskTakeoverResiduals base={base} values={residuals ?? []} onChange={setResiduals} disabled={busy || !!preview}/><TaskTakeoverKnowledge choices={knowledgeChoices} values={knowledge ?? []} onChange={setKnowledge} disabled={busy || !!preview} hasMore={row(data?.knowledge_options).has_more === true}/><label className="block">本次交接／补齐说明<textarea required maxLength={4000} className="mt-1 w-full rounded-md border bg-background p-2" value={note} onChange={e => setNote(e.target.value)}/></label><Button type="submit" size="sm" disabled={!validResiduals || !validKnowledge}>预览交接包</Button></fieldset></form> : null}
      {data?.can_review === true && !pending ? <fieldset disabled={busy || !!preview} className="space-y-2">{Object.entries(sections).map(([key, label]) => <label className="flex gap-2" key={key}><input type="checkbox" checked={checked.includes(key)} onChange={e => setChecked(old => e.target.checked ? [...old, key] : old.filter(value => value !== key))}/>已核对：{label}</label>)}{residualViews.map(item => { const key = `${item.kind}:${item.id}`; return <label className="flex gap-2" key={key}><input type="checkbox" checked={checkedResiduals.includes(key)} onChange={e => setCheckedResiduals(previous => e.target.checked ? [...previous, key] : previous.filter(value => value !== key))}/>已核对遗留项及责任安排：{text(row(item.snapshot).title)}</label>; })}{knowledgeViews.map((item, index) => <label className="flex gap-2" key={text(item.push_id)}><input type="checkbox" disabled={item.available !== true} checked={checkedKnowledge.includes(text(item.push_id))} onChange={e => setCheckedKnowledge(previous => e.target.checked ? [...previous, text(item.push_id)] : previous.filter(value => value !== item.push_id))}/>已核对经验原文、版本和适用说明：{text(item.title) || `经验 ${index + 1}`}</label>)}<label className="block">接收依据／退回待补事项<textarea maxLength={4000} className="mt-1 w-full rounded-md border bg-background p-2" value={note} onChange={e => setNote(e.target.value)}/></label><div className="flex flex-wrap gap-2"><Button type="button" size="sm" disabled={!note.trim() || checked.length !== 5 || data.source_changed === true || data.residuals_changed === true || checkedResiduals.length !== residualViews.length || data.knowledge_unavailable === true || checkedKnowledge.length !== knowledgeViews.length} onClick={() => prepare("accepted")}>预览接收</Button><Button type="button" variant="outline" size="sm" disabled={!note.trim()} onClick={() => prepare("returned")}>预览退回</Button></div></fieldset> : null}
      {preview ? <div className="space-y-2 rounded-md border p-3"><p className="font-medium">将记录：{actions[text(preview.action)]}；{text(preview.note)}</p>{preview.action === "submitted" ? Object.entries(sections).map(([key, label]) => <p className="whitespace-pre-wrap" key={key}>{label}：{text(row(preview.content)[key])}</p>) : null}{preview.action === "submitted" ? (residuals ?? []).map(item => <p key={`${item.kind}:${item.id}`}>关联：{text(item.snapshot.title)} · {text(item.snapshot.owner_name)} · {text(item.snapshot.due_date)}；{item.note}</p>) : null}{preview.action === "submitted" ? rows(preview.knowledge).map(item => <div key={text(item.push_id)}><p>经验：{knowledgeChoices.find(choice => choice.push_id === item.push_id)?.title || "原关联经验"}</p><p className="break-all">固定版本：{text(item.content_sha256)}</p><p className="whitespace-pre-wrap">适用说明：{text(item.note)}</p></div>) : null}<div className="flex gap-2"><Button type="button" size="sm" disabled={busy} onClick={() => void save(preview)}>确认保存</Button><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button></div></div> : null}
      {pending ? <div className="space-y-2"><p className="break-all">待核对请求：{text(pending.request_id)}</p><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void save(pending, true)}>回查原请求</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void save(pending)}>按原内容重试</Button></div> : null}
      {rows(data?.history).length ? <details><summary className="cursor-pointer">交接与接收历史</summary><div className="mt-2 space-y-2">{[...rows(data?.history), ...older].map(packet)}</div>{historyCursor !== null ? <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void loadEarlier()}>加载更早交接记录</Button> : null}</details> : null}
    </div>
  </details>;
}
