"use client";

import { useState } from "react";
import { ChangeDiscussionRuns } from "@/components/projects/change-discussion-runs";
import { DiscussionStatement } from "@/components/projects/change-discussion-brief";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { AgentRunProgressPanel } from "./agent-run-progress";
import { ChangeToolReceipts } from "./change-tool-receipts";
import { ConversationFinding } from "./conversation-finding";

type Row = Record<string, unknown>;
const obj = (value: unknown): Row => isRecord(value) ? value : {};
const text = (value: unknown) => value == null ? "" : String(value);
const statuses: Record<string, string> = { queued: "等待处理", running: "处理中", succeeded: "处理完成", degraded: "未完成", failed: "已停止" };
function reason(code: unknown) {
  const key = text(code);
  if (key.startsWith("BUDGET_") || key === "DAILY_BUDGET_EXCEEDED") return "原请求累计预算或有效时限已不足";
  return ({ DISCUSSION_FOLLOWUP_SOURCE_CHANGED: "原分析资料已变化", DISCUSSION_FOLLOWUP_CONTEXT_LIMIT: "讨论资料超过本次读取容量", APPLICATION_AUTHORIZATION_CHANGED: "原授权已变化", APPLICATION_REQUEST_CANCELLED: "原请求已停止", CAPABILITY_SHADOW: "接续分析尚待阶段评测", CAPABILITY_DISABLED: "接续分析当前未开放" } as Record<string, string>)[key] ?? "原讨论、资料或运行条件暂不可用于接续";
}

export function ChangeDiscussionContinuation({ projectId, ecrId, sourceDigest, value, disabled = false, onRefresh }: {
  projectId: string; ecrId: string; sourceDigest: string; value: Row;
  disabled?: boolean; onRefresh: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const choice = obj(value.discussion_choice), runtime = obj(value.discussion_runtime);
  const followup = obj(value.discussion_followup), input = obj(value.discussion_input);
  const discussionId = text(runtime.run_id || obj(value.convened_discussion).run_id || input.discussion_run_id);
  const cancelled = runtime.related_request_cancelled === true;
  const unfinished = ["degraded", "failed"].includes(text(runtime.status));
  async function act(path: string, body: Row) {
    setBusy(true); setError(null);
    try {
      const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await responseBody(response);
      if (!response.ok) throw new Error(text(obj(obj(result).detail).message) || "本次操作未完成，请读取原记录");
      await onRefresh();
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  if (!discussionId && !choice.action) return null;
  return <div className="space-y-3">
    {choice.action != null && <div className="space-y-2 rounded-md bg-muted/40 p-2"><p>Agent 的讨论发起判断：{choice.action === "convene" ? "请求专业比较" : choice.action === "not_needed" ? "当前无需多专业讨论" : "资料不足，未发起"}。</p><DiscussionStatement value={obj(choice.reason)} labels={obj(value.discussion_reference_labels)}/></div>}
    {discussionId && <div className="space-y-2">
      <p>{input.discussion_run_id ? "本次采用固定版本的讨论摘要重新分析，原分析候选仍保留。" : "原请求已创建关联讨论，原分析候选不代表已采用后续发言。"}发言、分歧和缺项可在下方核对。</p>
      {runtime.status != null && <p>讨论进度：{runtime.recovery_requested ? "等待按原进度接续" : statuses[text(runtime.status)] ?? "读取当前进度"}{cancelled ? "；本组后续运行已停止" : ""}。</p>}
      <ChangeDiscussionRuns projectId={projectId} ecrId={ecrId} source={{ digest: sourceDigest }} focusedRunId={discussionId}/>
    </div>}
    {value.discussion_followup_enabled === true && discussionId && <div className="space-y-2 rounded-md border p-3">
      <p className="font-medium">讨论后的分析</p>
      <p>{followup.run_id ? statuses[text(followup.status)] ?? "读取运行状态" : cancelled ? "已停止，不再启动后续分析" : value.discussion_followup_error != null ? reason(value.discussion_followup_error) : unfinished ? "讨论尚未完整结束，未启动后续分析；请先查看缺项或办理原讨论接续" : "等待完整讨论结果与原预算检查"}。</p>
      {followup.error_code != null && <p>{reason(followup.error_code)}。原记录已保留。</p>}
      {followup.discussion_current === false && <p className="text-destructive">本次所用讨论资料已变化，请重新核对后办理。</p>}
      {typeof followup.run_id === "string" && <AgentRunProgressPanel projectId={projectId} runId={followup.run_id}/>}
      <ChangeToolReceipts value={followup.tool_receipts}/>
      {followup.disposition === "insufficient_evidence" && <p>讨论后的分析仍缺少依据，尚未形成新候选。</p>}
      {Array.isArray(followup.missing) && followup.missing.length > 0 && <p className="whitespace-pre-wrap">待补资料：{followup.missing.map(String).join("；")}</p>}
      {typeof followup.finding_id === "string" && <ConversationFinding findingId={followup.finding_id}/>}
      {followup.requested_by_me === true && value.followup_available === true && !cancelled && (followup.status === "running" || followup.error_code === "APPLICATION_RUN_LEASE_EXPIRED") && <Button type="button" size="sm" variant="outline" disabled={disabled || busy || followup.discussion_current === false || value.current === false || value.sources_current === false} onClick={() => void act(`/api/projects/${projectId}/changes/ecrs/${ecrId}/analysis-runs`, { request_id: followup.request_id, expected_digest: followup.source_digest, depth: followup.depth, user_instruction: followup.user_instruction, allow_discussion: false, include_supplier_notices: followup.include_supplier_notices === true })}>读取 / 恢复讨论后的分析</Button>}
      <p className="text-xs text-muted-foreground">原分析、讨论和接续分析共用累计预算。新候选仍须人工审阅与独立应用。</p>
    </div>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
  </div>;
}
