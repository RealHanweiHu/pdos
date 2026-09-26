"use client";

import { useRef, useState } from "react";
import { DecisionIntakeConfirmation } from "@/components/ai/decision-intake-confirmation";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const columns: Record<string, string> = { title: "决策标题", outcome: "原文结论", context: "背景", options: "考虑过的选项原文", trade_offs: "权衡", rationale: "理由", consequence: "后果及后续要求", historical_date: "历史日期", historical_approver: "原文批准人", historical_owner: "原文负责人", historical_kind: "原文决策类型", historical_state: "原文办理状态", external_ref: "原决策编号", issue_ref: "原问题编号或说明" };
const initialColumns: Record<string, string> = Object.fromEntries(Object.keys(columns).map(key => [key, key === "title" ? "A" : key === "outcome" ? "B" : ""]));
const field = "w-full rounded-md border bg-background p-2 text-sm";
function obj(value: unknown): Row { if (!isRecord(value)) throw new Error("历史决策资料不完整"); return value; }
function rows(value: unknown): Row[] { if (!Array.isArray(value)) throw new Error("历史决策清单不完整"); return value.map(obj); }
function text(value: unknown): string { return value == null || value === "" ? "未提供" : typeof value === "object" ? JSON.stringify(value) : String(value); }
function string(value: unknown): string { return value == null ? "" : String(value); }
export function ConversationDecisionIntake({ conversationId, messageId, archived }: { conversationId: string; messageId: string; archived: boolean }) {
  const [index, setIndex] = useState<Row | null>(null), [preview, setPreview] = useState<Row | null>(null), [page, setPage] = useState(0);
  const [attachment, setAttachment] = useState(""), [sheet, setSheet] = useState(""), [first, setFirst] = useState(2), [last, setLast] = useState(20), [format, setFormat] = useState("YYYY-MM-DD"), [mapping, setMapping] = useState(initialColumns);
  const [permission, setPermission] = useState(""), [purpose, setPurpose] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const base = `/api/conversations/${conversationId}`, listPath = `/messages/${messageId}/decision-intake-previews`;
  async function request(path: string, body?: object) {
    const response = await fetch(`${base}${path}`, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" }), value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "历史决策草稿暂不可用，请保留输入后重试");
    return obj(value);
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "历史决策资料读取失败"); } finally { setBusy(false); } }
  async function load() { setIndex(await request(listPath)); }
  async function open(id: string) { setPreview(await request(`/decision-intake-previews/${id}`)); setPage(0); }
  const sources = index ? rows(index.sources) : [], selected = sources.find(source => source.id === attachment);
  const sheets = selected && Array.isArray(selected.sheets) ? selected.sheets.map(String) : [];
  const valid = !!attachment && sheets.includes(sheet) && !!permission.trim() && !!purpose.trim() && Number.isInteger(first) && Number.isInteger(last) && first >= 1 && last >= first && last <= 1048576 && last - first < 200 && Object.entries(mapping).every(([key, value]) => value ? /^[A-Z]{1,3}$/.test(value) : !["title", "outcome"].includes(key));
  async function prepare() {
    if (!valid) return;
    const body = { attachment_id: attachment, permission_basis: permission.trim(), purpose: purpose.trim(), mapping: { sheet, first_row: first, last_row: last, date_format: format, ...Object.fromEntries(Object.entries(mapping).map(([key, value]) => [key, value || null])) } }, signature = JSON.stringify(body);
    if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    const value = await request(listPath, { ...body, request_id: pending.current.id }); pending.current = null; setPreview(value); setPage(0); await load();
  }
  function copyMapping() {
    if (!preview) return;
    const old = obj(preview.mapping);
    setAttachment(string(preview.attachment_id)); setSheet(string(old.sheet)); setFirst(Number(old.first_row)); setLast(Number(old.last_row)); setFormat(string(old.date_format));
    setMapping(Object.fromEntries(Object.keys(columns).map(key => [key, string(old[key])]))); setPermission(string(preview.permission_basis)); setPurpose(string(preview.purpose)); pending.current = null;
  }
  const entries = preview ? rows(preview.rows) : [];
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !index && !busy) void act(load); }}>
    <summary className="cursor-pointer text-sm font-medium">准备历史决策清单</summary>
    <div className="mt-3 space-y-3 text-xs">
      <p>从本条消息的XLSX原件选择列和行范围，保存原文与映射版本。原文人员、日期和办理状态分别保留；缺项不补造，人员姓名不自动匹配为当前批准人。</p>
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>刷新附件与最近草稿</Button>
      {index && !sources.length && <p>本条消息暂无可用的内部XLSX抽取结果，请先在附件区上传并完成抽取。</p>}
      {index && rows(index.items).length > 0 && <details><summary className="cursor-pointer">最近100份映射草稿</summary><div className="mt-2 space-y-2">{rows(index.items).map(item => <div key={text(item.id)} className="flex flex-wrap items-center gap-2"><span>{text(item.created_at)} · {text(obj(item.mapping).sheet)} · 第 {text(obj(item.mapping).first_row)}–{text(obj(item.mapping).last_row)} 行 · {text(item.purpose)}</span><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => open(text(item.id)))}>读取原草稿</Button></div>)}</div></details>}
      {sources.length > 0 && <fieldset disabled={busy || archived} className="space-y-3">
        <div className="grid gap-2 sm:grid-cols-2"><label>本条消息的原件<select className={field} value={attachment} onChange={e => { const id = e.target.value, source = sources.find(item => item.id === id); setAttachment(id); setSheet(source && Array.isArray(source.sheets) ? String(source.sheets[0] ?? "") : ""); }}><option value="">选择已抽取的原件</option>{sources.map(source => <option key={text(source.id)} value={text(source.id)}>{text(source.filename)}</option>)}</select></label><label>工作表<select className={field} value={sheet} onChange={e => setSheet(e.target.value)}><option value="">选择工作表</option>{sheets.map(name => <option key={name} value={name}>{name}</option>)}</select></label><label>开始行<input className={field} type="number" min={1} max={1048576} value={first} onChange={e => setFirst(Number(e.target.value))}/></label><label>结束行<input className={field} type="number" min={1} max={1048576} value={last} onChange={e => setLast(Number(e.target.value))}/></label></div>
        <p>每份草稿最多200行。填写原件列字母；标题和结论必须映射，其余可留空并保留为缺项。</p>
        <div className="grid gap-2 sm:grid-cols-3">{Object.entries(columns).map(([key, label]) => <label key={key}>{label}{["title", "outcome"].includes(key) ? "（必填列）" : ""}<input className={field} maxLength={3} value={mapping[key]} onChange={e => setMapping(old => ({ ...old, [key]: e.target.value.toUpperCase().trim() }))}/></label>)}</div>
        <label className="block">原文日期格式<select className={field} value={format} onChange={e => setFormat(e.target.value)}>{["YYYY-MM-DD", "YYYY/MM/DD", "DD/MM/YYYY", "MM/DD/YYYY"].map(value => <option key={value}>{value}</option>)}</select></label>
        <label className="block">使用这份资料的许可依据<textarea maxLength={2000} className={field} value={permission} onChange={e => setPermission(e.target.value)}/></label><label className="block">本次整理用途<textarea maxLength={2000} className={field} value={purpose} onChange={e => setPurpose(e.target.value)}/></label>
        <Button type="button" disabled={!valid} onClick={() => void act(prepare)}>保存原值映射草稿</Button>
      </fieldset>}
      {preview && <section className="space-y-3 rounded-md border p-3">
        <p className="font-medium">历史原值草稿 · {text(obj(preview.source_snapshot).filename)} · {entries.length} 行 · 登记情况见下方回执</p><p>保存于 {text(preview.created_at)}。这不是历史决策日期，也不是本次批准时间。</p>
        {preview.source_current !== true && <p className="text-destructive">原附件已变化或停止引用。草稿原值保留，请重新核对来源。</p>}
        <p className="whitespace-pre-wrap">许可依据：{text(preview.permission_basis)}<br/>整理用途：{text(preview.purpose)}</p>
        <Button type="button" size="sm" variant="outline" disabled={busy || archived} onClick={copyMapping}>载入此映射继续调整</Button>
        {entries.slice(page * 20, page * 20 + 20).map(row => { const original = obj(row.original), values = obj(row.values); return <article key={text(row.row)} className="space-y-2 rounded-md border p-3"><p className="font-medium">第 {text(row.row)} 行 · {text(values.title)}</p><p className="whitespace-pre-wrap">原文结论：{text(values.outcome)}</p><p>历史日期：{text(row.historical_date)} · 原文批准人：{text(values.historical_approver)} · 原文负责人：{text(values.historical_owner)}</p><p>原文决策编号：{text(values.external_ref)} · 原问题编号/说明：{text(values.issue_ref)}</p>
          {Array.isArray(row.errors) && row.errors.map((value, i) => <p key={i} className="text-destructive">{text(value)}</p>)}{Array.isArray(row.gaps) && row.gaps.length > 0 && <p className="text-muted-foreground">未提供：{row.gaps.map(value => columns[String(value)] ?? String(value)).join("、")}</p>}
          <details><summary className="cursor-pointer">逐字段原文与单元格位置</summary><dl className="mt-2 space-y-2">{Object.entries(original).map(([key, value]) => { const cell = obj(value); return <div key={key}><dt className="font-medium">{columns[key] ?? key} · {text(cell.cell)}</dt><dd className="max-h-48 overflow-auto whitespace-pre-wrap break-words">{text(cell.value)}</dd></div>; })}</dl></details>
        </article>; })}
        {entries.length > 20 && <div className="flex items-center gap-2"><Button type="button" size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(old => old - 1)}>上一页原值</Button><span>{page + 1} / {Math.ceil(entries.length / 20)}</span><Button type="button" size="sm" variant="outline" disabled={(page + 1) * 20 >= entries.length} onClick={() => setPage(old => old + 1)}>下一页原值</Button></div>}
        <DecisionIntakeConfirmation key={text(preview.id)} preview={preview} disabled={busy} readOnly={archived} act={act} request={request} reload={() => open(text(preview.id))}/>
      </section>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
