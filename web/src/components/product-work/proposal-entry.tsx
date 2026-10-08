"use client";

import { useRef, useState } from "react";
import { PaperclipIcon } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ProductRequestError, request, type Evidence, type ProductCatalog } from "./product-work-api";
import { proposalKinds, type Proposal } from "./proposal-types";

export const proposalField = "w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40";
type FileRecord = { id: string; filename: string; status: string; error_code?: string; fragment_count: number };

export function ProposalEntry({ base, lineId, catalog, evidence, onCreated, onError, onPendingChange }: { base: string; lineId: string; catalog: ProductCatalog; evidence: Evidence[]; onCreated: (p: Proposal) => void; onError: (e: unknown) => void; onPendingChange: (v: boolean) => void }) {
  const [kind,setKind] = useState<Proposal["entry_kind"]>("odm"), [files,setFiles] = useState<FileRecord[]>([]);
  const [busy,setBusy] = useState(false), [status,setStatus] = useState("");
  const [uploadPending,setUploadPending] = useState(false);
  const input = useRef<HTMLInputElement>(null), pending = useRef(false);
  const upload = useRef<{ file: File; bytes: ArrayBuffer; digest: string; requestId: string; fileId?: string } | null>(null);
  const original = useRef<{ key: string; id: string } | null>(null);
  async function uploadFile(file?: File) {
    if (pending.current) return;
    pending.current = true; setBusy(true); onPendingChange(true);
    try {
      let current = upload.current;
      if (!current) {
        if (!file || !/\.(pdf|docx?|pptx?|xlsx?)$/i.test(file.name) || !file.size || file.size > 20*1024*1024) throw new Error("请选择20 MiB以内的Word、PowerPoint、Excel或PDF文件。");
        const bytes = await file.arrayBuffer();
        const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)), b => b.toString(16).padStart(2,"0")).join("");
        current = upload.current = { file, bytes, digest, requestId: crypto.randomUUID() };
        setUploadPending(true);
      }
      setStatus("正在上传并读取原文件…");
      if (!current.fileId) {
        const registered = await request<FileRecord>(`${base}/source-files`,"POST",{ request_id:current.requestId,filename:current.file.name,size_bytes:current.file.size,sha256:current.digest,classification:"internal" });
        current.fileId = registered.id;
      }
      const response = await fetch(`/api/product-work/${base}/source-files/${current.fileId}/upload`,{ method:"PUT",body:current.bytes });
      if (!response.ok) { const v = await response.json(); throw new ProductRequestError(v?.detail?.message ?? "上传未确认成功，可重试原文件。",response.status); }
      const parsed = await request<FileRecord>(`${base}/source-files/${current.fileId}/parse`,"POST");
      if (parsed.status !== "extracted") throw new Error(parsed.error_code === "DOCUMENT_CONVERSION_REQUIRED" ? "旧版文件转换不可用，请另存为DOCX、PPTX或XLSX。" : "原文件没有可读文本或解析失败，请提供文字原件或粘贴需求片段。");
      setFiles(v => [...v.filter(f => f.id !== parsed.id),parsed]); upload.current = null; setUploadPending(false);
      setStatus(`已读取 ${parsed.filename}，${parsed.fragment_count} 段原文可引用。`);
    } catch(e) { onError(e); setStatus("文件未完成，可重试原请求或换一个文件。"); }
    finally { pending.current = false; setBusy(false); onPendingChange(false); }
  }
  return <form className="space-y-4 rounded-lg border bg-card p-4 sm:p-6" onSubmit={async event => {
    event.preventDefault(); if (pending.current) return;
    if (!lineId) { onError(new Error("请先选择品类；没有品类时到品类资料新建品类。")); return; }
    const form = new FormData(event.currentTarget);
    const body = { title:String(form.get("title")).trim(),entry_kind:kind,brief:String(form.get("brief") ?? "").trim(),product_line_id:lineId||null,target_regions:String(form.get("regions")??"").split(/[，,\s]+/).filter(Boolean),baseline_product_id:String(form.get("baseline") ?? "") || null,source_file_ids:files.map(f => f.id),evidence_ids:form.getAll("evidence").map(String) };
    const key = JSON.stringify(body);
    if (original.current?.key !== key) original.current = { key,id:crypto.randomUUID() };
    pending.current = true; setBusy(true); onPendingChange(true);
    try {
      const proposal = await request<Proposal>(`${base}/proposals`,"POST",{ ...body,request_id:original.current!.id });
      setStatus("提案已建立，小Pai正在结合原件起草…");
      try {
        await request(`${base}/proposals/${proposal.id}/ai`,"POST",{
          expected_version:proposal.version,payload_digest:proposal.payload_digest,
          idempotency_key:original.current!.id,instruction:proposalKinds[kind].instruction,
        });
      } catch(e) { onError(e); }
      onCreated(proposal);
    }
    catch(e) { onError(e); }
    finally { pending.current = false; setBusy(false); onPendingChange(false); }
  }}><fieldset className="min-w-0 space-y-4" disabled={busy}><legend className="mb-3 text-sm font-medium">这次从哪里开始？</legend><div className="grid gap-2 md:grid-cols-3">{Object.entries(proposalKinds).map(([key,v]) => <label key={key} className={cn("cursor-pointer rounded-lg border p-3",kind === key && "border-primary bg-primary/5")}><span className="flex items-center gap-2"><input type="radio" name="entry" checked={kind === key} onChange={() => setKind(key as Proposal["entry_kind"])}/><span className="text-sm font-medium">{v.label}</span></span><span className="mt-2 block text-xs text-muted-foreground">{v.hint}</span></label>)}</div>
    <p className="text-xs text-muted-foreground">继承 {catalog.nodes.find(n=>n.id===lineId)?.name??"所选品类"} 的规格字典、场景、竞品和地区法规；客户原件仅留在此提案。</p><label className="block space-y-1 text-sm"><span>目标地区代码（留空沿用品类地区）</span><input name="regions" maxLength={512} className={proposalField} placeholder="例如 EU US"/></label><label className="block space-y-1 text-sm"><span>提案名称</span><input name="title" required maxLength={512} className={proposalField} placeholder="例如：面向日常骑行的便携充气泵"/></label>
    <label className="block space-y-1 text-sm"><span>{kind === "odm" ? "客户怎么说？" : kind === "iteration" ? "这次想改什么？" : "准备为谁解决什么问题？"}</span><textarea name="brief" rows={4} required={!files.length} maxLength={16000} className={proposalField} placeholder="直接描述已知需求，无需先整理成规格书。"/></label>
    {kind === "iteration" && <label className="block space-y-1 text-sm"><span>参考原产品（也可上传基线资料）</span><select name="baseline" className={proposalField}><option value="">暂不指定</option>{catalog.nodes.filter(n => n.product_line_id===lineId&&["model","variant"].includes(n.level)).map(n => <option key={n.id} value={n.id}>{n.name} · {n.code}</option>)}</select></label>}
    <div className="space-y-2"><Button type="button" variant="outline" disabled={uploadPending || files.length >= 8} onClick={() => input.current?.click()}><PaperclipIcon aria-hidden="true"/>添加客户文件 / 基线资料</Button><input ref={input} type="file" className="hidden" aria-label="添加提案原文件" accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx" onChange={e => { const f = e.target.files?.[0]; if (f) void uploadFile(f); e.target.value = ""; }}/><p className="text-xs text-muted-foreground">Word、PowerPoint、Excel、PDF · 每份20 MiB以内</p>{files.map(f => <div key={f.id} className="flex items-center justify-between gap-2 text-sm"><span className="truncate">{f.filename} · {f.fragment_count} 段原文</span><Button type="button" variant="ghost" size="sm" onClick={() => setFiles(v => v.filter(i => i.id !== f.id))}>移除引用</Button></div>)}</div>
    {!!evidence.length && <details><summary className="cursor-pointer text-sm text-muted-foreground">引用已有市场证据</summary><div className="mt-2 max-h-48 space-y-2 overflow-auto">{evidence.filter(e => !e.is_stale && !e.superseded && !e.has_conflict).slice(0,40).map(e => <label key={e.id} className="flex items-center gap-2 text-sm"><input name="evidence" type="checkbox" value={e.id}/>{e.name}</label>)}</div></details>}
    <Button disabled={busy || uploadPending || !lineId}>创建并让小Pai起草</Button></fieldset>
    {status && <p role="status" className="text-xs text-muted-foreground">{status}</p>}
    {uploadPending && !busy && <div className="flex gap-2"><Button type="button" variant="outline" size="sm" onClick={() => void uploadFile()}>重试原文件</Button><Button type="button" variant="ghost" size="sm" onClick={() => { upload.current = null; setUploadPending(false); setStatus(""); }}>换一个文件</Button></div>}
  </form>;
}
