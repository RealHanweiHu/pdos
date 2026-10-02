"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { requestFinding, reviewFinding, applyFinding, restoreFinding } from "./ai-api";
import { FindingReviewUndo } from "./finding-review-undo";
import { FindingLifecycle } from "./finding-lifecycle";
import type { AiFinding } from "./ai-types";
import { FindingAppliedReceipt, FindingDraftDiff, FindingProposal, PayloadEditor, findingApplyEffect, proposalReady } from "./finding-proposal";

const statusLabels = { pending_review: "待审阅", accepted: "已接受，待应用", applied: "已应用", rejected: "已拒绝", archived: "已归档" };

export function ConversationFinding({ findingId, onRecorded, onLoaded, onUnconfirmed, initialFinding, showUndo = true }: { findingId: string; onRecorded?: (finding: AiFinding) => void; onLoaded?: (finding: AiFinding) => void; onUnconfirmed?: () => void; initialFinding?: AiFinding; showUndo?: boolean }) {
  const [finding, setFinding] = useState<AiFinding | null>(initialFinding ?? null);
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [undoVersion, setUndoVersion] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const [loaded, setLoaded] = useState(!!initialFinding), [busy, setBusy] = useState(false), [stale, setStale] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function refresh() {
    setLoaded(true); setBusy(true); setError(null); setConfirming(false);
    try { const current = await requestFinding(findingId); setFinding(current); onLoaded?.(current); setStale(false); }
    catch (e) { setFinding(null); setStale(true); onUnconfirmed?.(); setError(e instanceof Error ? e.message : "当前无法读取候选"); }
    finally { setBusy(false); }
  }
  async function record(work: () => Promise<AiFinding>) {
    setBusy(true); setError(null);
    try { const result = await work(); setFinding(result); setUndoVersion(["accepted", "rejected"].includes(result.status) ? result.updated_at : null); setDraft(null); setConfirming(false); onRecorded?.(result); }
    catch (e) { setStale(true); setConfirming(false); onUnconfirmed?.(); setError(e instanceof Error ? e.message : "办理结果未确认，请刷新当前裁决后核对"); }
    finally { setBusy(false); }
  }
  const payload = finding?.status === "pending_review" ? draft ?? finding.proposed_payload : finding?.accepted_payload ?? finding?.proposed_payload ?? {};
  const locked = busy || stale;
  return <details className="rounded-lg border bg-background p-3" onToggle={e => { if (e.target === e.currentTarget && e.currentTarget.open && !loaded && !busy) void refresh(); }}>
    <summary className="cursor-pointer text-sm font-medium">{finding?.title ?? "打开建议、依据与办理"}{finding && <span className="ml-2 text-xs">{statusLabels[finding.status]}</span>}</summary>
    <div className="mt-3 space-y-3">
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void refresh()}>刷新当前裁决</Button>
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
      {stale && <p className="text-xs">刷新后核对实际状态再办理；未提交的修改和理由保留。</p>}
      {finding && <>
        <p className="whitespace-pre-wrap text-sm">{finding.summary}</p>
        <p className="text-xs text-muted-foreground">接受只保存人工裁决；独立应用时再次核对来源、当前状态与权限。</p>
        {finding.superseded_by && <p className="text-sm text-pending">此建议已有新修订。<a href={`/ai-review?finding=${finding.superseded_by}`} className="ml-2 underline">查看最新建议</a></p>}
        {draft && finding.status === "pending_review" ? <fieldset disabled={locked}><PayloadEditor finding={finding} payload={draft} onChange={setDraft}/></fieldset> : <FindingProposal finding={finding} payload={payload}/>}
        <FindingDraftDiff original={finding.proposed_payload} changed={payload}/>
        <details className="rounded-md border p-3 text-sm"><summary className="cursor-pointer">证据与来源</summary>
          {finding.evidence.length ? <ul className="mt-2 space-y-2">{finding.evidence.map((evidence, index) => <li key={`${evidence.event_row_id}:${index}`}><a className="text-primary underline" href={evidence.href}>{evidence.label}</a></li>)}</ul> : <p className="mt-2">请核对上方类型化内容中的原句、字段引用和固定版本；没有可核对依据时不能据此确认业务结论。</p>}
          <p className="mt-2 text-xs text-muted-foreground">运行记录：{finding.run_id}</p>
          <a className="text-primary underline" href={`/ai-review?finding=${findingId}`}>查看完整收件箱记录</a>
        </details>
        <p className="rounded-md border p-3 text-sm">实际应用及下一步：{findingApplyEffect(finding)}</p>
        {finding.status === "pending_review" && !finding.superseded_by && <div className="space-y-2">
          <label className="block text-xs">审阅说明／拒绝理由<textarea className="mt-1 w-full rounded-md border bg-background p-2" maxLength={3000} disabled={busy} value={reason} onChange={e => setReason(e.target.value)}/></label>
          <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => setDraft(draft ? null : structuredClone(finding.proposed_payload))}>{draft ? "放弃未提交修改" : "核对并补齐资料"}</Button>
            <Button size="sm" disabled={locked || !proposalReady(finding, payload)} onClick={() => void record(() => reviewFinding(findingId, { decision: "accepted", ...(draft ? { edited_payload: draft } : {}), comment: reason || undefined }))}>接受此候选</Button>
            <Button size="sm" variant="outline" disabled={locked || !reason.trim()} onClick={() => void record(() => reviewFinding(findingId, { decision: "rejected", comment: reason }))}>按所填理由拒绝</Button>
          </div>
        </div>}
        {finding.status !== "pending_review" && draft && <details className="text-sm"><summary>之前未提交的修改（原裁决已变化）</summary><FindingProposal finding={finding} payload={draft}/><Button variant="outline" size="sm" onClick={() => setDraft(null)}>放弃此份未提交修改</Button></details>}
        {finding.status === "accepted" && !finding.superseded_by && (confirming ? <section className="space-y-3 rounded-md border p-3" aria-label="最终写入预览">
          <h3 className="text-sm font-semibold">按已接受内容独立应用</h3><FindingProposal finding={finding} payload={finding.accepted_payload ?? {}}/>
          <div className="flex gap-2"><Button size="sm" disabled={locked} onClick={() => void record(() => applyFinding(findingId))}>确认独立应用</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => setConfirming(false)}>返回核对</Button></div>
        </section> : <Button size="sm" disabled={locked} onClick={() => setConfirming(true)}>核对应用内容</Button>)}
        {showUndo && undoVersion === finding.updated_at && <FindingReviewUndo key={undoVersion} items={[finding]} onRecorded={result => { const current = result.items.find(item => item.id === finding.id); if (current) { setFinding(current); setUndoVersion(null); setConfirming(false); onRecorded?.(current); } }}/>}
        {finding.review_comment && <p className="whitespace-pre-wrap text-xs">已记录审阅意见：{finding.review_comment}</p>}
        {finding.status === "archived" && <div className="space-y-2"><p className="text-xs">恢复后重新获得 14 天处理期；恢复不会接受或应用建议。</p><Button size="sm" disabled={locked} onClick={() => void record(() => restoreFinding(findingId))}>恢复到待审队列</Button></div>}
        <FindingAppliedReceipt finding={finding}/>
        <FindingLifecycle key={`${finding.id}:${finding.updated_at}`} findingId={finding.id}/>
      </>}
    </div>
  </details>;
}
