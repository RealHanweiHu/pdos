"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ProductAiRuns, type ProductSelection } from "./product-ai-runs";
import { ProductRequestError, request } from "./product-work-api";

type SourceFile = { id: string; filename: string; classification: string; status: string; error_code: string | null; revoked_at: string | null; size_bytes: number; fragment_count: number };
type Read = SourceFile & { fragments: { ordinal: number; locator: string; text: string }[]; next_after: number | null };
type Upload = { bytes: ArrayBuffer; body: { request_id: string; product_line_id: string | null; filename: string; size_bytes: number; sha256: string; classification: string }; stage: "register" | "upload" | "parse"; fileId?: string };
type FileAction = { id: string; action: "parse" | "revoke" };
type Props = { base: string; lineId: string | null; initialRunId?: string; disabled?: boolean; canEdit?: boolean; onPendingChange?: (pending: boolean) => void };
const names: Record<string, string> = { awaiting_upload: "待上传原件", uploaded: "原件已上传", extracted: "已解析原文", ocr_required: "扫描内容待OCR", failed: "解析暂未完成" };
const isDenied = (failure: unknown) => failure instanceof ProductRequestError && [401, 403].includes(failure.status);
const isUncertain = (failure: unknown) => !(failure instanceof ProductRequestError) || failure.status >= 500 || [408, 429].includes(failure.status);

