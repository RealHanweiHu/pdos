"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { RiskFollowupResults } from "@/components/projects/risk-followup-results";
import type { MyWorkRiskFollowup } from "./my-work-types";

// Keep the selected form mounted when its completed item leaves the queue.
export function RiskFollowupWork({ item, onClose, onRecorded }: {
  item: MyWorkRiskFollowup; onClose: () => void; onRecorded: () => void;
}) {
  return <section className="mt-4 space-y-3 rounded-lg border bg-card p-4" aria-label="风险处理结果办理">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-semibold">{item.project.code} · {item.title}</h2><Button type="button" size="sm" variant="ghost" onClick={onClose}>关闭办理区</Button></div>
    <p className="text-xs text-muted-foreground">提交或补齐本人任务的处理结果，或按指定接收人身份核对。办后保留原结果与回执。</p>
    <Link className="text-xs text-primary underline" href={`/projects?project=${item.project.id}&tab=work-items&entity_id=${item.risk_id}`}>查看原风险</Link>
    <RiskFollowupResults key={item.task_id} projectId={item.project.id} riskId={item.risk_id} taskId={item.task_id} onRecorded={onRecorded}/>
  </section>;
}
