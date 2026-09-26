"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const obj = (v: unknown): Row => isRecord(v) ? v : {};
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const text = (v: unknown) => v == null ? "" : String(v);
export function ChangeExecutionReviewer({ projectId, bindingId, result, digest, disabled, onChanged, onDirtyChange }: { projectId: string; bindingId: string; result: Row; digest: string; disabled: boolean; onChanged: () => Promise<void>; onDirtyChange: (dirty: boolean) => void }) {
  const [reviewer, setReviewer] = useState(""), [reason, setReason] = useState("");
  const [preview, setPreview] = useState<Row | null>(null), [pending, setPending] = useState<Row | null>(null);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [receipt, setReceipt] = useState<Row | null>(null);
  const people = rows(result.replacement_reviewers);
  function prepare() {
    const snapshot = obj(result.snapshot);
    setPreview({ request_id: crypto.randomUUID(), expected_digest: digest, outcome: "ready_for_confirmation", reviewer_user_id: reviewer,
      ...Object.fromEntries(["completed_scope", "excluded_scope", "criteria_response", "follow_up", "reason"].map(key => [key, snapshot[key]])),
      follow_up_responses: snapshot.follow_up_responses ?? [],
      references: rows(snapshot.references).map(ref => Object.fromEntries(["kind", "id", "expected_digest", "role", "correspondence"].map(key => [key, ref[key]]))),
      reviewer_change: { previous_result_id: result.id, expected_review_digest: result.review_digest, reason: reason.trim() } });
    onDirtyChange(true); setError("");
  }
  async function save(body: Row) {
    setPending(body); setBusy(true); setError(""); onDirtyChange(true);
    try {
      const response = await fetch(`/api/projects/${projectId}/changes/execution-items/${bindingId}/results`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const value = await responseBody(response);
      if (!response.ok) {
        if ([400, 401, 403, 404, 409, 422].includes(response.status)) { setPending(null); setPreview(null); onDirtyChange(false); }
        throw new Error(text(obj(obj(value).detail).message) || "确认人变更未完成，请保留原请求重试");
      }
      if (!isRecord(value) || typeof value.id !== "string" || value.request_id !== body.request_id) throw new Error("回执不完整，请保留原请求重试");
      setReceipt(value); setPending(null); setPreview(null); setReviewer(""); setReason(""); onDirtyChange(false);
      await onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : "确认人变更未完成"); }
    finally { setBusy(false); }
  }
  if (result.can_change_reviewer !== true && !pending && !receipt && !preview) return null;
  return <section className="space-y-2 rounded-md border p-3" aria-label="变更执行结果确认人调整"><p className="font-medium">更换具名独立确认人</p><p className="text-muted-foreground">沿用本版完成范围、判据、后续回应及固定证据，生成新版本待确认。原执行人、提交人及本次变更办理人仍不能独立确认这份结果。</p>
    {error ? <p role="alert" className="text-destructive">{error}</p> : null}{receipt ? <p role="status">确认人变更已保存为结果 v{text(receipt.revision_number)}；原请求 {text(receipt.request_id)}。</p> : null}
    {result.can_change_reviewer === true && !pending ? <fieldset className="space-y-2" disabled={disabled || busy || !!preview}><label className="block">新确认人<select className="mt-1 w-full rounded-md border bg-background p-2" value={reviewer} onChange={e => { setReviewer(e.target.value); onDirtyChange(!!e.target.value || !!reason); }}><option value="">选择有效且独立的确认人</option>{people.map(person => <option key={text(person.id)} value={text(person.id)}>{text(person.display_name)}</option>)}</select></label><label className="block">变更原因<textarea className="mt-1 w-full rounded-md border bg-background p-2" maxLength={4000} value={reason} onChange={e => { setReason(e.target.value); onDirtyChange(!!e.target.value || !!reviewer); }}/></label><Button type="button" size="sm" variant="outline" disabled={!reviewer || !reason.trim() || !people.some(person => person.id === reviewer)} onClick={prepare}>预览确认人变更</Button>{!people.length ? <p>当前没有满足独立确认要求的其他成员，请先补齐项目人员安排。</p> : null}<Button type="button" size="sm" variant="ghost" onClick={() => { setReviewer(""); setReason(""); onDirtyChange(false); }}>清除本次变更输入</Button></fieldset> : null}
    {preview && !pending ? <div className="space-y-2 rounded-md border p-2"><p>沿用结果 v{text(result.revision_number)}，交给 {text(people.find(person => person.id === preview.reviewer_user_id)?.display_name) || text(preview.reviewer_user_id)} 独立确认。</p><p>{text(obj(preview.reviewer_change).reason)}</p><Button type="button" size="sm" disabled={disabled || busy} onClick={() => void save(preview)}>确认变更并提交新版本</Button><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button></div> : null}
    {pending ? <div><p className="break-all">原请求 {text(pending.request_id)} 的结果待确认。</p><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void save(pending)}>按原请求重试并取得回执</Button></div> : null}
  </section>;
}
