"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Request = { request_id: string; plan_review_id: string; reason: string; policy_renewal: { previous_execution_id: string; expected_execution_digest: string; policy_id: string } };
export function ProjectExecutionRenewal({ projectId, original, policy, approverName, disabled, onLockChange, onChanged }: { projectId: string; original: { id: string; round_no: number; plan_review_id: string; payload_digest: string }; policy: { id: string; version: number; four_eyes: boolean; authority_basis: string }; approverName: string; disabled: boolean; onLockChange: (locked: boolean) => void; onChanged: (replacementId: string) => Promise<void> }) {
  const [reason, setReason] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [preview, setPreview] = useState<Request | null>(null), [pending, setPending] = useState<Request | null>(null), [receipt, setReceipt] = useState("");
  async function save(body: Request) {
    setPending(body); setBusy(true); setError(""); onLockChange(true);
    try {
      const response = await fetch(`/api/projects/${projectId}/execution/requests`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const value = await responseBody(response);
      if (!response.ok) {
        if ([400, 401, 403, 404, 409, 422].includes(response.status)) { setPending(null); setPreview(null); onLockChange(false); }
        throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "续提未完成，请保留原请求重试");
      }
      if (!isRecord(value) || value.request_id !== body.request_id || typeof value.id !== "string" || typeof value.round_no !== "number") throw new Error("回执不完整，请按原请求重试");
      setReceipt(`已保存第 ${value.round_no} 轮执行申请；请求 ${body.request_id}。`); setPending(null); setPreview(null); setReason(""); onLockChange(false); await onChanged(value.id);
    } catch (e) { setError(e instanceof Error ? e.message : "续提失败"); }
    finally { setBusy(false); }
  }
  return <section className="space-y-2 rounded-md border p-3 text-xs" aria-label="项目执行申请按新政策续提"><h4 className="font-medium">按当前政策续提原计划</h4><p>原第 {original.round_no} 轮申请绑定旧政策。当前政策 v{policy.version}：由 {approverName} 批准；{policy.four_eyes ? "批准人与历次申请人分离" : "沿用当前政策的同人申请批准规则"}。</p><p className="whitespace-pre-wrap">当前授权依据：{policy.authority_basis}</p><p className="text-muted-foreground">续提保留原计划和实际来源，建立新待批准轮次。原申请和签名保留；计划或其他执行依据变化时须准备完整新申请。</p>{error ? <p role="alert" className="text-destructive">{error}</p> : null}{receipt ? <p role="status">{receipt}</p> : null}<fieldset disabled={disabled || busy || !!pending || !!preview} className="space-y-2"><label className="block">续提原因<textarea className="mt-1 w-full rounded-md border bg-background p-2" maxLength={2048} value={reason} onChange={e => { setReason(e.target.value); onLockChange(!!e.target.value); }}/></label><Button type="button" size="sm" variant="outline" disabled={!reason.trim()} onClick={() => { setPreview({ request_id: crypto.randomUUID(), plan_review_id: original.plan_review_id, reason: reason.trim(), policy_renewal: { previous_execution_id: original.id, expected_execution_digest: original.payload_digest, policy_id: policy.id } }); onLockChange(true); }}>预览新申请轮次</Button><Button type="button" size="sm" variant="ghost" onClick={() => { setReason(""); onLockChange(false); }}>清除续提输入</Button></fieldset>
    {preview && !pending ? <div className="space-y-2 rounded-md border p-2"><p>将原计划提交给 {approverName}，按政策 v{policy.version} 重新独立办理。</p><p>{preview.reason}</p><Button type="button" size="sm" disabled={disabled || busy} onClick={() => void save(preview)}>确认续提</Button><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button></div> : null}{pending ? <div><p className="break-all">原请求 {pending.request_id} 的结果待确认。</p><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void save(pending)}>按原请求重试并取得回执</Button></div> : null}
  </section>;
}
