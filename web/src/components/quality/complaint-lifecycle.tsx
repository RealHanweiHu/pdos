import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { Complaint } from "./quality-types";

export type ComplaintTransition = {
  to_status: "investigating" | "resolved" | "closed";
  resolution_summary?: string;
};

export function ComplaintLifecycle({ complaint, busy, canManage, canClose, onSubmit }: {
  complaint: Complaint; busy: boolean; canManage: boolean; canClose: boolean;
  onSubmit: (input: ComplaintTransition) => Promise<boolean>;
}) {
  const [summary, setSummary] = useState("");
  return <div className="mt-4 space-y-3 border-t pt-3 text-sm">
    {complaint.resolution_summary && <div><p className="font-medium">已保存的解决结论</p><p className="whitespace-pre-wrap">{complaint.resolution_summary}</p></div>}
    {complaint.closed_at && <p>正式关闭人：{complaint.closed_by_name ?? "姓名不可用"} · 关闭时间：{new Date(complaint.closed_at).toLocaleString("zh-CN")}</p>}
    {canManage && complaint.status === "triaged" && <Button disabled={busy} onClick={() => void onSubmit({ to_status: "investigating" })}>开始投诉调查</Button>}
    {canManage && complaint.status === "investigating" && <form className="space-y-3" onSubmit={event => { event.preventDefault(); void onSubmit({ to_status: "resolved", resolution_summary: summary.trim() }); }}>
      <p>全部关联不符合项关闭后，记录投诉解决结论。投诉不会随整改记录自动关闭。</p>
      <label className="block">解决结论与实际处理范围<textarea required maxLength={20000} value={summary} disabled={busy} onChange={event => setSummary(event.target.value)} className="mt-1 min-h-24 w-full rounded-lg border bg-background p-3"/></label>
      <Button type="submit" disabled={busy || !summary.trim()}>保存投诉解决结论</Button>
    </form>}
    {complaint.status === "resolved" && (canClose ? <div className="space-y-2"><p>核对上方已保存的结论后，由品质人员独立办理正式关闭。</p><Button disabled={busy} onClick={() => void onSubmit({ to_status: "closed" })}>确认正式关闭投诉</Button></div> : <p>已解决，等待品质人员核对并正式关闭。</p>)}
  </div>;
}
