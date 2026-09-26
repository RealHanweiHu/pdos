"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { obj, rows, text, field, type Row } from "@/components/quality/fmea-sources";

const kinds = { "8d": "8D 问题解决报告", dfmea: "DFMEA 设计风险报告", gate: "Gate 签核与裁决", weekly: "项目周报" };
const formats = { docx: "Word", xlsx: "Excel", pptx: "PowerPoint", pdf: "PDF" };

export function ProjectReportExports({ projectId }: { projectId: string }) {
  const [kind, setKind] = useState<keyof typeof kinds>("8d"), [format, setFormat] = useState<keyof typeof formats>("docx");
  const [options, setOptions] = useState<Row | null>(null), [history, setHistory] = useState<Row | null>(null), [preview, setPreview] = useState<Row | null>(null);
  const [object, setObject] = useState(""), [entries, setEntries] = useState<string[]>([]), [search, setSearch] = useState(""), [loadedSearch, setLoadedSearch] = useState("");
  const [start, setStart] = useState(""), [end, setEnd] = useState(""), [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const attempt = useRef<{ key: string; id: string } | null>(null);
  const base = "/api/project-reports/" + projectId;
  async function request(path: string, body: unknown): Promise<Row> {
    const response = await fetch(base + "/" + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    let value: unknown;
    try { value = await response.json(); }
    catch { throw new Error("报表服务暂未返回完整结果。请先查看已生成文件；如未保存，可重试原操作。"); }
    if (!response.ok) throw new Error(text(obj(obj(value).detail).message) || text(obj(value).message) || "报表操作未完成");
    return obj(value);
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(""); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "报表暂不可用"); } finally { setBusy(false); } }
  async function loadOptions(before?: string) {
    const query = before ? loadedSearch : search;
    const value = await request("options", { kind, search: query, before_id: before ?? null });
    setOptions(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); setLoadedSearch(query);
  }
  async function loadHistory(before?: string) { const value = await request("history", { kind, before_id: before ?? null }); setHistory(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); }
  function draft() { return { scope: { kind, object_id: kind === "8d" || kind === "gate" ? object || null : null, entry_ids: kind === "dfmea" ? entries : [], period_start: kind === "weekly" ? start || null : null, period_end: kind === "weekly" ? end || null : null }, format, reason }; }
  async function save() {
    const body = { ...draft(), expected_digest: preview?.digest }, key = JSON.stringify(body);
    if (attempt.current?.key !== key) attempt.current = { key, id: crypto.randomUUID() };
    const saved = await request("save", { ...body, request_id: attempt.current.id }); attempt.current = null;
    setPreview(null); setNotice("文件及原生成回执已保存，可从历史下载。编号 " + text(saved.id)); await loadHistory();
  }
  return <details className="space-y-4 rounded-lg border p-4 text-sm"><summary className="cursor-pointer font-semibold">导出中心 · 项目内部报告</summary><p className="text-muted-foreground">明确选取实际记录或统计窗口，核对缺项后生成内部文件。报告保留生成时状态、原版本及记录人，不代替业务审批、客户批准或认证证明。</p>{error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}
    <form className="space-y-3" onSubmit={event => { event.preventDefault(); void act(async () => setPreview(await request("preview", draft()))); }}><fieldset className="space-y-3" disabled={busy}>
      <div className="grid gap-3 sm:grid-cols-2"><label>模板<select className={field} value={kind} onChange={event => { setKind(event.target.value as keyof typeof kinds); setOptions(null); setObject(""); setEntries([]); setHistory(null); setPreview(null); setNotice(""); }}>{Object.entries(kinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label>文件格式<select className={field} value={format} onChange={event => { setFormat(event.target.value as keyof typeof formats); setPreview(null); }}>{Object.entries(formats).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
      {kind === "weekly" ? <><div className="grid gap-3 sm:grid-cols-2"><label>统计开始日期（UTC）<input className={field} type="date" required value={start} onChange={event => { setStart(event.target.value); setPreview(null); }}/></label><label>统计结束日期（UTC，含当日）<input className={field} type="date" required min={start} value={end} onChange={event => { setEnd(event.target.value); setPreview(null); }}/></label></div><p className="text-muted-foreground">当前模板汇总窗口内任务/问题办理及本次读取的待办；不据内部日期推定客户承诺。</p></> : <>
        <label className="block">查找实际记录<input className={field} value={search} maxLength={128} onChange={event => setSearch(event.target.value)}/></label><Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadOptions())}>查找</Button>
        {kind === "dfmea" ? <div className="space-y-2"><p>已选 {entries.length} 项（最多 100 项）；未选条目不进入报告。</p>{entries.length > 0 && <Button type="button" size="sm" variant="ghost" onClick={() => { setEntries([]); setPreview(null); }}>清空所选</Button>}<div className="max-h-64 space-y-2 overflow-auto">{rows(options?.items).map(value => <label key={text(value.id)} className="flex items-start gap-2 rounded-md border p-2"><input type="checkbox" checked={entries.includes(text(value.id))} disabled={!entries.includes(text(value.id)) && entries.length >= 100} onChange={event => { setEntries(old => event.target.checked ? [...old, text(value.id)] : old.filter(v => v !== value.id)); setPreview(null); }}/><span>{text(value.title)} · 最新修订 {text(value.version)}</span></label>)}</div></div> : <label className="block">选择记录<select className={field} required value={object} onChange={event => { setObject(event.target.value); setPreview(null); }}><option value="">请选择</option>{rows(options?.items).map(value => <option key={text(value.id)} value={text(value.id)}>{text(value.code)} · {text(value.title)} · {text(value.status)}</option>)}</select></label>}
        {options?.next_before_id != null && <Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadOptions(text(options.next_before_id)))}>更多记录</Button>}
      </>}
      <label className="block">内部用途与范围说明<textarea className={field} required maxLength={2048} value={reason} onChange={event => { setReason(event.target.value); setPreview(null); }}/></label><div className="flex flex-wrap gap-2"><Button disabled={kind === "dfmea" && entries.length === 0}>预览报告内容</Button><Button type="button" variant="outline" onClick={() => void act(() => loadHistory())}>已生成文件</Button></div>
    </fieldset></form>
    {preview && <section className="space-y-3 rounded-md bg-muted/30 p-3"><h4 className="font-semibold">{text(obj(preview.source).title)}</h4><p className="text-primary">{text(obj(preview.source).status_label)}</p><div className="max-h-[32rem] space-y-2 overflow-auto">{rows(obj(preview.source).sections).map((part, index) => <details key={index} className="rounded-md border p-2"><summary className="cursor-pointer font-medium">{text(part.title)}</summary><pre className="mt-2 whitespace-pre-wrap break-words font-sans">{text(part.text)}</pre></details>)}</div><form className="space-y-3" onSubmit={event => { event.preventDefault(); void act(save); }}><label className="flex items-start gap-2"><input key={text(preview.digest)} type="checkbox" required disabled={busy}/>已核对所选范围、当前与历史版本、待办及缺项，文件仅作内部使用。</label><Button disabled={busy}>{busy ? "正在生成…" : "生成并保存文件"}</Button></form></section>}
    {history && <section className="space-y-3"><h4 className="font-semibold">{kinds[kind]} · 已生成文件</h4><p className="text-muted-foreground">以下为生成时固定内容，当前业务记录可能已变化；使用前请回查原业务。</p>{rows(history.items).map(value => <article key={text(value.id)} className="space-y-2 rounded-md border p-3"><p>{formats[text(value.format) as keyof typeof formats]} · {new Date(text(value.created_at)).toLocaleString()}</p><p className="whitespace-pre-wrap">{text(value.reason)}</p><a className="inline-flex min-h-11 items-center underline" href={base + "/" + text(value.id) + "/download"}>下载原文件（{Math.ceil(Number(value.byte_size)/1024)} KB）</a><details><summary className="cursor-pointer">生成范围与回执</summary><pre className="whitespace-pre-wrap break-words text-xs">{JSON.stringify({ scope: value.scope, id: value.id, actor: value.actor_user_id, checksum: value.content_digest, template: value.template_version }, null, 2)}</pre></details></article>)}{history.next_before_id != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => loadHistory(text(history.next_before_id)))}>更多生成历史</Button>}</section>}
  </details>;
}
