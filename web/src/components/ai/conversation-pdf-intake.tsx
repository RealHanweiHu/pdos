"use client";

import { EmailExtractionNotice } from "./email-extraction-notice";
import { useRef, useState } from "react";
import { DecisionIntakeConfirmation } from "@/components/ai/decision-intake-confirmation";
import { IssueIntakeConfirmation } from "@/components/ai/issue-intake-confirmation";
import type { IntakeSourceRow } from "@/components/ai/issue-intake-reuse";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
type Kind = "issue" | "decision";
type Span = { ordinal: number; start: number; end: number; locator: string; value: string };
type Entry = { anchor: Span | null; fields: Record<string, Span> };
const issueFields = { title: "问题标题", description: "问题描述", external_ref: "原编号", source_state: "原办理状态", root_cause: "原根因", resolution: "原处理措施", target_date: "原到期日期" };
const decisionFields = { title: "决策标题", outcome: "原文结论", context: "背景", options: "考虑过的选项", trade_offs: "权衡", rationale: "理由", consequence: "后果及后续要求", historical_date: "历史日期", historical_approver: "原批准人", historical_owner: "原负责人", historical_kind: "原类型", historical_state: "原状态", external_ref: "原决策编号", issue_ref: "原问题编号或说明" };
const field = "w-full rounded-md border bg-background p-2 text-sm";
function obj(value: unknown): Row { if (!isRecord(value)) throw new Error("资料结构不完整，请重新读取"); return value; }
function list(value: unknown): Row[] { return Array.isArray(value) ? value.map(obj) : []; }
function text(value: unknown): string { return value == null ? "" : String(value); }
function coordinates(span: Span) { return { ordinal: span.ordinal, start: span.start, end: span.end }; }
function savedSpan(value: unknown): Span { const row = obj(value); return { ordinal: Number(row.ordinal), start: Number(row.start), end: Number(row.end), locator: text(row.locator), value: text(row.value) }; }
function issueRow(row: Row): IntakeSourceRow {
  return { row: Number(row.row), errors: Array.isArray(row.errors) ? row.errors.map(String) : ["原值缺失"], proposed: Object.fromEntries(Object.entries(obj(row.proposed)).map(([key, value]) => [key, value == null ? null : String(value)])), historical_state: row.historical_state == null ? null : text(row.historical_state), external_ref: row.external_ref == null ? null : text(row.external_ref) };
}
export function ConversationPdfIntake({ conversationId, messageId, archived, sourceKind = "pdf" }: { conversationId: string; messageId: string; archived: boolean; sourceKind?: "pdf" | "email" }) {
  const sourceLabel = sourceKind === "email" ? "授权邮件" : "PDF";
  const [kind, setKind] = useState<Kind>("issue"), [index, setIndex] = useState<Row | null>(null), [source, setSource] = useState<Row | null>(null);
  const [fragments, setFragments] = useState<Row[]>([]), [after, setAfter] = useState(0), [next, setNext] = useState<number | null>(null), [previous, setPrevious] = useState<number[]>([]);
  const [selection, setSelection] = useState<Span | null>(null), [entries, setEntries] = useState<Entry[]>([]), [active, setActive] = useState(0), [fieldName, setFieldName] = useState("title");
  const [format, setFormat] = useState("YYYY-MM-DD"), [permission, setPermission] = useState(""), [purpose, setPurpose] = useState("");
  const [preview, setPreview] = useState<Row | null>(null), [page, setPage] = useState(0), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const base = `/api/conversations/${conversationId}`, path = `/messages/${messageId}/${sourceKind}-intake-previews`;
  const labels: Record<string, string> = kind === "issue" ? issueFields : decisionFields;
  async function request(route: string, body?: object): Promise<Row> {
    const response = await fetch(`${base}${route}`, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" });
    const value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "资料暂不可用，请保留选段后重试");
    return obj(value);
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); } }
  async function load(selectedKind: Kind = kind) { setIndex(await request(`${path}?kind=${selectedKind}`)); }
  async function read(id: string, cursor = 0) {
    const value = await request(`/attachments/${id}?after_ordinal=${cursor}`);
    if (value.status !== "extracted" || value.revoked_at != null) throw new Error("原附件已停止引用或没有可用文本，请重新核对来源");
    setFragments(list(value.fragments)); setAfter(cursor); setNext(value.next_after == null ? null : Number(value.next_after)); setSelection(null);
  }
  async function choose(id: string) {
    const selected = list(index?.sources).find(item => item.id === id);
    setSource(selected ?? null); setFragments([]); setPrevious([]); setAfter(0); setNext(null); setSelection(null);
    if (selected) await read(id);
  }
  async function open(id: string) { setPreview(await request(`/${kind}-intake-previews/${id}`)); setPage(0); }
  function clearDraft() { setEntries([]); setActive(0); setSelection(null); setSource(null); setFragments([]); setPrevious([]); setNext(null); pending.current = null; }
  function assign(anchor = false) {
    if (!selection) return;
    setEntries(old => { const result = [...old], current = result[active] ?? { anchor: null, fields: {} }; result[active] = anchor ? { ...current, anchor: selection } : { anchor: current.anchor ?? selection, fields: { ...current.fields, [fieldName]: selection } }; return result; });
  }
  async function prepare() {
    if (!source || !entries.length || entries.some(entry => !entry.anchor)) return;
    const body = { kind, attachment_id: source.id, expected_source_digest: source.digest, permission_basis: permission.trim(), purpose: purpose.trim(), date_format: format, entries: entries.map(entry => ({ anchor: coordinates(entry.anchor!), fields: Object.fromEntries(Object.entries(entry.fields).map(([key, value]) => [key, coordinates(value)])) })) };
    const signature = JSON.stringify(body); if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    const value = await request(path, { ...body, request_id: pending.current.id }); setPreview(value); setPage(0); pending.current = null; await load();
  }
  async function copy() {
    if (!preview || entries.length || preview.source_current !== true) return;
    const identity = obj(preview.source_snapshot);
    setSource({ id: preview.attachment_id, filename: identity.filename, digest: preview.source_digest, status: "extracted", source_identity: identity });
    setEntries(list(preview.rows).map(row => ({ anchor: savedSpan(row.anchor), fields: Object.fromEntries(Object.entries(obj(row.original)).map(([key, value]) => [key, savedSpan(value)])) })));
    setPermission(text(preview.permission_basis)); setPurpose(text(preview.purpose)); setFormat(text(obj(preview.mapping).date_format)); setActive(0); setPrevious([]); pending.current = null;
    await read(text(preview.attachment_id));
  }
  const current = entries[active], saved = list(preview?.rows);
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !index && !busy) void act(() => load()); }}>
    <summary className="cursor-pointer text-sm font-medium">从{sourceLabel}原文整理问题或历史决策</summary>
    <div className="mt-3 space-y-3 text-xs">
      <p>{sourceKind === "email" ? "从EML邮件头和正文选中原句，指定字段后保存草稿；保存邮件部分和字符位置，缺项留空。原文发件人不自动匹配为项目批准人。确认共享原件会保存整封邮件，包括原收件人及附带文件，请按许可用途核对。" : "在抽取原文中选中句子，指定字段后保存草稿。仅整理所选片段；缺项留空，扫描件需先完成识别及核对。页码与字符位置按实际抽取片段保存，抽取文本不保留完整排版，确认前请对照原件。"}</p>
      <label className="block">整理为<select className={field} disabled={busy || entries.length > 0} value={kind} onChange={e => { const value = e.target.value as Kind; setKind(value); setPreview(null); setIndex(null); setFieldName("title"); void act(() => load(value)); }}><option value="issue">问题</option><option value="decision">历史决策</option></select></label>
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => load())}>刷新附件与最近草稿</Button>
      {index && <details><summary className="cursor-pointer">最近100份{sourceLabel}草稿（{list(index.items).length}）</summary>{list(index.items).map(item => <div className="my-2 flex flex-wrap items-center gap-2" key={text(item.id)}><span>{text(item.created_at)} · {text(item.purpose)}</span><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => open(text(item.id)))}>查看原草稿</Button></div>)}</details>}
      {index && !list(index.sources).length && <p>本条消息尚无可用的内部{sourceLabel}。请先在附件区上传并抽取文本。</p>}
      <fieldset disabled={busy || archived} className="space-y-3">
        <label className="block">原{sourceLabel}<select className={field} value={text(source?.id)} disabled={entries.length > 0} onChange={e => void act(() => choose(e.target.value))}><option value="">选择原件</option>{list(index?.sources).map(item => <option key={text(item.id)} value={text(item.id)} disabled={item.status !== "extracted"}>{text(item.filename)} · {item.status === "extracted" ? "已抽取" : item.status === "ocr_required" ? "需要识别" : text(item.status)}</option>)}</select></label>
        {source && <EmailExtractionNotice metadata={isRecord(source.source_identity) ? source.source_identity.extraction_metadata : null}/>}
        {source && <p className="break-all text-muted-foreground">本次选段固定来源版本：{text(source.digest)}。如需更换资料或整理类型，请先清空未保存选段。</p>}
        {(source || entries.length > 0) && <Button type="button" variant="outline" size="sm" onClick={clearDraft}>清空本页未保存选段</Button>}
        {fragments.map(fragment => <label className="block" key={text(fragment.ordinal)}>{text(fragment.locator)} · 片段 {text(fragment.ordinal)}<textarea className={`${field} h-40`} readOnly value={text(fragment.text)} onSelect={e => { const element = e.currentTarget, start = Array.from(element.value.slice(0, element.selectionStart)).length, end = Array.from(element.value.slice(0, element.selectionEnd)).length; if (end > start) setSelection({ ordinal: Number(fragment.ordinal), start, end, locator: text(fragment.locator), value: Array.from(element.value).slice(start, end).join("") }); }}/></label>)}
        {source && fragments.length > 0 && <div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={!previous.length} onClick={() => void act(async () => { await read(text(source.id), previous[previous.length - 1]); setPrevious(old => old.slice(0, -1)); })}>上一组原文</Button><Button type="button" size="sm" variant="outline" disabled={next == null} onClick={() => void act(async () => { await read(text(source.id), next!); setPrevious(old => [...old, after]); })}>下一组原文</Button></div>}
        {selection && <div className="space-y-2 rounded-md border p-3"><p>已选 {selection.locator} · 字符 {selection.start + 1}–{selection.end}</p><p className="max-h-32 overflow-auto whitespace-pre-wrap">{selection.value}</p><label>用于当前条目的字段<select className={field} value={fieldName} onChange={e => setFieldName(e.target.value)}>{Object.entries(labels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><div className="flex flex-wrap gap-2"><Button type="button" size="sm" onClick={() => assign()}>采用为{labels[fieldName]}</Button><Button type="button" size="sm" variant="outline" onClick={() => assign(true)}>设为条目主来源位置</Button></div></div>}
        {entries.length > 0 && <section className="space-y-2 rounded-md border p-3"><label>当前草稿条目<select className={field} value={active} onChange={e => setActive(Number(e.target.value))}>{entries.map((entry, i) => <option key={i} value={i}>{i + 1} · {entry.fields.title?.value.slice(0, 70) || "待选择标题"}</option>)}</select></label><p>主来源：{current?.anchor ? `${current.anchor.locator} · 字符 ${current.anchor.start + 1}–${current.anchor.end}` : "尚未选择"}。精确位置相同且字段一致时复用原登记；相近内容需在确认区人工选择已有记录。</p>{Object.entries(current?.fields ?? {}).map(([key, span]) => <div className="space-y-1 border-t pt-2" key={key}><p>{labels[key]} · {span.locator} · 字符 {span.start + 1}–{span.end}</p><p className="max-h-32 overflow-auto whitespace-pre-wrap">{span.value}</p><Button type="button" size="sm" variant="outline" onClick={() => setEntries(old => old.map((entry, i) => i === active ? { ...entry, fields: Object.fromEntries(Object.entries(entry.fields).filter(([name]) => name !== key)) } : entry))}>清除此字段</Button></div>)}<div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="outline" disabled={entries.length >= 200} onClick={() => { setEntries(old => [...old, { anchor: null, fields: {} }]); setActive(entries.length); }}>新增条目</Button><Button type="button" size="sm" variant="outline" onClick={() => { setEntries(old => old.filter((_, i) => i !== active)); setActive(0); }}>移除此条目</Button></div></section>}
        <label className="block">原文日期格式<select className={field} value={format} onChange={e => setFormat(e.target.value)}>{["YYYY-MM-DD", "YYYY/MM/DD", "DD/MM/YYYY", "MM/DD/YYYY", ...(sourceKind === "email" ? ["RFC 5322"] : [])].map(value => <option key={value}>{value}</option>)}</select></label>
        <label className="block">资料使用许可依据<textarea className={field} maxLength={2000} value={permission} onChange={e => setPermission(e.target.value)}/></label><label className="block">整理用途<textarea className={field} maxLength={2000} value={purpose} onChange={e => setPurpose(e.target.value)}/></label>
        <Button type="button" disabled={!source || !entries.length || entries.some(entry => !entry.anchor) || !permission.trim() || !purpose.trim()} onClick={() => void act(prepare)}>保存原文选段草稿</Button>
      </fieldset>
      {preview && <section className="space-y-3 rounded-md border p-3"><h4 className="font-medium">已保存草稿 · {text(obj(preview.source_snapshot).filename)} · {saved.length} 条</h4><p>许可依据：{text(preview.permission_basis)}<br/>整理用途：{text(preview.purpose)}</p>{preview.source_current !== true && <p className="text-destructive">来源已变化或停止引用，原草稿保留；请重新读取核对。</p>}<Button type="button" size="sm" variant="outline" disabled={busy || archived || entries.length > 0 || preview.source_current !== true} onClick={() => void act(copy)}>载入选段继续调整并另存新稿</Button>
        <EmailExtractionNotice metadata={obj(preview.source_snapshot).extraction_metadata}/>
        {sourceKind === "email" && <p>RFC 5322日期按邮件声明的当地日期保存，原时区和完整日期文字保留；不使用本次登记日期替代。</p>}
        {saved.slice(page * 20, page * 20 + 20).map(row => <article className="space-y-2 border-t pt-2" key={text(row.row)}><p>条目 {text(row.row)} · {text(row.locator)}（编号仅为本草稿顺序）</p>{Array.isArray(row.errors) && row.errors.map((value, i) => <p className="text-destructive" key={i}>{text(value)}</p>)}{Array.isArray(row.gaps) && row.gaps.length > 0 && <p>缺项：{row.gaps.map(key => labels[String(key)] ?? String(key)).join("、")}</p>}<details><summary className="cursor-pointer">逐字段原句与实际位置</summary>{Object.entries(obj(row.original)).map(([key, value]) => <div key={key} className="my-2"><p>{labels[key]} · {text(obj(value).cell)}</p><p className="max-h-40 overflow-auto whitespace-pre-wrap">{text(obj(value).value)}</p></div>)}</details></article>)}
        {saved.length > 20 && <div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={!page} onClick={() => setPage(old => old - 1)}>上一页条目</Button><span>{page + 1}/{Math.ceil(saved.length / 20)}</span><Button type="button" size="sm" variant="outline" disabled={(page + 1) * 20 >= saved.length} onClick={() => setPage(old => old + 1)}>下一页条目</Button></div>}
        {kind === "issue" ? <IssueIntakeConfirmation key={text(preview.id)} conversationId={conversationId} previewId={text(preview.id)} digest={text(preview.request_digest)} rows={saved.map(issueRow)} receipts={Array.isArray(preview.confirmation_receipts) ? preview.confirmation_receipts : []} disabled={busy || archived || preview.source_current !== true} onRefresh={() => open(text(preview.id))} onBusyChange={setBusy}/> : <DecisionIntakeConfirmation key={text(preview.id)} preview={preview} disabled={busy} readOnly={archived} act={act} request={request} reload={() => open(text(preview.id))}/>}
      </section>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
