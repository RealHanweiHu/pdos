"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
type Row = Record<string, unknown>;
const text = (value: unknown) => value == null ? "" : String(value);
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];

export function ConversationIntakeAdoption({ conversationId, finding, receipts, disabled, onAdopted }: { conversationId: string; finding: Row; receipts: Row[]; disabled: boolean; onAdopted: () => Promise<void> }) {
  const [numbers, setNumbers] = useState<number[]>([]), [note, setNote] = useState(""), [preview, setPreview] = useState<Row | null>(null), [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const pending = useRef<{ signature: string; requestId: string } | null>(null);
  const accepted = isRecord(finding.accepted_payload) ? finding.accepted_payload : {}, all = rows(accepted.proposals);
  const completed = new Set(receipts.map(item => Number(item.proposal_number)));
  const remaining = all.filter(item => item.kind === "project_observation" && !completed.has(Number(item.number)));
  function reset() { setPreview(null); setConfirmed(false); }
  async function request(path: string, body: object): Promise<Row> {
    const response = await fetch(`/api/conversations/${conversationId}/intake-ai-findings/${finding.id}/${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && isRecord(value.detail) ? text(value.detail.message) : "采用未完成，请保留输入后读取原回执或重试");
    return value;
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "采用未完成"); } finally { setBusy(false); } }
  async function adopt() {
    const body = { numbers, review_note: note, preview_digest: preview?.preview_digest, publish_to_project: true, reviewed: true };
    const signature = JSON.stringify(body);
    if (pending.current?.signature !== signature) pending.current = { signature, requestId: crypto.randomUUID() };
    await request("adopt-observations", { ...body, request_id: pending.current.requestId });
    pending.current = null; setNumbers([]); reset(); await onAdopted();
  }
  return <section className="space-y-2 rounded-md border p-3" aria-label="独立采用项目现状建议">
    <strong>独立采用到项目现状</strong>
    <p>项目现状建议已采用 {receipts.length} 项。接受、采用到现状版本、安排实际工作分别办理；历史阶段与进展不会自动推进Gate或完成任务。</p>
    {receipts.map(item => <p key={text(item.id)}>建议 {text(item.proposal_number)} · {text(item.created_at)} · <a className="text-primary underline" href={text(item.href)}>查看实际现状版本及后续工作</a></p>)}
    {all.some(item => item.kind !== "project_observation") && <p className="text-muted-foreground">问题和历史决策在下方独立导入办理，此处只显示现状建议的采用回执。</p>}
    {remaining.length > 0 && <>
      {remaining.map(item => <label key={Number(item.number)} className="flex items-start gap-2"><input type="checkbox" disabled={disabled || busy} checked={numbers.includes(Number(item.number))} onChange={e => { setNumbers(old => e.target.checked ? [...old, Number(item.number)].sort((a, b) => a - b) : old.filter(n => n !== Number(item.number))); reset(); }}/><span>建议 {text(item.number)}：{text(item.model_summary)}</span></label>)}
      <label className="block">本次采用依据<textarea className="w-full rounded-md border bg-background p-2 text-xs" value={note} maxLength={2000} disabled={disabled || busy} onChange={e => { setNote(e.target.value); reset(); }}/></label>
      <Button type="button" size="sm" variant="outline" disabled={disabled || busy || !numbers.length || !note.trim()} onClick={() => void act(async () => { setPreview(await request("observation-preview", { numbers, review_note: note })); setConfirmed(false); })}>预览新增现状与共享原件</Button>
      {preview && <div className="space-y-2 rounded-md bg-muted p-3">
        <p>以当前第 {text(preview.latest_revision)} 版为基础，保留 {text(preview.retained_observations)} 项原文及 {text(preview.retained_work)} 项工作安排，新增 {rows(preview.originals).length} 项原文依据。新增版本后可继续补齐工作、安排负责人及实际办理。</p>
        {preview.latest_id != null && <a className="text-primary underline" href={`/projects?project=${preview.project_id}&tab=overview&intake_proposal=${preview.latest_id}`}>核对当前现状和工作安排</a>}
        <p>以下完整原件将成为项目共享资料，项目有权成员可读取，包含未选的页面、文字和邮件附件。</p>
        {rows(preview.files).map(file => <p key={text(file.attachment_id)}>{text(file.filename)} · {text(file.size_bytes)} 字节 · SHA256 {text(file.sha256)}</p>)}
        <p>许可依据：{text(preview.permission_basis)} · 用途：{text(preview.purpose)}</p>
        {rows(preview.originals).map(item => <details key={`${item.number}:${item.name}`}><summary>建议 {text(item.number)} · {item.name === "anchor" ? "主要依据" : text(item.name)}</summary>{isRecord(item.quote) && <><p>{text(item.quote.locator)} · 字符 {Number(item.quote.start) + 1}–{text(item.quote.end)}</p><p className="whitespace-pre-wrap">{text(item.quote.value)}</p></>}</details>)}
        <label className="flex items-start gap-2"><input type="checkbox" disabled={busy || disabled} checked={confirmed} onChange={e => setConfirmed(e.target.checked)}/><span>已核对本次选段、现状差异及许可用途，同意将上述完整原件共享到本项目，并独立采用所选建议。</span></label>
        <Button type="button" size="sm" disabled={disabled || busy || !confirmed} onClick={() => void act(adopt)}>确认共享并采用到现状版本</Button>
      </div>}
    </>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {busy && <p role="status">正在处理采用回执…</p>}
  </section>;
}
