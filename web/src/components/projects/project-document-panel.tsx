"use client";

import { FileIcon, UploadSimpleIcon } from "@phosphor-icons/react";
import { FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { ProjectDocumentPreview } from "./project-document-preview";
import type { ProjectDocument } from "./project-gate-document-types";
import type { WorkItemLoadState } from "./project-workspace-view";

function DocumentState({ onRetry, state }: { onRetry: () => void; state: WorkItemLoadState }) {
  if (state === "loading" || state === "idle") return <p className="rounded-lg border px-4 py-10 text-center text-sm text-muted-foreground">正在加载项目文档…</p>;
  if (state === "error") return <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-8 text-center"><h3 className="font-semibold">项目文档暂不可用</h3><p className="mt-1 text-sm text-muted-foreground">读取失败不会被显示为空文档库。</p><Button className="mt-4 h-11" onClick={onRetry} variant="outline">重新加载文档</Button></div>;
  return null;
}

export function ProjectDocumentPanel({ busy, canUpload, documents, error, onRetry, onUpload, state, focusedDocumentId = null }: { busy: boolean; canUpload: boolean; documents: ProjectDocument[] | null; error: string | null; onRetry: () => void; onUpload: (file: File, classification: string) => Promise<boolean>; state: WorkItemLoadState; focusedDocumentId?: string | null }) {
  const [file, setFile] = useState<File | null>(null), [classification, setClassification] = useState("internal");
  const [selected, setSelected] = useState<string | null>(focusedDocumentId);
  if (state !== "ready" || documents === null) return <DocumentState onRetry={onRetry} state={state} />;
  const current = documents.find(d => d.document_id === selected);
  const pageParam = typeof window === "undefined" ? 1 : Number(new URLSearchParams(window.location.search).get("page"));
  const initialPage = selected === focusedDocumentId && Number.isInteger(pageParam) && pageParam>=1 && pageParam<=500 ? pageParam : 1;
  async function submit(event: FormEvent) { event.preventDefault(); if (!file) return; if (await onUpload(file, classification)) setFile(null); }
  return <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
    <section className="rounded-lg border bg-card p-4 sm:p-5"><h3 className="font-semibold">项目文档</h3><p className="mt-1 text-sm text-muted-foreground">核对原件、查看抽取状态，或选择同格式文件对照。每份文件保留独立身份和内容摘要。</p>
      {documents.length === 0 ? <div className="mt-5 rounded-lg border border-dashed px-4 py-8 text-center"><FileIcon aria-hidden="true" className="mx-auto size-6 text-muted-foreground"/><h4 className="mt-2 font-medium">尚未上传文档</h4><p className="mt-1 text-sm text-muted-foreground">支持 PDF、XLSX、STEP 和 Gerber 单层文件，扫描 PDF 会标记等待文字识别。</p></div> : <ul className="mt-4 divide-y rounded-lg border">{documents.map(document => <li className="flex flex-wrap items-start gap-3 px-3 py-3" key={document.document_id}><FileIcon aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-primary"/><div className="min-w-0 flex-1"><p className="break-all text-sm font-medium">{document.filename}</p><p className="mt-1 text-xs text-muted-foreground">{({internal:"内部",confidential:"机密",restricted:"受限"} as Record<string,string>)[document.classification] ?? document.classification} · {(document.size_bytes/1024).toFixed(1)} KB · {document.extraction_status === "extracted" ? "已抽取" : document.extraction_status === "preview_only" ? "图纸原件 · 未抽取正文" : "等待文字识别"}</p></div><Button type="button" variant="outline" size="sm" onClick={() => setSelected(document.document_id)}>{document.media_type !== "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" ? "预览 / 对照" : "读取原件"}</Button></li>)}</ul>}
    </section>
    {canUpload && <form className="rounded-lg border bg-card p-4" onSubmit={submit}><h3 className="font-semibold">上传证据</h3><p className="mt-1 text-sm text-muted-foreground">每份最多20 MiB，PDF最多500页。STEP/Gerber在本机解析，当前支持单个未压缩原件；照片或扫描页的文字识别尚待接入。</p>{error && <p className="mt-3 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</p>}<label className="mt-4 block text-sm font-medium" htmlFor="project-document-file">PDF / XLSX / STEP / Gerber</label><input accept=".pdf,.xlsx,.step,.stp,.gbr,.ger,.gerber,.gtl,.gbl,.gts,.gbs,.gto,.gbo,.gko,.gm1,.gml" className="mt-2 block min-h-11 w-full text-sm file:mr-3 file:min-h-11 file:rounded-md file:border file:bg-background file:px-3" id="project-document-file" onChange={event => setFile(event.target.files?.[0] ?? null)} type="file"/><label className="mt-4 block text-sm font-medium" htmlFor="project-document-classification">密级</label><select className="mt-2 min-h-11 w-full rounded-md border bg-background px-3 text-sm" id="project-document-classification" onChange={event => setClassification(event.target.value)} value={classification}><option value="internal">内部</option><option value="confidential">机密</option><option value="restricted">受限</option></select><Button className="mt-4 h-11 w-full" disabled={busy || !file} type="submit"><UploadSimpleIcon aria-hidden="true" className="size-4"/>{busy ? "正在上传…" : "保存资料"}</Button></form>}
    {current && <ProjectDocumentPreview key={current.document_id} document={current} documents={documents} initialPage={initialPage} onClose={() => setSelected(null)}/>}
  </div>;
}
