"use client";

import { ConversationEmailParts, EmailPartOrigins } from "./conversation-email-parts";
import { EmailExtractionNotice } from "./email-extraction-notice";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

export type ConversationAttachment = {
  id: string; filename: string; classification: string; size_bytes: number; sha256: string;
  extraction_metadata?: Record<string, unknown>; status: string; error_code: string | null; revoked_at: string | null; fragment_count: number;
};
const labels: Record<string, string> = { awaiting_upload: "已登记，等待传完", uploaded: "原文件已保存，待抽取", extracted: "文字已抽取", ocr_required: "需要OCR，尚未读到文字", failed: "抽取失败，可重试" };
export async function attachmentRequest(path: string, body?: object | File): Promise<unknown> {
  const binary = body instanceof File;
  const response = await fetch(path, {
    method: body ? "POST" : "GET", cache: "no-store",
    headers: body ? { "Content-Type": binary ? "application/octet-stream" : "application/json" } : undefined,
    body: body ? binary ? body : JSON.stringify(body) : undefined,
  });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "附件处理未完成，请刷新原回执后继续");
  return value;
}
export function parseAttachment(value: unknown): ConversationAttachment {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.filename !== "string" || typeof value.status !== "string"
    || typeof value.classification !== "string" || typeof value.size_bytes !== "number" || typeof value.sha256 !== "string" || typeof value.fragment_count !== "number"
    || !(value.revoked_at === null || typeof value.revoked_at === "string")) throw new Error("附件回执不完整");
  return { extraction_metadata: isRecord(value.extraction_metadata) ? value.extraction_metadata : {}, id: value.id, filename: value.filename, status: value.status, classification: value.classification, size_bytes: value.size_bytes, sha256: value.sha256, fragment_count: value.fragment_count, revoked_at: value.revoked_at, error_code: typeof value.error_code === "string" ? value.error_code : null };
}
export function AttachmentDetail({ conversationId, attachmentId, initialOpen = false, initialFragment = 1 }: {
  conversationId: string; attachmentId: string; initialOpen?: boolean; initialFragment?: number;
}) {
  const [attachment, setAttachment] = useState<ConversationAttachment | null>(null);
  const [origins, setOrigins] = useState<Record<string, unknown> | null>(null);
  const [fragments, setFragments] = useState<{ ordinal: number; locator: string; text: string }[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  async function load(older = false) {
    setBusy(true); setError(null);
    try {
      const value = await attachmentRequest(`/api/conversations/${conversationId}/attachments/${attachmentId}?after_ordinal=${older ? next : Math.max(0, initialFragment - 1)}`);
      if (!isRecord(value) || !Array.isArray(value.fragments)) throw new Error("附件原文暂不可用");
      setAttachment(parseAttachment(value));
      setOrigins(isRecord(value.email_origins) ? value.email_origins : null);
      const rows = value.fragments.map(f => { if (!isRecord(f) || typeof f.ordinal !== "number" || typeof f.locator !== "string" || typeof f.text !== "string") throw new Error("原文片段不完整"); return { ordinal: f.ordinal, locator: f.locator, text: f.text }; });
      setFragments(previous => older ? [...previous, ...rows] : rows); setNext(typeof value.next_after === "number" ? value.next_after : null);
    } catch (e) { setError(e instanceof Error ? e.message : "读取原文失败"); } finally { setBusy(false); }
  }
  return <details id={`attachment-${attachmentId}`} open={initialOpen} className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !attachment && !busy) void load(); }}>
    <summary className="cursor-pointer text-xs font-medium">{attachment?.filename ?? "打开附件原文与状态"}</summary>
    <div className="mt-3 space-y-3">
      {attachment && <p className="text-xs">{attachment.revoked_at ? "已停止引用，历史证据保留" : labels[attachment.status] ?? attachment.status} · {(attachment.size_bytes / 1024).toFixed(1)} KiB · {attachment.fragment_count}个原文片段</p>}
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void load()}>核对当前原文</Button>
      {attachment && <EmailExtractionNotice metadata={attachment.extraction_metadata}/>}
      {origins && Array.isArray(origins.items) && origins.items.length > 0 && <EmailPartOrigins key={`${attachmentId}:${JSON.stringify(origins)}`} value={origins} conversationId={conversationId} attachmentId={attachmentId}/>}
      {fragments.map(f => <section className="space-y-1" key={f.ordinal}><p className="text-xs font-medium">{f.locator}</p><pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">{f.text}</pre></section>)}
      {next !== null && <Button size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>读取后续原文片段</Button>}
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    </div>
  </details>;
}

export function ConversationFiles({ conversationId, ensureConversation, selected, onSelectionChange, onBusyChange, disabled, initialAttachmentId, initialFragment }: {
  conversationId?: string; ensureConversation: () => Promise<string>; selected: ConversationAttachment[];
  onSelectionChange: (rows: ConversationAttachment[]) => void; onBusyChange: (busy: boolean) => void; disabled: boolean;
  initialAttachmentId?: string; initialFragment?: number;
}) {
  const [items, setItems] = useState<ConversationAttachment[]>([]), [truncated, setTruncated] = useState(false);
  const [classification, setClassification] = useState("internal"), [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null), [progress, setProgress] = useState<string | null>(null);
  const input = useRef<HTMLInputElement | null>(null);
  async function refresh(id: string) {
    const value = await attachmentRequest(`/api/conversations/${id}/attachments`);
    if (!isRecord(value) || !Array.isArray(value.items)) throw new Error("附件清单暂不可用");
    const rows = value.items.map(parseAttachment); setItems(rows); setTruncated(value.truncated === true);
    return rows;
  }
  useEffect(() => {
    if (!conversationId) return;
    let active = true;
    void attachmentRequest(`/api/conversations/${conversationId}/attachments`).then(value => {
      if (!active) return;
      if (!isRecord(value) || !Array.isArray(value.items)) throw new Error("附件清单暂不可用");
      setItems(value.items.map(parseAttachment)); setTruncated(value.truncated === true);
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : "附件清单读取失败"); });
    return () => { active = false; };
  }, [conversationId]);
  async function act(work: () => Promise<void>) {
    setBusy(true); onBusyChange(true); setError(null);
    try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "附件办理未完成"); }
    finally { setBusy(false); onBusyChange(false); }
  }
  async function upload(files: File[]) {
    if (files.length > 6) throw new Error("每次最多添加6个文件，请分批上传");
    const id = conversationId ?? await ensureConversation();
    let picks = selected;
    const failures: string[] = [];
    for (const file of files) {
      try {
        if (!/\.(pdf|xlsx|eml)$/i.test(file.name) || !file.size || file.size > 20 * 1024 * 1024) throw new Error("仅支持非空、20 MiB以内的PDF/XLSX/授权EML");
        setProgress(`${file.name}：正在核对文件内容…`);
        const sha = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await file.arrayBuffer()))).map(b => b.toString(16).padStart(2, "0")).join("");
        let row = parseAttachment(await attachmentRequest(`/api/conversations/${id}/attachments`, { request_id: crypto.randomUUID(), filename: file.name, size_bytes: file.size, sha256: sha, classification }));
        if (row.revoked_at) throw new Error("此内容已停止引用，请选择适用的新资料");
        if (row.status === "awaiting_upload") {
          setProgress(`${file.name}：正在上传原件…`);
          row = parseAttachment(await attachmentRequest(`/api/conversations/${id}/attachments/${row.id}/content`, file));
        }
        if (["uploaded", "failed"].includes(row.status)) {
          setProgress(`${file.name}：原件已保存，正在抽取文字…`);
          row = parseAttachment(await attachmentRequest(`/api/conversations/${id}/attachments/${row.id}/parse`, {}));
        }
        picks = picks.map(p => p.id === row.id ? row : p);
        onSelectionChange(picks);
        if (!picks.some(p => p.id === row.id) && picks.length < 6) { picks = [...picks, row]; onSelectionChange(picks); }
        else if (!picks.some(p => p.id === row.id)) failures.push(`${file.name}：已保存，请在下一条消息选择`);
        if (row.status !== "extracted") failures.push(`${file.name}：${labels[row.status] ?? row.status}`);
      } catch (e) { failures.push(`${file.name}：${e instanceof Error ? e.message : "处理未完成"}`); }
    }
    await refresh(id); setProgress("已查询本批附件回执；附件保存不等于正式业务录入。");
    if (failures.length) setError(failures.join("；"));
  }
  async function refreshSelected() {
    if (!conversationId) return;
    const rows = await refresh(conversationId);
    onSelectionChange(selected.map(p => rows.find(r => r.id === p.id) ?? p));
  }
  return <section className="space-y-3 rounded-lg border p-3" onDragOver={e => { e.preventDefault(); }} onDrop={e => { e.preventDefault(); if (!disabled && !busy) void act(() => upload(Array.from(e.dataTransfer.files))); }}>
    <p className="text-sm font-medium">本条消息的文件</p>
    <p className="text-xs text-muted-foreground">拖入或选择PDF/XLSX/授权EML，每条最多6个、每个20 MiB。文件仅本人可见；内部资料抽取完成后可用于问答，机密或受限资料仅保存并供本人核对。扫描PDF目前需要OCR；表格公式按原文展示，不代算结果。EML仅抽取邮件头和正文文字；请上传有权用于此项目的原件，在整理草稿中填写许可依据及用途。</p>
    <div className="flex flex-wrap gap-2">
      <select className="rounded-md border bg-background p-2 text-xs" aria-label="新上传文件的资料级别" value={classification} disabled={disabled || busy} onChange={e => setClassification(e.target.value)}><option value="internal">内部资料，可供模型阅读</option><option value="confidential">机密资料，仅本人核对</option><option value="restricted">受限资料，仅本人核对</option></select>
      <input ref={input} type="file" className="hidden" accept=".pdf,.xlsx,.eml" multiple onChange={e => { const files = Array.from(e.target.files ?? []); e.target.value = ""; if (files.length) void act(() => upload(files)); }} />
      <Button type="button" size="sm" variant="outline" disabled={disabled || busy} onClick={() => input.current?.click()}>选择文件</Button>
      {conversationId && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(refreshSelected)}>刷新附件回执</Button>}
    </div>
    {progress && <p role="status" className="text-xs">{progress}</p>}
    {items.map(row => <div key={row.id} className="space-y-2 rounded-md border p-2">
      <label className="flex items-start gap-2 text-xs"><input type="checkbox" disabled={disabled || busy || !!row.revoked_at || (!selected.some(s => s.id === row.id) && selected.length >= 6)} checked={selected.some(s => s.id === row.id)} onChange={e => onSelectionChange(e.target.checked ? [...selected, row] : selected.filter(s => s.id !== row.id))} /><span>{row.filename} · {row.revoked_at ? "已停止引用" : labels[row.status] ?? row.status} · {row.fragment_count}段{row.error_code ? " · 上次处理未完成" : ""}</span></label>
      {conversationId && <AttachmentDetail key={`${conversationId}:${row.id}`} conversationId={conversationId} attachmentId={row.id} initialOpen={initialAttachmentId === row.id} initialFragment={initialAttachmentId === row.id ? initialFragment : undefined} />}
      {conversationId && !row.revoked_at && row.status !== "awaiting_upload" && /\.eml$/i.test(row.filename) && <ConversationEmailParts conversationId={conversationId} attachmentId={row.id} classification={row.classification} disabled={busy || disabled} onBusy={value => { setBusy(value); onBusyChange(value); }} onSaved={refreshSelected}/>}
      {conversationId && !row.revoked_at && ["uploaded", "failed"].includes(row.status) && <Button type="button" size="sm" variant="outline" disabled={busy || disabled} onClick={() => void act(async () => { await attachmentRequest(`/api/conversations/${conversationId}/attachments/${row.id}/parse`, {}); await refreshSelected(); })}>从已存原件重新抽取</Button>}
      {row.status === "awaiting_upload" && <p className="text-xs text-muted-foreground">重新选择同一原文件即可续传，系统会核对内容并复用登记。</p>}
      {conversationId && !row.revoked_at && <Button type="button" size="sm" variant="ghost" disabled={busy || disabled} onClick={() => void act(async () => { await attachmentRequest(`/api/conversations/${conversationId}/attachments/${row.id}/revoke`, {}); const rows = await refresh(conversationId); onSelectionChange(selected.filter(p => p.id !== row.id).map(p => rows.find(r => r.id === p.id) ?? p)); })}>停止引用此附件</Button>}
    </div>)}
    {truncated && <p className="text-xs text-muted-foreground">此处显示最近100个附件；已发消息仍可打开其原附件。</p>}
    {error && <p role="alert" className="whitespace-pre-wrap text-xs text-destructive">{error}</p>}
  </section>;
}
