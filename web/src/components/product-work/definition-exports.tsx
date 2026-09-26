"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { obj, rows, text, field, type Row } from "@/components/quality/fmea-sources";
import { request } from "./product-work-api";

const formats = { docx: "Word 文档", xlsx: "Excel 工作簿", pptx: "PowerPoint 演示文稿", pdf: "PDF 规格书" };
const states: Record<string, string> = { draft: "草稿", in_review: "协审中", published: "已发布（以当前生效状态为准）" };

export function DefinitionExports({ base, initialDefinitionId = "" }: { base: string; initialDefinitionId?: string }) {
  const [options, setOptions] = useState<Row | null>(null), [definition, setDefinition] = useState(initialDefinitionId);
  const [search, setSearch] = useState(""), [loadedSearch, setLoadedSearch] = useState("");
  const [format, setFormat] = useState<keyof typeof formats>("docx"), [reason, setReason] = useState("");
  const [preview, setPreview] = useState<Row | null>(null), [history, setHistory] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const attempt = useRef<{ key: string; id: string } | null>(null);
  async function act(work: () => Promise<void>) { setBusy(true); setError(""); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "导出暂不可用"); } finally { setBusy(false); } }
  async function loadOptions(before?: string) {
    const query = before ? loadedSearch : search;
    const value = await request<Row>(base + "/definition-export-options", "POST", { search: query, before_id: before ?? null });
    setOptions(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); setLoadedSearch(query);
  }
  async function loadHistory(before?: string) {
    const value = await request<Row>(base + "/definition-export-history", "POST", { definition_id: definition, before_id: before ?? null });
    setHistory(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value);
  }
  async function save() {
    const body = { definition_id: definition, format, reason, expected_digest: preview?.digest };
    const key = JSON.stringify(body); if (attempt.current?.key !== key) attempt.current = { key, id: crypto.randomUUID() };
    const saved = await request<Row>(base + "/definition-export-save", "POST", { ...body, request_id: attempt.current.id }); attempt.current = null;
    setNotice("文件已生成并保存原回执，可在历史中下载。文件编号：" + text(saved.id)); setPreview(null); await loadHistory();
  }
  return <section className="space-y-4 rounded-lg border p-4 text-sm"><header><h3 className="text-lg font-semibold">导出中心 · 内部产品规格书</h3><p className="mt-1 text-muted-foreground">选择真实定义版本并核对内容，生成内部使用的文件。文件保留当时状态、原引用和协审历史，草稿与历史版会明确标识。</p></header>
    {error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}
    <form className="space-y-3" onSubmit={event => { event.preventDefault(); void act(async () => { setPreview(await request<Row>(base + "/definition-export-preview", "POST", { definition_id: definition, format, reason })); }); }}><fieldset disabled={busy} className="space-y-3">
      {!initialDefinitionId && <><label className="block">查找产品定义<input className={field} maxLength={128} value={search} onChange={event => setSearch(event.target.value)}/></label><Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadOptions())}>查找实际版本</Button><label className="block">明确选择定义版本<select className={field} required value={definition} onChange={event => { setDefinition(event.target.value); setPreview(null); setHistory(null); setNotice(""); }}><option value="">请选择</option>{rows(options?.items).map(value => <option key={text(value.id)} value={text(value.id)}>{text(value.title)} · 修订 {text(value.revision_number)} / 内容 {text(value.version)} · {states[text(value.state)]}</option>)}</select></label>{options?.next_before_id != null && <Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadOptions(text(options.next_before_id)))}>更多版本</Button>}</>}
      <label className="block">文件格式<select className={field} value={format} onChange={event => { setFormat(event.target.value as keyof typeof formats); setPreview(null); }}>{Object.entries(formats).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label className="block">内部用途与版本选择说明<textarea className={field} required maxLength={2048} value={reason} onChange={event => { setReason(event.target.value); setPreview(null); }}/></label><div className="flex flex-wrap gap-2"><Button disabled={!definition}>预览内容与状态</Button><Button type="button" variant="outline" disabled={!definition} onClick={() => void act(() => loadHistory())}>查看已生成文件</Button></div>
    </fieldset></form>
    {preview && <section className="space-y-3 rounded-md bg-muted/30 p-3"><h4 className="font-semibold">{text(obj(obj(preview.source).definition).title)}</h4><p className="font-medium text-primary">{text(obj(preview.source).status_label)} · {formats[format]} · 内部使用</p><p>包含规格正文、依据和假设、专业协审、此定义发布/撤回历史及原引用；不附证据原文件。</p><div className="max-h-[32rem] space-y-3 overflow-auto">{rows(preview.sections).map((section, index) => <details key={index} className="rounded-md border p-2"><summary className="cursor-pointer font-medium">{text(section.title)}</summary><pre className="mt-2 whitespace-pre-wrap break-words font-sans text-sm">{text(section.text)}</pre></details>)}</div><form className="space-y-3" onSubmit={event => { event.preventDefault(); void act(save); }}><label className="flex items-start gap-2"><input key={text(preview.digest)} type="checkbox" required disabled={busy}/>已核对版本、草稿/生效状态、缺项与内部用途；文件不能作为客户批准、审厂或认证通过证明。</label><Button disabled={busy}>{busy ? "正在生成…" : "生成并保存文件"}</Button></form></section>}
    {history && <section className="space-y-3"><h4 className="font-semibold">已生成文件</h4>{rows(history.items).length === 0 && <p>暂无可读取的导出记录。</p>}{rows(history.items).map(value => <article key={text(value.id)} className="space-y-2 rounded-md border p-3"><h5 className="font-medium">{formats[text(value.format) as keyof typeof formats]} · {new Date(text(value.created_at)).toLocaleString()}</h5><p className="whitespace-pre-wrap">用途：{text(value.reason)}</p>{value.sources_current !== true && <p className="text-primary">当前定义、发布记录或来源已有变化/不可用。此文件保留生成时的固定内容；使用前请核对当前记录。</p>}<a className="inline-flex min-h-11 items-center underline" href={"/api/product-work/" + base + "/definition-exports/" + text(value.id) + "/download"}>下载原文件（{Math.ceil(Number(value.byte_size) / 1024)} KB）</a><details><summary className="cursor-pointer">生成回执</summary><p className="break-all">编号：{text(value.id)}</p><p>记录人：{text(value.actor_user_id)}</p><p className="break-all">文件校验：{text(value.content_digest)}</p><p>模板版本：{text(value.template_version)}</p></details></article>)}{history.next_before_id != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => loadHistory(text(history.next_before_id)))}>更多生成历史</Button>}</section>}
  </section>;
}
