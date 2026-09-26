"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

const slots = { product_user_id: "产品／客户确认人", me_user_id: "结构确认人", hw_user_id: "硬件确认人" };
type People = { id: string; display_name: string }[];
type Original = { id: string; revision_id: string; confirmation_document_id: string; payload_digest: string; product_user_id: string; me_user_id: string; hw_user_id: string; authority_basis: string; snapshot: { revision: { payload_digest: string } } };
type Request = { request_id: string; revision_id: string; expected_revision_digest: string; confirmation_document_id: string; product_user_id: string; me_user_id: string; hw_user_id: string; authority_basis: string; reason: string; responsibility_renewal: { previous_request_id: string; expected_digest: string } };

export function IdFreezeResponsibilityRenewal({ projectId, original, people, disabled, onLock, onChanged }: { projectId: string; original: Original; people: People; disabled: boolean; onLock: (locked: boolean) => void; onChanged: (id: string) => Promise<void> }) {
  const [form, setForm] = useState({ product_user_id: original.product_user_id, me_user_id: original.me_user_id, hw_user_id: original.hw_user_id, authority_basis: original.authority_basis, reason: "" });
  const [preview, setPreview] = useState<Request | null>(null), [pending, setPending] = useState<Request | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const person = (id: string) => people.find(value => value.id === id)?.display_name ?? "原具名确认人";
  async function save(body: Request) {
    setBusy(true); setPending(body); setError(""); onLock(true);
    try {
      const response = await fetch(`/api/projects/${projectId}/execution/id-design/freezes`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const value = await responseBody(response);
      if (!response.ok) {
        if ([400, 401, 403, 404, 409, 422].includes(response.status)) { setPending(null); setPreview(null); onLock(false); }
        throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "未取得替代申请回执，请按原请求重试");
      }
      if (!isRecord(value) || value.request_id !== body.request_id || value.previous_request_id !== original.id || typeof value.id !== "string") throw new Error("回执不完整，请保留原请求重试");
      setPending(null); setPreview(null); onLock(false); await onChanged(value.id);
    } catch (e) { setError(e instanceof Error ? e.message : "调整未完成"); }
    finally { setBusy(false); }
  }
  return <details className="space-y-2 rounded-md border p-3"><summary className="cursor-pointer font-medium">调整具名确认人并重新申请</summary>
    <p className="text-muted-foreground">沿用本申请固定的设计、图档和反馈依据。保存后旧申请退出办理，原意见保留；新申请三方重新确认后再独立冻结。</p>
    {error ? <p role="alert" className="text-destructive">{error}</p> : null}
    <fieldset disabled={disabled || busy || !!preview || !!pending} className="space-y-2">
      {(Object.keys(slots) as (keyof typeof slots)[]).map(key => <label className="block" key={key}>{slots[key]}（原：{person(original[key])}）<select className="mt-1 w-full rounded-md border bg-background p-2" value={form[key]} onChange={e => { setForm(old => ({ ...old, [key]: e.target.value })); onLock(true); }}><option value="">选择有效项目成员</option>{people.map(item => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label>)}
      <label className="block">新确认职责与授权依据<textarea maxLength={2048} className="mt-1 w-full rounded-md border bg-background p-2" value={form.authority_basis} onChange={e => { setForm(old => ({ ...old, authority_basis: e.target.value })); onLock(true); }}/></label>
      <label className="block">调整原因与交接安排<textarea maxLength={2048} className="mt-1 w-full rounded-md border bg-background p-2" value={form.reason} onChange={e => { setForm(old => ({ ...old, reason: e.target.value })); onLock(true); }}/></label>
      <Button type="button" size="sm" disabled={!form.reason.trim() || !form.authority_basis.trim() || Object.keys(slots).some(key => !people.some(person => person.id === form[key as keyof typeof slots])) || Object.keys(slots).every(key => original[key as keyof typeof slots] === form[key as keyof typeof slots])} onClick={() => { setPreview({ ...form, reason: form.reason.trim(), authority_basis: form.authority_basis.trim(), request_id: crypto.randomUUID(), revision_id: original.revision_id, expected_revision_digest: original.snapshot.revision.payload_digest, confirmation_document_id: original.confirmation_document_id, responsibility_renewal: { previous_request_id: original.id, expected_digest: original.payload_digest } }); onLock(true); }}>预览人员调整</Button>
      <Button type="button" size="sm" variant="ghost" onClick={() => { setForm({ product_user_id: original.product_user_id, me_user_id: original.me_user_id, hw_user_id: original.hw_user_id, authority_basis: original.authority_basis, reason: "" }); onLock(false); }}>清除调整输入</Button>
    </fieldset>
    {preview && !pending ? <div className="space-y-2 rounded-md border p-3">{(Object.keys(slots) as (keyof typeof slots)[]).map(key => <p key={key}>{slots[key]}：{person(original[key])} → {person(preview[key])}</p>)}<p className="whitespace-pre-wrap">授权依据：{preview.authority_basis}</p><p className="whitespace-pre-wrap">{preview.reason}</p><Button type="button" size="sm" disabled={busy || disabled} onClick={() => void save(preview)}>确认替代原申请</Button><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button></div> : null}
    {pending ? <div className="space-y-2"><p className="break-all">待确认原请求：{pending.request_id}</p><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void save(pending)}>按原内容重试并取得回执</Button></div> : null}
  </details>;
}