export function ProductSourceFiles(props: Props) {
  return <ProductSourceFilesPanel key={JSON.stringify([props.base, props.lineId])} {...props}/>;
}
function ProductSourceFilesPanel({ base, lineId, initialRunId, disabled = false, canEdit = true, onPendingChange }: Props) {
  const [items, setItems] = useState<SourceFile[]>([]), [truncated, setTruncated] = useState(false);
  const [classification, setClassification] = useState("internal");
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [status, setStatus] = useState("");
  const [denied, setDenied] = useState(false), [authority, setAuthority] = useState(0);
  const [detail, setDetail] = useState<Read | null>(null), [selected, setSelected] = useState<number[]>([]);
  const [prepared, setPrepared] = useState<{ digest: string; selection: ProductSelection } | null>(null);
  const [question, setQuestion] = useState("抽取客户要求，保留单位、工况、验收条件和待澄清项");
  const [uploadPending, setUploadPending] = useState<Upload | null>(null), [actionPending, setActionPending] = useState<FileAction | null>(null);
  const [confirmationPending, setConfirmationPending] = useState(false);
  const [linkedRun, setLinkedRun] = useState<{ id: string; matched: boolean } | null>(null);
  const input = useRef<HTMLInputElement>(null), live = useRef(true), revision = useRef(0), listVersion = useRef(0), working = useRef(false);
  const originalUpload = useRef<Upload | null>(null), originalAction = useRef<FileAction | null>(null), lockCallback = useRef(onPendingChange);
  useEffect(() => { lockCallback.current = onPendingChange; }, [onPendingChange]);
  useEffect(() => { lockCallback.current?.(busy || !!uploadPending || !!actionPending || confirmationPending); }, [busy, uploadPending, actionPending, confirmationPending]);
  useEffect(() => { live.current = true; return () => { live.current = false; revision.current += 1; listVersion.current += 1; originalUpload.current = null; originalAction.current = null; lockCallback.current?.(false); }; }, []);
  const captureAccess = useCallback(() => { const current = revision.current; return () => live.current && revision.current === current; }, []);
  const clearAuthority = useCallback((message: string) => {
    if (!live.current) return;
    revision.current += 1; listVersion.current += 1; working.current = false; originalUpload.current = null; originalAction.current = null;
    setItems([]); setTruncated(false); setDetail(null); setSelected([]); setPrepared(null); setQuestion(""); setClassification("internal");
    setUploadPending(null); setActionPending(null); setConfirmationPending(false); setStatus(""); setBusy(false); setDenied(true); setAuthority(value => value + 1); setError(message);
    if (input.current) input.current.value = "";
  }, []);
  useEffect(() => {
    if (!initialRunId) return;
    let active = true;
    const current = captureAccess();
    void request<{ items: { run_id: string; selection: { capability: string; product_line_id: string | null } }[] }>(`${base}/product-ai-run-read`, "POST", { run_id: initialRunId }).then(value => { if (!active || !current()) return; const item = value.items.find(item => item.run_id === initialRunId); setLinkedRun({ id: initialRunId, matched: !!item && item.selection.capability === "rfq_requirements" && (item.selection.product_line_id ?? null) === lineId }); }).catch(failure => { if (!active || !current()) return; if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) clearAuthority(failure.message); else setError(failure instanceof Error ? failure.message : "原运行暂不可读"); });
    return () => { active = false; };
  }, [base, lineId, initialRunId, captureAccess, clearAuthority]);
  const list = useCallback(async () => {
    const current = captureAccess(), version = ++listVersion.current;
    try {
      const value = await request<{ items: SourceFile[]; truncated: boolean }>(`${base}/source-files${lineId ? `?product_line_id=${lineId}` : ""}`);
      if (!current() || version !== listVersion.current) return;
      setItems(value.items); setTruncated(value.truncated); setDenied(false);
    } catch (failure) { if (current() && version === listVersion.current) { if (isDenied(failure)) clearAuthority((failure as Error).message); else setError(failure instanceof Error ? failure.message : "文件列表暂不可读"); } }
  }, [base, lineId, captureAccess, clearAuthority]);
  useEffect(() => { let active = true; void Promise.resolve().then(() => { if (active) void list(); }); return () => { active = false; }; }, [list]);
  const locked = disabled || busy || denied || confirmationPending || !!uploadPending || !!actionPending;
  const writeLocked = locked || !canEdit;
  async function refresh() {
    if (working.current || disabled || confirmationPending || originalUpload.current || originalAction.current) return;
    working.current = true; setBusy(true); setError(null); const current = captureAccess();
    try { await list(); } finally { if (current()) { working.current = false; setBusy(false); } }
  }
  async function prepare() {
    if (!detail || working.current || writeLocked) return;
    working.current = true; setBusy(true); setError(null); setPrepared(null); const current = captureAccess();
    const selection: ProductSelection = { capability: "rfq_requirements", product_line_id: lineId, question, sources: [{ kind: "file", id: detail.id, ordinals: [...selected] }] };
    try { const value = await request<{ digest: string }>(`${base}/product-ai-context`, "POST", selection); if (current()) setPrepared({ ...value, selection }); }
    catch (failure) { if (current()) { if (isDenied(failure)) clearAuthority((failure as Error).message); else setError(failure instanceof Error ? failure.message : "原文范围核对失败"); } }
    finally { if (current()) { working.current = false; setBusy(false); } }
  }
  async function read(file: SourceFile, more = false) {
    if (working.current || locked) return;
    working.current = true; setBusy(true); setError(null); const current = captureAccess();
    if (!more) { setDetail(null); setSelected([]); setPrepared(null); }
    try {
      const value = await request<Read>(`${base}/source-files/${file.id}?after_ordinal=${more ? detail?.next_after ?? 0 : 0}`);
      if (current()) setDetail(previous => more && previous?.id === value.id ? { ...value, fragments: [...previous.fragments, ...value.fragments] } : value);
    } catch (failure) { if (current()) { if (isDenied(failure)) clearAuthority((failure as Error).message); else setError(failure instanceof Error ? failure.message : "原文暂不可读"); } }
    finally { if (current()) { working.current = false; setBusy(false); } }
  }
  async function upload(file?: File) {
    if (working.current || disabled || denied || !canEdit || confirmationPending || originalAction.current || (file && originalUpload.current)) return;
    working.current = true; setBusy(true); setError(null); setDetail(null); setSelected([]); setPrepared(null); const current = captureAccess();
    try {
      let original = originalUpload.current;
      if (!original) {
        if (!file || !/\.(pdf|xlsx)$/i.test(file.name) || file.size < 1 || file.size > 20 * 1024 * 1024) throw new ProductRequestError("请选择不超过20 MiB的PDF或XLSX原件", 422);
        const level = classification; setStatus("核对原文件…"); const bytes = await file.arrayBuffer();
        if (!current()) return;
        const sha256 = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), byte => byte.toString(16).padStart(2, "0")).join("");
        if (!current()) return;
        original = { bytes, body: { request_id: crypto.randomUUID(), product_line_id: lineId, filename: file.name, size_bytes: file.size, sha256, classification: level }, stage: "register" };
        originalUpload.current = original; setUploadPending(original);
      }
      if (original.stage === "register") {
        const registered = await request<SourceFile>(`${base}/source-files`, "POST", original.body);
        if (!current()) return;
        if (registered.revoked_at) throw new ProductRequestError("此请求的原件已停止引用，请核对记录后重新上传", 409);
        original.fileId = registered.id; original.stage = "upload";
      }
      if (original.stage === "upload") {
        setStatus("上传原件…");
        const response = await fetch(`/api/product-work/${base}/source-files/${original.fileId}/upload`, { method: "PUT", headers: { "Content-Type": "application/octet-stream" }, body: original.bytes });
        if (!current()) return;
        if (!response.ok) { const value = await response.json().catch(() => null); throw new ProductRequestError(value?.detail?.message ?? "原件上传未确认成功，可重试原件处理", response.status); }
        original.stage = "parse";
      }
      setStatus("解析原文与出处…"); await request(`${base}/source-files/${original.fileId}/parse`, "POST", {});
      if (!current()) return;
      originalUpload.current = null; setUploadPending(null); setStatus("原件已处理，请核对解析状态和出处。");
      await list();
    } catch (failure) {
      if (!current()) return;
      if (isDenied(failure)) clearAuthority((failure as Error).message);
      else { if (!isUncertain(failure)) { originalUpload.current = null; setUploadPending(null); } setStatus(""); setError(failure instanceof Error ? failure.message : "文件处理结果尚未确认，可重试原件处理"); }
    } finally { if (current()) { working.current = false; setBusy(false); if (input.current) input.current.value = ""; } }
  }
  async function act(file?: SourceFile, action?: "parse" | "revoke") {
    if (working.current || disabled || denied || !canEdit || confirmationPending || originalUpload.current || (file && originalAction.current)) return;
    const original = originalAction.current ?? (file && action ? { id: file.id, action } : null);
    if (!original) return;
    originalAction.current = original; setActionPending(original); working.current = true; setBusy(true); setError(null); const current = captureAccess();
    try {
      await request(`${base}/source-files/${original.id}/${original.action}`, "POST", {});
      if (!current()) return;
      originalAction.current = null; setActionPending(null); setDetail(null); setSelected([]); setPrepared(null);
      setStatus(original.action === "revoke" ? "已停止引用此原件。" : "解析办理已确认，请核对文件状态。"); await list();
    } catch (failure) { if (current()) { if (isDenied(failure)) clearAuthority((failure as Error).message); else { if (!isUncertain(failure)) { originalAction.current = null; setActionPending(null); } setError(failure instanceof Error ? failure.message : "文件操作结果尚未确认"); } } }
    finally { if (current()) { working.current = false; setBusy(false); } }
  }
  return <section className="space-y-3 rounded-lg border p-4">
    <h3 className="font-semibold">RFQ与客户原件</h3>
    <p className="text-sm text-muted-foreground">无需先建项目。上传PDF或XLSX，核对页码、单元格与原文；原件仅供上传人依当前空间和产品线权限读取。解析不会登记需求或批准规格。</p>
    <fieldset disabled={writeLocked} className="flex flex-wrap items-end gap-3">
      <label className="text-sm">资料级别<select className="ml-2 rounded-md border bg-background p-2" value={classification} onChange={event => setClassification(event.target.value)}><option value="internal">内部</option><option value="confidential">机密</option><option value="restricted">严格受限</option></select></label>
      <input ref={input} className="hidden" type="file" accept=".pdf,.xlsx" aria-label="选择RFQ或客户原件" onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file); }}/>
      <Button type="button" variant="outline" onClick={() => input.current?.click()}>上传RFQ或客户原件</Button>
      <Button type="button" variant="ghost" onClick={() => { setError(null); void refresh(); }}>刷新文件</Button>
    </fieldset>
    {denied && <Button variant="outline" size="sm" disabled={busy} onClick={() => void refresh()}>重新核对文件权限</Button>}
    {uploadPending && <div className="space-y-2 text-sm"><p>原件处理结果尚未确认，已保留原文件、资料级别和请求编号。重试使用相同原件，请保持当前页面。</p><Button variant="outline" size="sm" disabled={disabled || busy || denied || !canEdit} onClick={() => void upload()}>重试原件处理</Button></div>}
    {actionPending && <div className="space-y-2 text-sm"><p>上次文件操作结果尚未确认，重试会核对同一原件。</p><Button variant="outline" size="sm" disabled={disabled || busy || denied || !canEdit} onClick={() => void act()}>重试原文件操作</Button></div>}
    {confirmationPending && <p role="status" className="text-sm">请先核对原确认或分析请求的结果，再更换原件和抽取范围。</p>}
    {status && <p role="status" className="text-sm">{status}</p>}
    {items.map(file => <article id={`source-file-${file.id}`} className="space-y-2 rounded-md border p-3" key={file.id}>
      <p className="text-sm font-medium">{file.filename} · {file.revoked_at ? "已停止引用" : names[file.status] ?? file.status}</p>
      <p className="text-xs text-muted-foreground">{(file.size_bytes / 1024).toFixed(1)} KiB · {file.fragment_count}段原文 · {file.classification === "internal" ? "内部" : file.classification === "confidential" ? "机密" : "严格受限"}</p>
      {file.status === "ocr_required" && <p className="text-sm">未提取到可读文字；请提供带文字层的原件后重新登记，不将空白解析当成无需求。</p>}
      {file.status === "failed" && <p className="text-sm">请核对原件格式及存储可用性，可重试解析。</p>}
      <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={locked || !!file.revoked_at || file.status !== "extracted"} onClick={() => void read(file)}>核对原文与出处</Button>
      {["uploaded", "failed"].includes(file.status) && <Button size="sm" variant="outline" disabled={writeLocked || !!file.revoked_at} onClick={() => void act(file, "parse")}>重试解析</Button>}
      {!file.revoked_at && <Button size="sm" variant="ghost" disabled={writeLocked} onClick={() => void act(file, "revoke")}>停止引用此原件</Button>}</div>
    </article>)}
    {truncated && <p className="text-xs text-muted-foreground">显示最近100份文件；可通过已有引用读取更早原件。</p>}
    {detail && <section className="space-y-3"><div className="flex items-center justify-between"><h4 className="font-medium">{detail.filename}</h4><Button size="sm" variant="ghost" disabled={locked} onClick={() => { setDetail(null); setSelected([]); setPrepared(null); }}>收起原文</Button></div>{detail.fragments.map(fragment => <div key={fragment.ordinal}><label className="flex items-center gap-2 text-xs font-medium"><input type="checkbox" checked={selected.includes(fragment.ordinal)} disabled={writeLocked || detail.classification !== "internal" || (!selected.includes(fragment.ordinal) && selected.length >= 20)} onChange={event => { setPrepared(null); setSelected(current => event.target.checked ? [...current, fragment.ordinal] : current.filter(ordinal => ordinal !== fragment.ordinal)); }}/>{fragment.locator}</label><pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-sm">{fragment.text}</pre></div>)}{detail.next_after !== null && <Button size="sm" variant="outline" disabled={locked} onClick={() => void read(detail, true)}>读取后续原文</Button>}</section>}
    {detail && <fieldset disabled={writeLocked} className="space-y-2"><p className="text-sm text-muted-foreground">勾选实际要抽取的原文，每次最多20段。未选片段不参与本次抽取；机密或严格受限原件保留人工核对。</p><label className="block text-sm">抽取要求<textarea className="mt-1 w-full rounded-md border bg-background p-2" maxLength={5000} value={question} onChange={event => { setQuestion(event.target.value); setPrepared(null); }}/></label><Button size="sm" variant="outline" disabled={!selected.length || !question.trim()} onClick={() => void prepare()}>核对所选原文范围</Button></fieldset>}
    {prepared && <p role="status" className="text-sm">已核对{prepared.selection.sources[0].ordinals?.length}段原文；可在下方读取能力状态后抽取。</p>}
    <ProductAiRuns initialRunId={linkedRun?.id === initialRunId && linkedRun?.matched ? initialRunId : undefined} key={authority} base={base} capability="rfq_requirements" line={lineId ?? ""} prepared={prepared} disabled={disabled || busy || denied || !!uploadPending || !!actionPending || !canEdit} onAuthorityDenied={clearAuthority} captureAccess={captureAccess} onPendingChange={setConfirmationPending}/>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </section>;
}
