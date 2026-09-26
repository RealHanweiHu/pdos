"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";
import { EvidenceView } from "@/components/cases/plan-reviews";

type Node = { node_key: string; task_id: string; schedule_node_id: string; receiver_user_id: string; discipline: string; completion_criteria: string; node_snapshot: { title: string; expected_output: string; effort_hours: string | null; waiting_days: number } };
type Application = { id: string; execution_request_id: string; baseline_id: string; created_at: string; reason: string; nodes: Node[]; baseline: { version: number; contract: { node_times: { node_id: string; window: { start: string | null; end: string | null } }[] } }; receipt: unknown };
type Result = { application: Application; already_applied: boolean; diff: Record<string, unknown> | null };
type State = { application: Application | null; can_apply: boolean };

export function InitialPlanApplicationPanel({ projectId, requests, person, onApplied }: { projectId: string; requests: { id: string; round_no: number; state: string; payload_digest: string }[]; person: (id: string) => string; onApplied: () => Promise<void> }) {
  const [open, setOpen] = useState(false); const [data, setData] = useState<State | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null); const [notice, setNotice] = useState<string | null>(null); const [diff, setDiff] = useState<Record<string, unknown> | null>(null);
  const [requestId, setRequestId] = useState(""); const [reason, setReason] = useState(""); const [read, setRead] = useState(false); const ids = useRef(new Map<string, string>());
  const path = `projects/${projectId}/execution/application`; const selected = requests.find((item) => item.id === requestId);
  async function load() { setData(await caseLinkRequest<State>(path)); }
  async function refresh() { setBusy(true); setError(null); try { await load(); } catch (failure) { setError(failure instanceof Error ? failure.message : "计划应用暂不可用"); } finally { setBusy(false); } }
  async function apply() {
    if (!selected) return;
    setBusy(true); setError(null); setNotice(null); setDiff(null);
    const body = { execution_request_id: selected.id, expected_digest: selected.payload_digest, reason }; const key = JSON.stringify(body); let id = ids.current.get(key); if (!id) { id = crypto.randomUUID(); ids.current.set(key, id); }
    try { const result = await caseLinkRequest<Result>(path, { ...body, request_id: id }); setData({ application: result.application, can_apply: true }); setDiff(result.diff); setRead(false); setNotice(result.diff ? "已保留现有计划并生成差异。" : result.already_applied ? "该计划已应用，返回原任务与基线。" : `已创建 ${result.application.nodes.length} 项任务及基线 v${result.application.baseline.version}。`); await onApplied(); } catch (failure) { setError(failure instanceof Error ? failure.message : "计划应用未完成"); } finally { setBusy(false); }
  }
  const when = (value: string | null) => value ? new Date(value).toLocaleString() : "未知";
  return <section className="space-y-3 border-t pt-3"><Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => { setOpen(!open); if (!open) void refresh(); }}>{open ? "收起任务与基线" : "独立应用计划与查看基线"}</Button>{open && <div className="space-y-3">
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-sm">{notice}</p>}
    <p className="text-xs text-muted-foreground">应用前重新核对已批准来源、责任确认及容量。成功后同时保留任务、依赖、基线和回执；正式资源预约仍按资源办理入口确认。</p>
    {data?.can_apply && <form className="space-y-2" onSubmit={(event) => { event.preventDefault(); void apply(); }}>
      <label className="block text-sm">执行批准<select className="mt-1 w-full rounded-md border bg-background p-2 text-sm" required value={requestId} onChange={(event) => { setRequestId(event.target.value); setRead(false); }}><option value="">选择已批准的执行申请</option>{requests.filter((item) => item.state === "approved").map((item) => <option key={item.id} value={item.id}>执行申请第 {item.round_no} 轮{data.application?.execution_request_id === item.id ? " · 已应用" : ""}</option>)}</select></label>
      <label className="block text-sm">应用说明<textarea className="mt-1 w-full rounded-md border bg-background p-2 text-sm" required maxLength={2048} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={read} onChange={(event) => setRead(event.target.checked)} />已核对上述批准计划，确认独立创建任务与基线；如已有首版，仅查看差异</label>
      <Button type="submit" size="sm" disabled={busy || !read || !selected || !reason.trim()}>{data.application ? "查看已有结果或生成差异" : "应用已批准计划"}</Button>
    </form>}
    {diff && <div className="rounded-md border p-3 text-xs"><h4 className="mb-2 font-medium">与现有首版的差异</h4><EvidenceView value={diff} /></div>}
    {data?.application && <article className="space-y-3 rounded-md border p-3 text-xs"><p className="font-medium">已应用 · 基线 v{data.application.baseline.version} · {new Date(data.application.created_at).toLocaleString()}</p><p>{data.application.reason}</p><a className="text-primary underline" href={`/projects?project=${projectId}&tab=work-items`}>进入实际任务列表</a>
      <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr><th className="p-2">任务</th><th className="p-2">接收人 / 交付判据</th><th className="p-2">批准基线时间</th></tr></thead><tbody>{data.application.nodes.map((node) => { const window = data.application!.baseline.contract.node_times.find((item) => item.node_id === node.schedule_node_id)?.window; return <tr key={node.node_key} className="border-t align-top"><td className="p-2"><p className="font-medium">{node.node_key} · {node.node_snapshot.title}</p><p>{node.discipline} · 工时 {node.node_snapshot.effort_hours ?? "未知"} · 等待 {node.node_snapshot.waiting_days} 天</p><p className="text-muted-foreground">任务编号：{node.task_id}</p></td><td className="p-2"><p>{person(node.receiver_user_id)}</p><p>{node.node_snapshot.expected_output}</p><p>{node.completion_criteria}</p></td><td className="p-2">{when(window?.start ?? null)}<br />{when(window?.end ?? null)}</td></tr>; })}</tbody></table></div>
      <details><summary className="cursor-pointer">原子应用回执与对象映射</summary><EvidenceView value={data.application.receipt} /></details>
    </article>}
    <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => void refresh()}>刷新任务与基线</Button>
  </div>}</section>;
}
