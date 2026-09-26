"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { ConversationIntakeRuns } from "./conversation-intake-runs";
import { AttachmentDetail } from "./conversation-files";
import { EmailExtractionNotice } from "./email-extraction-notice";

type Row = Record<string, unknown>;
type Selection = { attachment_id: string; expected_source_digest: string; first_ordinal: number; last_ordinal: number };
const text = (value: unknown) => value == null ? "" : String(value);
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const strings = (value: unknown): string[] => Array.isArray(value) ? value.map(String) : [];
const kinds: Record<string, string> = { issue: "历史问题资料", decision: "历史决策资料", project_observation: "项目阶段、进展与缺项" };
const field = "w-full rounded-md border bg-background p-2 text-xs";

export function ConversationIntakeAi({ conversationId, messageId, archived }: { conversationId: string; messageId: string; archived: boolean }) {
  const [index, setIndex] = useState<Row | null>(null), [revision, setRevision] = useState(0), [preview, setPreview] = useState<Row | null>(null);
  const [selections, setSelections] = useState<Selection[]>([]), [selectedKinds, setSelectedKinds] = useState(Object.keys(kinds));
  const [instruction, setInstruction] = useState(""), [permission, setPermission] = useState(""), [purpose, setPurpose] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [page, setPage] = useState(0);
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const base = `/api/conversations/${conversationId}`, route = `/messages/${messageId}/intake-ai-sources`;
  async function request(path: string, body?: object): Promise<Row> {
    const response = await fetch(`${base}${path}`, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" });
    const value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && isRecord(value.detail) ? text(value.detail.message) : "整理来源暂不可用，请保留输入后重试");
    return value;
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "未完成"); } finally { setBusy(false); } }
  async function load(older = false) { const value = await request(`${route}${older && index?.next_revision ? `?before_revision=${index.next_revision}` : ""}`); setIndex(old => older ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); if (!older) setRevision(Number(value.latest_revision)); }
  async function open(id: string) { setPreview(await request(`/intake-ai-sources/${id}`)); setPage(0); }
  function add(source: Row) { setSelections(old => [...old, { attachment_id: text(source.id), expected_source_digest: text(source.digest), first_ordinal: 1, last_ordinal: Math.min(Number(source.fragment_count), 10) }]); }
  function change(i: number, value: Partial<Selection>) { setSelections(old => old.map((item, index) => i === index ? { ...item, ...value } : item)); }
  async function save() {
    const body = { expected_revision: revision, instruction: instruction.trim(), permission_basis: permission.trim(), purpose: purpose.trim(), kinds: selectedKinds, selections };
    const signature = JSON.stringify(body); if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    const result = await request(route, { ...body, request_id: pending.current.id }); setPreview(result); setPage(0); pending.current = null; await load();
  }
  function copy() {
    if (!preview || !isRecord(preview.source_snapshot)) return;
    const source = preview.source_snapshot;
    setSelections(rows(source.selections).map(item => ({ attachment_id: text(item.attachment_id), expected_source_digest: text(item.expected_source_digest), first_ordinal: Number(item.first_ordinal), last_ordinal: Number(item.last_ordinal) })));
    setSelectedKinds(strings(source.kinds)); setInstruction(text(source.instruction)); setPermission(text(source.permission_basis)); setPurpose(text(source.purpose)); setRevision(Number(index?.latest_revision)); pending.current = null;
  }
  const snapshot = preview && isRecord(preview.source_snapshot) ? preview.source_snapshot : {}, fragments = rows(snapshot.fragments);
  const sourceRows = isRecord(snapshot.sources) ? Object.entries(snapshot.sources).filter((entry): entry is [string, Row] => isRecord(entry[1])) : [];
  const count = selections.reduce((total, item) => total + Math.max(0, item.last_ordinal - item.first_ordinal + 1), 0);
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !index && !busy) void act(load); }}>
    <summary className="cursor-pointer text-sm font-medium">准备AI整理的原文与要求</summary>
    <div className="mt-3 space-y-3 text-xs">
      <p>可合并本消息多份PDF、表格和授权邮件的所选片段，保留实际页码、单元格或邮件位置。范围外资料保留未知；模型建议后续仍需人工核对及独立确认。</p>
      <p className="text-muted-foreground">{text(index?.generation_message) || "当前可保存整理来源，保存不会自动运行模型。"}</p>
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>读取当前附件与最新要求版本</Button>
      {index && <p>最新要求版本 {text(index.latest_revision)} · 本页续接版本 {revision}。</p>}
      <fieldset disabled={busy || archived || !index} className="space-y-3">
        <div className="flex flex-wrap gap-3">{Object.entries(kinds).map(([key, label]) => <label key={key} className="flex gap-1"><input type="checkbox" checked={selectedKinds.includes(key)} onChange={e => setSelectedKinds(old => e.target.checked ? [...old, key] : old.filter(value => value !== key))}/>{label}</label>)}</div>
        {rows(index?.sources).map(source => <div key={text(source.id)} className="space-y-1 rounded-md border p-2"><p>{text(source.filename)} · 全文件 {text(source.fragment_count)} 个抽取片段、{text(source.characters)} 字符</p><AttachmentDetail conversationId={conversationId} attachmentId={text(source.id)}/><Button type="button" size="sm" variant="outline" disabled={selections.length >= 12} onClick={() => add(source)}>添加原文范围（默认前10段，可改）</Button></div>)}
        {index && !rows(index.sources).length && <p>本消息暂无已抽取且可引用的内部附件，请先完成原文件保存和文字抽取。</p>}
        {selections.map((item, i) => <div key={i} className="space-y-2 rounded-md border p-2"><p>{text(rows(index?.sources).find(source => source.id === item.attachment_id)?.filename) || item.attachment_id}</p><div className="grid grid-cols-2 gap-2"><label>起始片段编号<input className={field} type="number" min={1} value={item.first_ordinal} onChange={e => change(i, { first_ordinal: Number(e.target.value) })}/></label><label>结束片段编号<input className={field} type="number" min={item.first_ordinal} value={item.last_ordinal} onChange={e => change(i, { last_ordinal: Number(e.target.value) })}/></label></div><Button type="button" size="sm" variant="ghost" onClick={() => setSelections(old => old.filter((_, index) => i !== index))}>移除此范围</Button></div>)}
        <p>当前选取 {count} 个片段；每次最多200个片段、18万字符，重叠范围须合并。字数超限会提示调整，不会自动截断原文。</p>
        <label className="block">本次整理要求<textarea className={field} maxLength={4000} value={instruction} onChange={e => setInstruction(e.target.value)}/></label>
        <label className="block">资料使用许可依据<textarea className={field} maxLength={2000} value={permission} onChange={e => setPermission(e.target.value)}/></label>
        <label className="block">本次用途<textarea className={field} maxLength={2000} value={purpose} onChange={e => setPurpose(e.target.value)}/></label>
        <Button type="button" size="sm" disabled={!selections.length || count > 200 || !selectedKinds.length || !instruction.trim() || !permission.trim() || !purpose.trim() || selections.some(item => item.first_ordinal < 1 || item.last_ordinal < item.first_ordinal)} onClick={() => void act(save)}>保存整理要求与原文版本</Button>
      </fieldset>
      {index && <details><summary className="cursor-pointer">已保存的整理要求</summary>{rows(index.items).map(item => <div key={text(item.id)} className="my-2 flex flex-wrap items-center gap-2"><span>版本 {text(item.revision)} · {text(item.purpose)} · {text(item.created_at)}</span><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => open(text(item.id)))}>读取版本</Button></div>)}{index.next_revision != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => load(true))}>更早要求</Button>}</details>}
      {preview && <section className="space-y-2 rounded-md border p-3"><p className="font-medium">已保存要求版本 {text(preview.revision)}</p><p className="whitespace-pre-wrap">{text(snapshot.instruction)}</p><p>范围：{strings(snapshot.kinds).map(kind => kinds[kind]).join("、")} · 实际固定 {fragments.length} 个片段、{text(snapshot.characters)} 字符。</p><p>许可：{text(snapshot.permission_basis)} · 用途：{text(snapshot.purpose)}</p>{preview.source_current !== true && <p className="text-destructive">所选原件状态或版本已变化，不能继续作为当前模型依据。原保存版本保留。</p>}<Button type="button" size="sm" variant="outline" disabled={busy || archived} onClick={copy}>载入此版续改（覆盖上方未保存输入）</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => open(text(preview.id)))}>核对当前来源</Button>
        {sourceRows.map(([id, source]) => { const identity = isRecord(source.identity) ? source.identity : {}; return <div key={id} className="border-t pt-2"><p>{text(identity.filename)} · 本次 {text(source.selected_count)} / 全文件 {text(source.fragment_count)} 个片段。未选范围不参与整理。</p><EmailExtractionNotice metadata={identity.extraction_metadata}/></div>; })}
        <ConversationIntakeRuns key={text(preview.id)} conversationId={conversationId} brief={preview} archived={archived}/>
        <details><summary className="cursor-pointer">查看已固定原文（每页10段）</summary>{fragments.slice(page*10, page*10+10).map(item => <div key={text(item.reference_id)} className="my-2"><p>{text(item.locator)} · 片段 {text(item.ordinal)} · 附件 {text(item.attachment_id)}</p><pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-2">{text(item.text)}</pre></div>)}<div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(old => old-1)}>上一页</Button><Button type="button" size="sm" variant="outline" disabled={(page+1)*10>=fragments.length} onClick={() => setPage(old => old+1)}>下一页</Button></div></details>
      </section>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
