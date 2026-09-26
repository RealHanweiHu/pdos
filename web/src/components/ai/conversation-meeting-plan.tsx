"use client";

import { isRecord } from "@/components/workspace-api";
import { MeetingPlanning } from "@/components/projects/meeting-planning";
import { MeetingPlanningReview } from "@/components/projects/meeting-planning-review";

export function ConversationMeetingPlanResult({ projectId, source, receipt }: { projectId: string; source: Record<string, unknown>; receipt: Record<string, unknown> }) {
  const finding = isRecord(receipt.finding) ? receipt.finding : null;
  const reading = isRecord(receipt.reading) && isRecord(receipt.reading.assessment) ? receipt.reading.assessment : null;
  return <div className="space-y-3 rounded-md border p-3 text-xs">
    {receipt.source_current === false && <p className="text-destructive">原起草要求、人员或依据已变化。历史回执保留，请修订资料后发起新的请求。</p>}
    {typeof source.brief_id === "string" && <MeetingPlanning key={source.brief_id} projectId={projectId} initialBriefId={source.brief_id} showRuns={false} readOnly/>}
    {reading?.disposition === "insufficient_evidence" && <p>所选资料不足，未形成会议草案。</p>}
    {reading && Array.isArray(reading.open_questions) && reading.open_questions.map((question, i) => <p key={i}>待补：{String(question)}</p>)}
    {finding && typeof finding.id === "string" && <MeetingPlanningReview projectId={projectId} findingId={finding.id}/>}
    {!finding && receipt.finding_id && !reading ? <p>原运行已有候选回执；当前能力状态未开放候选读取，请沿运行记录核对。</p> : null}
  </div>;
}
