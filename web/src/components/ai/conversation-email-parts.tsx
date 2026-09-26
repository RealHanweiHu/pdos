"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
type Row = Record<string, unknown>;
const text = (value: unknown) => value == null ? "" : String(value);
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const labels: Record<string, string> = { available: "可独立保存", unsupported: "当前不支持此格式", nested_message_or_container: "嵌入邮件或附件容器，保留在原件中", invalid_filename: "文件名不可用", unsupported_encoding: "暂不支持此编码", malformed_part: "附件编码或结构不完整", invalid_size: "文件为空或超过大小限制" };
const levels = ["internal", "confidential", "restricted"];
const levelLabels = ["内部资料", "机密资料", "受限资料"];
const field = "w-full rounded-md border bg-background p-2 text-xs";
async function request(path: string, body?: object): Promise<Row> {
  const response = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && isRecord(value.detail) ? text(value.detail.message) : "邮件附件暂不可用，请保留输入后重试");
  return value;
}
export function EmailPartOrigins({ value, conversationId, attachmentId }: { value: Row; conversationId: string; attachmentId: string }) {
  const [extra, setExtra] = useState<Row[]>([]), [cursor, setCursor] = useState<unknown>(undefined), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const next = cursor === undefined ? value.next_id : cursor;
  async function more() {
    setBusy(true); setError(null);
    try { const page = await request(`/api/conversations/${conversationId}/attachments/${attachmentId}/email-origins?before_id=${encodeURIComponent(text(next))}`); setExtra(old => [...old, ...rows(page.items)]); setCursor(page.next_id); }
    catch (e) { setError(e instanceof Error ? e.message : "来源暂不可读"); } finally { setBusy(false); }
  }
  return <details><summary className="cursor-pointer text-xs">邮件附件来源与独立保存记录</summary>{[...rows(value.items), ...extra].map(item => {
    const parent = isRecord(item.parent) ? item.parent : {}, child = isRecord(item.attachment) ? item.attachment : {}, part = isRecord(item.part_snapshot) ? item.part_snapshot : {};
    const href = (id: unknown) => `/ask?project=${item.project_id}&conversation=${conversationId}&attachment=${id}`;
    return <div key={text(item.id)} className="my-2 space-y-1 border-t pt-2 text-xs"><p>原邮件：<a className="text-primary underline" href={href(parent.id)}>{text(parent.filename)}</a>{parent.revoked_at ? "（已停止引用）" : ""} · MIME {text(item.part_path)}</p><p>独立附件：<a className="text-primary underline" href={href(child.id)}>{text(child.filename)}</a> · {child.revoked_at ? "已停止引用" : text(child.status)}</p><p>原附件名：{text(part.original_filename) || "原件未提供"} · {text(part.size_bytes)} 字节</p><p className="break-all">附件摘要：{text(part.sha256)}</p><p className="whitespace-pre-wrap">许可依据：{text(item.permission_basis)}<br/>用途：{text(item.purpose)}</p><p>{text(item.created_at)} · 核对人 {text(item.created_by_user_id)}</p></div>;
  })}{next != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void more()}>继续读取来源记录</Button>}{error && <p role="alert" className="text-xs text-destructive">{error}</p>}</details>;
}
export function ConversationEmailParts({ conversationId, attachmentId, classification: initialClass, disabled, onBusy, onSaved }: {
  conversationId: string; attachmentId: string; classification: string; disabled: boolean; onBusy: (busy: boolean) => void; onSaved: () => Promise<void>;
}) {
  const [preview, setPreview] = useState<Row | null>(null), [partPath, setPartPath] = useState("");
  const [permission, setPermission] = useState(""), [purpose, setPurpose] = useState(""), [classification, setClassification] = useState(initialClass);
  const [reviewed, setReviewed] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [receipt, setReceipt] = useState<Row | null>(null);
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const base = `/api/conversations/${conversationId}/attachments/${attachmentId}/email-parts`;
  const part = rows(preview?.parts).find(item => item.path === partPath);
  async function act(work: () => Promise<void>) { setBusy(true); onBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "未完成"); } finally { setBusy(false); onBusy(false); } }
  async function load() { setPreview(await request(base)); setPartPath(""); setReviewed(false); }
  async function save() {
    if (!preview || !part) return;
    const body = { expected_source_digest: preview.source_digest, part_path: part.path, expected_part_digest: part.digest, classification, permission_basis: permission.trim(), purpose: purpose.trim(), reviewed: true }, signature = JSON.stringify(body);
    if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    const value = await request(base, { ...body, request_id: pending.current.id }); setReceipt(value);
    const child = isRecord(value.attachment) ? value.attachment : {};
    if (child.status !== "awaiting_upload") { pending.current = null; setReviewed(false); }
    await onSaved();
  }
  return <details className="rounded-md border p-2"><summary className="cursor-pointer text-xs font-medium">选择邮件中的独立附件</summary><div className="mt-2 space-y-2 text-xs">
    <p>从已保存邮件中核对并拆取PDF/XLSX，保留原邮件及MIME位置。只解码所列附件字节；附件文字另行抽取，不读取外部链接、压缩包或嵌入邮件。</p>
    <Button type="button" size="sm" variant="outline" disabled={disabled || busy} onClick={() => void act(load)}>读取邮件附件清单</Button>
    {preview && !rows(preview.parts).length && <p>未找到具有附件标记或文件名的邮件部分。</p>}
    {preview && <fieldset disabled={disabled || busy} className="space-y-2">
      {rows(preview.parts).map(item => <label key={text(item.path)} className="flex items-start gap-2 rounded-md border p-2"><input type="radio" name={`email-part-${attachmentId}`} disabled={item.status !== "available"} checked={partPath === item.path} onChange={() => { setPartPath(text(item.path)); setReviewed(false); setReceipt(null); }}/><span>{text(item.original_filename) || text(item.filename) || "原件未提供文件名"} · MIME {text(item.path)} · {labels[text(item.status)] ?? text(item.status)}<br/>原件声明 {text(item.declared_media_type)}{item.size_bytes != null && <> · {text(item.size_bytes)} 字节</>}</span></label>)}
      {part && <p className="break-all">独立保存名：{text(part.filename)} · SHA-256 {text(part.sha256)}</p>}
      <label className="block">附件资料级别<select className={field} value={classification} onChange={e => { setClassification(e.target.value); setReviewed(false); }}>{levels.map((level, i) => <option key={level} value={level} disabled={i < levels.indexOf(initialClass)}>{levelLabels[i]}</option>)}</select></label>
      <label className="block">使用许可依据<textarea className={field} maxLength={2000} value={permission} onChange={e => { setPermission(e.target.value); setReviewed(false); }}/></label>
      <label className="block">整理用途<textarea className={field} maxLength={2000} value={purpose} onChange={e => { setPurpose(e.target.value); setReviewed(false); }}/></label>
      <label className="flex items-start gap-2"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)}/><span>已核对所选附件及许可，保存为本人的独立会话文件。停止引用原邮件不会同时停止已独立保存的附件；需要时应分别办理。</span></label>
      <Button type="button" size="sm" disabled={!part || !reviewed || !permission.trim() || !purpose.trim()} onClick={() => void act(save)}>独立保存到本会话</Button>
    </fieldset>}
    {receipt && isRecord(receipt.attachment) && <p role="status">{receipt.attachment.status === "awaiting_upload" ? "登记及来源已保存，文件尚未保存成功；可用原输入重试。" : receipt.attachment.revoked_at ? "原办理对应的独立附件已停止引用。" : "独立附件已保存或复用。可在文件列表抽取文字、选择附件并发送消息，再进入问题／决策／报告整理。"}</p>}
    {preview && isRecord(preview.origins) && <EmailPartOrigins key={text(preview.source_digest)} value={preview.origins} conversationId={conversationId} attachmentId={attachmentId}/>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
  </div></details>;
}
