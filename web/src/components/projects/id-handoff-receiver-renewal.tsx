"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Item = { item_key: string; title: string; criteria: string; document_id: string; residuals: { description: string; owner_user_id: string; due_at: string }[]; artifact_snapshot: { filename: string } };
type Original = { id: string; freeze_id: string; target_node_id: string; receiver_user_id: string; payload_digest: string; snapshot: { target: { target_digest: string }; items: Item[] } };
type Request = { request_id: string; freeze_id: string; target_node_id: string; expected_target_digest: string; receiver_user_id: string; expected_previous_handoff_id: string; receiver_renewal_digest: string; reason: string; items: Omit<Item, "artifact_snapshot">[] };

export function IdHandoffReceiverRenewal({ projectId, original, choices, people, disabled, onLock, onChanged }: { projectId: string; original: Original; choices: { id: string; display_name: string }[]; people: { id: string; display_name: string }[]; disabled: boolean; onLock: (locked: boolean) => void; onChanged: (id: string) => Promise<void> }) {
  const [receiver, setReceiver] = useState(""), [reason, setReason] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<Request | null>(null), [pending, setPending] = useState<Request | null>(null);
  const person = (id: string) => people.find(item => item.id === id)?.display_name ?? "原具名人员";
  async function save(body: Request) {
    setBusy(true); setPending(body); setError(""); onLock(true);
    try {
      const response = await fetch(`/api/projects/${projectId}/execution/id-design/handoffs`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const value = await responseBody(response);
      if (!response.ok) {
        if ([400, 401, 403, 404, 409, 422].includes(response.status)) { setPending(null); setPreview(null); onLock(false); }
        throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "未取得新交接回执，请按原内容重试");
      }
      if (!isRecord(value) || typeof value.id !== "string" || value.request_id !== body.request_id || value.previous_handoff_id !== original.id) throw new Error("回执不完整，请保留原请求重试");
      setPending(null); setPreview(null); onLock(false); await onChanged(value.id);
    } catch (e) { setError(e instanceof Error ? e.message : "交接接续未完成"); }
    finally { setBusy(false); }
  }
  return <details className="space-y-2 rounded-md border p-3"><summary className="cursor-pointer font-medium">调整接收人并提交新轮次</summary><p className="text-muted-foreground">保留原冻结设计、交付文档、验收标准和遗留安排。仅选择当前正式节点的另一位有效责任人，新轮次重新逐项接收；原轮次及已有意见保留。</p>
    {error ? <p role="alert" className="text-destructive">{error}</p> : null}
    <fieldset className="space-y-2" disabled={disabled || busy || !!preview || !!pending}><label className="block">新接收人（原：{person(original.receiver_user_id)}）<select className="mt-1 w-full rounded-md border bg-background p-2" value={receiver} onChange={e => { setReceiver(e.target.value); onLock(true); }}><option value="">选择当前节点具名人员</option>{choices.map(item => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label>
      {!choices.length ? <p>暂无可独立接收的其他具名人员，请先通过正式计划责任调整办理。</p> : null}
      <label className="block">调整原因与接续说明<textarea maxLength={2048} className="mt-1 w-full rounded-md border bg-background p-2" value={reason} onChange={e => { setReason(e.target.value); onLock(true); }}/></label>
      <Button type="button" size="sm" disabled={!reason.trim() || !choices.some(item => item.id === receiver)} onClick={() => { setPreview({ request_id: crypto.randomUUID(), freeze_id: original.freeze_id, target_node_id: original.target_node_id, expected_target_digest: original.snapshot.target.target_digest, receiver_user_id: receiver, expected_previous_handoff_id: original.id, receiver_renewal_digest: original.payload_digest, reason: reason.trim(), items: original.snapshot.items.map(({ item_key, title, criteria, document_id, residuals }) => ({ item_key, title, criteria, document_id, residuals })) }); onLock(true); }}>预览新接收轮次</Button><Button type="button" size="sm" variant="ghost" onClick={() => { setReceiver(""); setReason(""); onLock(false); }}>清除接续输入</Button>
    </fieldset>
    {preview && !pending ? <div className="space-y-2 rounded-md border p-3"><p>接收人：{person(original.receiver_user_id)} → {person(preview.receiver_user_id)}</p><p className="whitespace-pre-wrap">{preview.reason}</p>{original.snapshot.items.map(item => <div key={item.item_key}><p>{item.title} · {item.artifact_snapshot.filename}</p><p>验收标准：{item.criteria}</p>{item.residuals.map((residual, index) => <p key={index}>遗留：{residual.description} · {person(residual.owner_user_id)} · {new Date(residual.due_at).toLocaleString()}</p>)}</div>)}<Button type="button" size="sm" disabled={disabled || busy} onClick={() => void save(preview)}>确认提交新轮次</Button><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button></div> : null}
    {pending ? <div><p className="break-all">待确认原请求：{pending.request_id}</p><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void save(pending)}>按原内容重试并取得回执</Button></div> : null}
  </details>;
}
