"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Fact = { at: string; evidence_id: string; location: string };
type Draft = { update: "first_response" | "sample_received"; at: string; evidence_id: string; location: string; reason: string };
type Record = { record_id: string; version: number; payload: { kind: string; title: string; status: string; responded: Fact | null; received: Fact | null; promised: Fact | null } };
type Preview = { digest: string; basis: { previous_version: number; proposed: Record["payload"]; notice: string } };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

async function request<T>(path: string, body: object): Promise<T> {
  const response = await fetch(path, { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "供方回复未保存，请保留原内容并重试");
  return value as T;
}

export function SupplierReplies({ projectId, supplierId, record, documents, onSaved }: {
  projectId: string; supplierId: string; record: Record; documents: { id: string; filename: string }[]; onSaved: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<Draft>({ update: record.payload.responded ? "sample_received" : "first_response", at: "", evidence_id: "", location: "", reason: "" });
  const [preview, setPreview] = useState<Preview | null>(null), [previewKey, setPreviewKey] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null);
  const ids = useRef(new Map<string, string>());
  const key = JSON.stringify({ projectId, supplierId, recordId: record.record_id, version: record.version, draft });
  const current = key === previewKey;
  const base = `/api/projects/${projectId}/npi/supplier-replies/${supplierId}/${record.record_id}`;
  const choices = [
    ...(!record.payload.responded ? [{ value: "first_response", title: "首次实际响应" }] : []),
    ...(record.payload.kind === "sample_delivery" && !record.payload.received ? [{ value: "sample_received", title: "实际收样" }] : []),
  ];
  if (record.payload.status !== "active" || !["sample_delivery", "technical_response"].includes(record.payload.kind) || !choices.length) return null;
  function body() {
    const at = new Date(draft.at);
    if (!Number.isFinite(at.getTime())) throw new Error("请填写回复或收样实际发生时间");
    return { ...draft, at: at.toISOString() };
  }
  async function act(work: () => Promise<void>) {
    setBusy(true); setError(null); setNotice(null);
    try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "更新未完成"); } finally { setBusy(false); }
  }
  async function prepare() {
    const observed = await request<Preview>(`${base}/preview`, body());
    setPreview(observed); setPreviewKey(key);
  }
  async function confirm() {
    if (!preview || !current) return;
    const command = { ...body(), expected_version: preview.basis.previous_version, expected_digest: preview.digest, evidence_checked: true };
    const signature = JSON.stringify(command);
    let id = ids.current.get(signature);
    if (!id) { id = crypto.randomUUID(); ids.current.set(signature, id); }
    const saved = await request<{ version: number }>(`${base}/confirm`, { ...command, request_id: id });
    setNotice(`已更新原事项 v${saved.version}，供方指标按实际记录重算。`);
    setPreview(null);
    await onSaved();
  }
  return <details className="rounded-md border p-3"><summary className="cursor-pointer text-sm">从供方回复补齐实际记录</summary><div className="mt-3 space-y-3 text-sm">
    <p className="text-xs text-muted-foreground">选择已保存到本项目的内部转发回复或收样证据，预填原事项后一次确认。供方回复的未来交期仍需具名核对；实际收样不替代质量放行或ERP供给快照。</p>
    <fieldset disabled={busy} className="space-y-3">
      <label className="block">本次事实<select className={field} value={draft.update} onChange={event => setDraft({ ...draft, update: event.target.value as Draft["update"] })}>{choices.map(choice => <option value={choice.value} key={choice.value}>{choice.title}</option>)}</select></label>
      <label className="block">实际发生时间（本机时区）<input type="datetime-local" className={field} value={draft.at} onChange={event => setDraft({ ...draft, at: event.target.value })}/></label>
      <label className="block">回复或收样证据<select className={field} value={draft.evidence_id} onChange={event => setDraft({ ...draft, evidence_id: event.target.value })}><option value="">选择本项目原件</option>{documents.map(doc => <option key={doc.id} value={doc.id}>{doc.filename}</option>)}</select></label>
      <label className="block">原件位置与时间依据<textarea maxLength={2048} className={field} value={draft.location} onChange={event => setDraft({ ...draft, location: event.target.value })}/></label>
      <label className="block">回复与该供方、原事项的关系及更新理由<textarea maxLength={2048} className={field} value={draft.reason} onChange={event => setDraft({ ...draft, reason: event.target.value })}/></label>
      <Button size="sm" variant="outline" disabled={!draft.at || !draft.evidence_id || !draft.location.trim() || !draft.reason.trim()} onClick={() => void act(prepare)}>预览原事项更新</Button>
      {preview && <div className="space-y-2 rounded-md border p-3 text-xs"><p>{current ? "当前预览" : "内容或原版本已变化，请重新预览"} · {record.payload.title} · v{preview.basis.previous_version} → v{preview.basis.previous_version + 1}</p><p>补齐{draft.update === "first_response" ? "首次实际响应" : "实际收样"}：{new Date((draft.update === "first_response" ? preview.basis.proposed.responded : preview.basis.proposed.received)?.at ?? "").toLocaleString()}</p><p>具名供样承诺：{preview.basis.proposed.promised ? new Date(preview.basis.proposed.promised.at).toLocaleString() : "未知"}</p><p>{preview.basis.notice}</p><p>点击确认表示已核对原件、事实时间、供方与原事项；保存后留存具名版本和证据。</p><Button size="sm" disabled={!current} onClick={() => void act(confirm)}>确认并更新原事项</Button></div>}
    </fieldset>
    {error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}
  </div></details>;
}
