"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Review = { id: string; round_no: number; payload_digest: string; reviewer_user_id: string; reviewer_name: string | null; scenario_id: string; capacity_check_id: string };
type Request = { request_id: string; replaces_review_id: string; expected_review_digest: string; scenario_id: string; capacity_check_id: string; reviewer_user_id: string; reason: string };
export function PlanReviewerChange({ candidateId, review, reviewers, disabled, onLockChange, onChanged }: { candidateId: string; review: Review; reviewers: { id: string; display_name: string }[]; disabled: boolean; onLockChange: (locked: boolean) => void; onChanged: () => Promise<void> }) {
  const [person, setPerson] = useState(""), [reason, setReason] = useState("");
  const [preview, setPreview] = useState<Request | null>(null), [pending, setPending] = useState<Request | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [receipt, setReceipt] = useState("");
  const people = reviewers.filter(user => user.id !== review.reviewer_user_id);
  function prepare() {
    setPreview({ request_id: crypto.randomUUID(), replaces_review_id: review.id, expected_review_digest: review.payload_digest, scenario_id: review.scenario_id, capacity_check_id: review.capacity_check_id, reviewer_user_id: person, reason: reason.trim() });
    setError(""); onLockChange(true);
  }
  async function save(body: Request) {
    setBusy(true); setError(""); setPending(body); onLockChange(true);
    try {
      const response = await fetch(`/api/initial-plans/${candidateId}/reviews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const value = await responseBody(response);
      if (!response.ok) {
        if ([400, 401, 403, 404, 409, 422].includes(response.status)) { setPending(null); setPreview(null); onLockChange(false); }
        throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "审阅人变更未完成，请保留原请求重试");
      }
      if (!isRecord(value) || value.request_id !== body.request_id || typeof value.id !== "string" || typeof value.round_no !== "number") throw new Error("回执不完整，请按原请求重试");
      setReceipt(`已创建第 ${value.round_no} 轮审阅，原请求 ${body.request_id}。`); setPending(null); setPreview(null); setPerson(""); setReason(""); onLockChange(false);
      await onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : "审阅人变更未完成"); }
    finally { setBusy(false); }
  }
  return <section className="space-y-2 rounded-md border p-3 text-xs" aria-label="初始计划审阅人变更"><h4 className="font-medium">更换本轮审阅人</h4><p className="text-muted-foreground">沿用第 {review.round_no} 轮固定的候选、排程、容量检查和责任确认，建立新轮次交给新审阅人；原审阅及签名保留。依据变化时需重新准备完整审阅。</p>{error ? <p role="alert" className="text-destructive">{error}</p> : null}{receipt ? <p role="status">{receipt}</p> : null}
    <fieldset className="space-y-2" disabled={disabled || busy || !!preview || !!pending}><label className="block">新审阅人<select className="mt-1 w-full rounded-md border bg-background p-2" value={person} onChange={e => { setPerson(e.target.value); onLockChange(!!e.target.value || !!reason); }}><option value="">请选择有效审阅人</option>{people.map(user => <option key={user.id} value={user.id}>{user.display_name}</option>)}</select></label><label className="block">人员变更原因<textarea maxLength={2048} className="mt-1 w-full rounded-md border bg-background p-2" value={reason} onChange={e => { setReason(e.target.value); onLockChange(!!e.target.value || !!person); }}/></label><Button type="button" size="sm" variant="outline" disabled={!person || !reason.trim() || !people.some(user => user.id === person)} onClick={prepare}>预览新审阅轮次</Button><Button type="button" size="sm" variant="ghost" onClick={() => { setPerson(""); setReason(""); onLockChange(false); }}>清除变更输入</Button></fieldset>
    {preview && !pending ? <div className="space-y-2 rounded-md border p-2"><p>原审阅人：{review.reviewer_name || review.reviewer_user_id} → {people.find(user => user.id === preview.reviewer_user_id)?.display_name || preview.reviewer_user_id}</p><p>{preview.reason}</p><Button type="button" size="sm" disabled={disabled || busy} onClick={() => void save(preview)}>确认变更并提交新轮次</Button><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button></div> : null}
    {pending ? <div><p className="break-all">原请求 {pending.request_id} 的结果待确认。</p><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void save(pending)}>按原请求重试并取得回执</Button></div> : null}
  </section>;
}
