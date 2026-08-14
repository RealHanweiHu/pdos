"use client";

import { FileIcon, UploadSimpleIcon } from "@phosphor-icons/react";
import { FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";

import type { ProjectDocument } from "./project-gate-document-types";
import type { WorkItemLoadState } from "./project-workspace-view";

function DocumentState({ onRetry, state }: { onRetry: () => void; state: WorkItemLoadState }) {
  if (state === "loading" || state === "idle") return <p className="rounded-lg border px-4 py-10 text-center text-sm text-muted-foreground">正在加载项目文档…</p>;
  if (state === "error") return <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-8 text-center"><h3 className="font-semibold">项目文档暂不可用</h3><p className="mt-1 text-sm text-muted-foreground">读取失败不会被显示为空文档库。</p><Button className="mt-4 h-11" onClick={onRetry} variant="outline">重新加载文档</Button></div>;
  return null;
}

export function ProjectDocumentPanel({ busy, canUpload, documents, error, onRetry, onUpload, state }: { busy: boolean; canUpload: boolean; documents: ProjectDocument[] | null; error: string | null; onRetry: () => void; onUpload: (file: File, classification: string) => Promise<boolean>; state: WorkItemLoadState }) {
  const [file, setFile] = useState<File | null>(null);
  const [classification, setClassification] = useState("internal");
  if (state !== "ready" || documents === null) return <DocumentState onRetry={onRetry} state={state} />;
  async function submit(event: FormEvent) { event.preventDefault(); if (!file) return; if (await onUpload(file, classification)) setFile(null); }
  return <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
    <section className="rounded-lg border bg-card p-4 sm:p-5"><div><p className="font-mono text-[11px] uppercase tracking-[0.12em] text-primary">Private evidence</p><h3 className="mt-1 font-semibold">项目文档</h3><p className="mt-1 text-sm text-muted-foreground">只展示元数据与抽取状态，不暴露对象存储键。</p></div>{documents.length === 0 ? <div className="mt-5 rounded-lg border border-dashed px-4 py-8 text-center"><FileIcon aria-hidden="true" className="mx-auto size-6 text-muted-foreground" /><h4 className="mt-2 font-medium">尚未上传文档</h4><p className="mt-1 text-sm text-muted-foreground">支持 PDF 与 XLSX，扫描 PDF 会标记等待 OCR。</p></div> : <ul className="mt-4 divide-y rounded-lg border">{documents.map((document) => <li className="flex items-start gap-3 px-3 py-3" key={document.document_id}><FileIcon aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-primary" /><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{document.filename}</p><p className="mt-1 text-xs text-muted-foreground">{document.classification} · {(document.size_bytes / 1024).toFixed(1)} KB · {document.extraction_status === "extracted" ? "已抽取" : "等待 OCR"}</p></div></li>)}</ul>}</section>
    {canUpload ? <form className="rounded-lg border bg-card p-4" onSubmit={submit}><h3 className="font-semibold">上传证据</h3><p className="mt-1 text-sm text-muted-foreground">文件进入项目私有对象存储。</p>{error ? <p className="mt-3 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</p> : null}<label className="mt-4 block text-sm font-medium" htmlFor="project-document-file">PDF / XLSX</label><input accept=".pdf,.xlsx" className="mt-2 block min-h-11 w-full text-sm file:mr-3 file:min-h-11 file:rounded-md file:border file:bg-background file:px-3" id="project-document-file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} type="file" /><label className="mt-4 block text-sm font-medium" htmlFor="project-document-classification">密级</label><select className="mt-2 min-h-11 w-full rounded-md border bg-background px-3 text-sm" id="project-document-classification" onChange={(event) => setClassification(event.target.value)} value={classification}><option value="internal">内部</option><option value="confidential">机密</option><option value="restricted">受限</option></select><Button className="mt-4 h-11 w-full" disabled={busy || !file} type="submit"><UploadSimpleIcon aria-hidden="true" className="size-4" />{busy ? "正在上传…" : "上传并抽取"}</Button></form> : null}
  </div>;
}
