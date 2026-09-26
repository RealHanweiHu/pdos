"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { transitionTask } from "@/components/projects/project-work-item-api";
import type { TaskTransitionInput } from "@/components/projects/project-work-item-types";

const labels: Record<string, string> = { todo: "待开始", in_progress: "进行中", blocked: "已阻塞", done: "已完成", skipped: "已跳过", pending_approval: "待批准" };
export function TaskDirectActions({ projectId, task, preparedAt, canEdit, loading, startBlockers, finishBlockers, receiver, onRefresh, onChanged }: {
  projectId: string;
  task: { id: string; title: string; status: string; updatedAt: string; blockedReason: string | null; completionEvidence: string | null };
  preparedAt: string; canEdit: boolean; loading: boolean; startBlockers: string[]; finishBlockers: string[]; receiver: string;
  onRefresh: () => void; onChanged: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false), [evidence, setEvidence] = useState<string | undefined>(), [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null), [failedBasis, setFailedBasis] = useState<string | null>(null);
  const blocked = busy || loading || !canEdit || failedBasis === preparedAt;
  async function apply(input: TaskTransitionInput) {
    setBusy(true); setError(null); setNotice(null);
    try {
      const result = await transitionTask(projectId, task.id, { ...input, expected_updated_at: task.updatedAt });
      const message = `「${result.title}」已更新为${labels[result.status] ?? result.status}。`;
      setNotice(message); setFailedBasis(preparedAt); onChanged(message); onRefresh();
    } catch (e) {
      setFailedBasis(preparedAt); setError(e instanceof Error ? e.message : "暂未取得办理结果，请刷新实际任务核对后继续");
    } finally { setBusy(false); }
  }
  return <section aria-label="在工作卡办理任务" className="space-y-3 rounded-lg border bg-background p-3">
    <div className="flex flex-wrap items-center justify-between gap-2"><h4 className="font-medium">在这里办理 · {labels[task.status] ?? task.status}</h4><Button type="button" size="sm" variant="outline" disabled={busy || loading} onClick={onRefresh}>刷新实际状态</Button></div>
    <p className="text-xs text-muted-foreground">按业务规则办理。开始后登记实际进展，完成后更新原任务及其计划进展；相关问题、测试、交接和签核仍按各自流程核对。</p>
    <p className="text-xs">计划接收人：{receiver}。{receiver === "未指定" ? "没有具名接收人时，不推定已交接。" : "完成任务不自动代表对方已接收。"}</p>
    {!canEdit && <p>当前权限可查看资料，不能在此修改任务。</p>}
    {task.status === "pending_approval" && <p>任务仍待批准，请从来源或原任务入口查看批准要求。</p>}
    {task.status === "blocked" && <p className="whitespace-pre-wrap text-destructive">阻塞说明：{task.blockedReason || "请核对原任务"}</p>}
    {task.status === "in_progress" && <label className="block text-sm">完成依据或实际交付位置<textarea className="mt-1 w-full rounded-md border bg-background p-2" rows={3} maxLength={2000} disabled={busy || !canEdit} value={evidence ?? task.completionEvidence ?? ""} onChange={e => setEvidence(e.target.value)}/></label>}
    <div className="flex flex-wrap gap-2">
      {task.status === "todo" && <Button type="button" size="sm" disabled={blocked || startBlockers.length > 0} onClick={() => void apply({ to_status: "in_progress" })}>开始任务</Button>}
      {task.status === "in_progress" && <Button type="button" size="sm" disabled={blocked || finishBlockers.length > 0} onClick={() => void apply({ to_status: "done", completion_evidence_ref: (evidence ?? task.completionEvidence ?? "").trim() || null })}>登记完成</Button>}
      {task.status === "blocked" && <Button type="button" size="sm" variant="outline" disabled={blocked} onClick={() => void apply({ to_status: "todo" })}>解除阻塞，回到待开始</Button>}
    </div>
    {["todo", "in_progress"].includes(task.status) && <details><summary className="cursor-pointer text-sm">遇到阻塞，记录原因</summary><div className="mt-2 space-y-2"><label className="block text-sm">真实阻塞原因及需要的帮助<textarea className="mt-1 w-full rounded-md border bg-background p-2" rows={2} maxLength={20000} disabled={busy || !canEdit} value={reason} onChange={e => setReason(e.target.value)}/></label><Button type="button" size="sm" variant="outline" disabled={blocked || !reason.trim()} onClick={() => void apply({ to_status: "blocked", blocked_reason: reason.trim() })}>记录阻塞</Button></div></details>}
    {failedBasis === preparedAt && !loading && <p>请刷新实际任务核对最新结果后继续；填写内容会保留。</p>}
    {notice && <p role="status">{notice}</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
  </section>;
}
