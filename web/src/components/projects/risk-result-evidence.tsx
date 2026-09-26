"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
export type EvidenceFile = { document: Record<string, unknown>; correspondence: string };
type Cursor = { before_created_at: string; before_id: string };
const text = (value: unknown) => value == null ? "" : String(value);
const control = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
export function RiskResultEvidence({ base, files, onChange, disabled }: {
  base: string; files: Record<string, EvidenceFile>; onChange: (files: Record<string, EvidenceFile>) => void; disabled: boolean;
}) {
  const [search, setSearch] = useState(""), [activeSearch, setActiveSearch] = useState(""), [items, setItems] = useState<Record<string, unknown>[]>([]), [next, setNext] = useState<Cursor | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [loaded, setLoaded] = useState(false);
  async function load(cursor?: Cursor) {
    setBusy(true); setError("");
    const term = cursor ? activeSearch : search.trim();
    const query = new URLSearchParams({ search: term, ...(cursor ?? {}) });
    try {
      const response = await fetch(`${base}/evidence?${query}`, { cache: "no-store", credentials: "same-origin" });
      const value = await responseBody(response);
      if (!response.ok || !isRecord(value) || !Array.isArray(value.items) || !value.items.every(d => isRecord(d) && typeof d.id === "string" && typeof d.filename === "string" && typeof d.digest === "string" && typeof d.sha256 === "string" && typeof d.href === "string" && d.href.startsWith("/projects?"))) throw new Error("文件列表暂不可用，请重新查询");
      setItems(value.items); setActiveSearch(term); setLoaded(true);
      setNext(isRecord(value.next) && typeof value.next.before_created_at === "string" && typeof value.next.before_id === "string" ? value.next as Cursor : null);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  function select(document: Record<string, unknown>, checked: boolean) {
    const id = text(document.id);
    if (checked) onChange({ ...files, [id]: { document, correspondence: "" } });
    else onChange(Object.fromEntries(Object.entries(files).filter(([key]) => key !== id)));
  }
  return <section aria-label="固定项目证据文件" className="space-y-3 rounded-lg border p-3">
    <h4 className="font-medium">项目证据文件（最多10份）</h4>
    <p className="text-muted-foreground">选择本项目可读取的内部文件，说明支持哪些结论。至少选一份；“已处理”或“不受影响”的逐项结论还需关联下方所选文件。</p>
    <div className="flex flex-wrap items-end gap-2"><label className="min-w-48 flex-1">文件名搜索<input className={control} value={search} disabled={disabled || busy} onChange={e => setSearch(e.target.value)} /></label><Button type="button" size="sm" variant="outline" disabled={disabled || busy} onClick={() => void load()}>查找文件</Button>{next ? <Button type="button" size="sm" variant="outline" disabled={disabled || busy} onClick={() => void load(next)}>下一批文件</Button> : null}</div>
    {error ? <p role="alert" className="text-destructive">{error}</p> : null}
    {loaded && !items.length ? <p>未找到匹配文件。可在项目文档页登记实际原件后重新查询。</p> : null}
    <ul className="max-h-64 space-y-2 overflow-y-auto">{items.map(document => <li key={text(document.id)} className="flex gap-2"><input type="checkbox" aria-label={`选择证据 ${text(document.filename)}`} checked={!!files[text(document.id)]} disabled={disabled || busy || (!files[text(document.id)] && Object.keys(files).length >= 10)} onChange={e => select(document, e.target.checked)} /><div><Link className="text-primary underline" href={text(document.href)}>{text(document.filename)}</Link><p className="break-all text-muted-foreground">SHA-256：{text(document.sha256)}</p></div></li>)}</ul>
    {Object.entries(files).map(([id, file]) => <div className="space-y-2 rounded-lg border p-3" key={id}><p className="font-medium">已选：{text(file.document.filename)}</p><p className="break-all text-muted-foreground">固定摘要：{text(file.document.sha256)}</p>{file.document.changed === true ? <p className="text-destructive">原文件版本已变化或不可读取，请移除后重新选择。</p> : null}<label className="block">本文件与处理结果的对应关系<textarea className={control} required maxLength={4000} disabled={disabled} value={file.correspondence} onChange={e => onChange({ ...files, [id]: { ...file, correspondence: e.target.value } })} /></label><Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => onChange(Object.fromEntries(Object.entries(files).filter(([key]) => key !== id)))}>移除本次选择</Button></div>)}
  </section>;
}
