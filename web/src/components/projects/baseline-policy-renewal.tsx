"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Request = { request_id: string; scenario_id: string; capacity_check_id: string; policy_id: string; expected_baseline_id: string; reason: string; policy_renewal: { previous_change_id: string; expected_digest: string } };
export function BaselinePolicyRenewal({ projectId, original, policy, approverName, disabled, onLockChange, onChanged }: { projectId: string; original: { id: string; scenario_id: string; capacity_check_id: string; base_baseline_id: string; payload_digest: string }; policy: { id: string; version: number; four_eyes: boolean; authority_basis: string }; approverName: string; disabled: boolean; onLockChange: (locked: boolean) => void; onChanged: (replacementId: string) => Promise<void> }) {
  const [reason, setReason] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [preview, setPreview] = useState<Request | null>(null), [pending, setPending] = useState<Request | null>(null), [receipt, setReceipt] = useState("");
  async function save(body: Request) {
    setPending(body); setBusy(true); setError(""); onLockChange(true);
    try {
      const response = await fetch(`/api/projects/${projectId}/execution/baseline-changes`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const value = await responseBody(response);
      if (!response.ok) {
        if ([400, 401, 403, 404, 409, 422].includes(response.status)) { setPending(null); setPreview(null); onLockChange(false); }
        throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "续提结果未确认，请保留原请求重试");
      }
      if (!isRecord(value) || value.request_id !== body.request_id || typeof value.id !== "string") throw new Error("回执不完整，请按原请求重试");
      setReceipt(`旧申请已撤回，新申请 ${value.id} 待批准；原请求 ${body.request_id}。`); setPending(null); setPreview(null); setReason(""); onLockChange(false); await onChanged(value.id);
    } catch (e) { setError(e instanceof Error ? e.message : "续提失败"); }
    finally { setBusy(false); }
  }
  return <section className="space-y-2 rounded-md border p-3" aria-label="基线申请按新政策续提"><h4 className="font-medium">撤回旧申请并按当前政策续提</h4><p>当前政策 v{policy.version}：由 {approverName} 批准；{policy.four_eyes ? "提交人与批准人分离" : "允许同人提交批准"}。</p><p className="whitespace-pre-wrap">授权依据：{policy.authority_basis}</p><p className="text-muted-foreground">保留原拟变更日期、节点、依赖、容量及判据。成功后同时撤回本申请并建立新申请；新批准与基线应用继续分别办理。依据变化时须重新准备完整变更。</p>{error ? <p role="alert" className="text-destructive">{error}</p> : null}{receipt ? <p role="status">{receipt}</p> : null}<fieldset disabled={disabled || busy || !!preview || !!pending} className="space-y-2"><label className="block">本次撤回与续提原因<textarea className="mt-1 w-full rounded-md border bg-background p-2" maxLength={2048} value={reason} onChange={e => { setReason(e.target.value); onLockChange(!!e.target.value); }}/></label><Button type="button" size="sm" variant="outline" disabled={!reason.trim()} onClick={() => { setPreview({ request_id: crypto.randomUUID(), scenario_id: original.scenario_id, capacity_check_id: original.capacity_check_id, policy_id: policy.id, expected_baseline_id: original.base_baseline_id, reason: reason.trim(), policy_renewal: { previous_change_id: original.id, expected_digest: original.payload_digest } }); onLockChange(true); }}>预览撤回与续提</Button><Button type="button" size="sm" variant="ghost" onClick={() => { setReason(""); onLockChange(false); }}>清除续提输入</Button></fieldset>
    {preview && !pending ? <div className="space-y-2 rounded-md border p-2"><p>将撤回此申请，沿用原变更内容提交给 {approverName}，按政策 v{policy.version} 重新办理。</p><p>{preview.reason}</p><Button type="button" size="sm" disabled={disabled || busy} onClick={() => void save(preview)}>确认撤回并续提</Button><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button></div> : null}{pending ? <div><p className="break-all">原请求 {pending.request_id} 的结果待确认。</p><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void save(pending)}>按原请求重试并取得回执</Button></div> : null}
  </section>;
}
