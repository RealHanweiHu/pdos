"use client";

import { useState } from "react";
import { ScheduleActualCorrections } from "./schedule-actual-corrections";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";

type Constraint = { kind?: "id_handoff_acceptance" | "id_freeze_checkpoint" | "tooling_availability"; round_id?: string; round_version?: number; title?: string; handoff_id?: string; version?: number; forecast_ref: { record_id: string; version: number } | null; source_observation_id: string | null; predecessor_task_id: string | null; predecessor_node_key: string; relation: string; lag: string; lag_unit: string; target_point: string; source_event_row_id: number | null; not_before: string | null; satisfied: boolean; reason: string | null };
type Item = { node_id: string; node_kind: string; task_id: string | null; node_key: string; title: string; status: string; actual_start: string | null; actual_finish: string | null; constraints: Constraint[]; start_blockers: Constraint[]; finish_blockers: Constraint[] };
type State = { items: Item[]; actual_version: number | null; as_of: string };
const statuses: Record<string, string> = { todo: "未开始", in_progress: "进行中", blocked: "受阻", done: "已完成", skipped: "已跳过", pending_approval: "待批准" };
const when = (value: string | null) => value ? new Date(value).toLocaleString() : "尚无实际记录";

export function ScheduleExecutionPanel({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false); const [data, setData] = useState<State | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  async function refresh() { setBusy(true); setError(null); try { setData(await caseLinkRequest<State>(`projects/${projectId}/execution/readiness`)); } catch (failure) { setError(failure instanceof Error ? failure.message : "执行依赖暂不可用"); } finally { setBusy(false); } }
  return <section className="space-y-3 rounded-lg border bg-card p-4">
    <div className="flex items-center justify-between gap-2"><h3 className="font-semibold">执行依赖与实际时间</h3><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => { setOpen(!open); if (!open) void refresh(); }}>{open ? "收起" : "查看等待与开工记录"}</Button></div>
    {open && <div className="space-y-3">
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {data && <p className="text-xs text-muted-foreground">读取时间：{when(data.as_of)} · {data.actual_version ? `实际时间 v${data.actual_version}` : "尚无实际时间版本"}。开工、完成来自实际任务办理记录；等待按后继任务的日历计算。</p>}
      {data && !data.items.length && <p className="text-sm">尚未应用初始计划。</p>}
      {data?.items.map((item) => <article key={item.node_id} className="space-y-2 rounded-md border p-3 text-xs">
        <p className="font-medium">{item.node_key} · {item.title} · {statuses[item.status] ?? item.status}</p>
        <dl className="grid gap-2 sm:grid-cols-2"><div><dt className="text-muted-foreground">实际开工</dt><dd>{when(item.actual_start)}</dd></div><div><dt className="text-muted-foreground">实际完成</dt><dd>{when(item.actual_finish)}</dd></div></dl>
        {item.node_kind === "gate" && <p className="text-muted-foreground">评审结束与取得批准分开；此处依赖完成点以获批结果为准。</p>}
        {!!item.start_blockers.length && !["done", "skipped"].includes(item.status) && <div><p className="font-medium">开工 / 恢复条件</p>{item.start_blockers.map((entry, index) => <p key={index} className="text-destructive">{entry.reason}</p>)}</div>}
        {!!item.finish_blockers.length && !["done", "skipped"].includes(item.status) && <div><p className="font-medium">完成条件</p>{item.finish_blockers.map((entry, index) => <p key={index} className="text-destructive">{entry.reason}</p>)}</div>}
        {item.constraints.length > 0 ? <details><summary className="cursor-pointer">全部前置关系与依据</summary>{item.constraints.map((entry, index) => <div key={index} className="my-2 border-l pl-2"><p>{entry.kind ? (entry.kind === "tooling_availability" ? <a className="text-primary underline" href={`/projects?project=${projectId}&tab=materials&tooling_round_id=${entry.round_id}#tooling-rounds`}>{entry.title} · 工装 v{entry.round_version}</a> : entry.kind === "id_freeze_checkpoint" ? `ID冻结检查点 · 绑定 v${entry.version}` : `ID交接第 ${entry.version} 轮`) : <>{entry.predecessor_node_key} → {item.node_key} · {entry.relation.toUpperCase()} · 滞后 {entry.lag} {entry.lag_unit === "working_hours" ? "工作小时" : "自然日"}</>}</p><p>{entry.target_point === "start" ? "开工" : "完成"}条件：{entry.satisfied ? (entry.kind === "tooling_availability" ? "本轮接受及实际可用依据已满足" : entry.kind === "id_freeze_checkpoint" ? "批准冻结依据已满足" : entry.kind === "id_handoff_acceptance" ? "全部交付项已有效接收" : "依赖时间已满足") : entry.reason}</p>{entry.forecast_ref && <p>提前量依据：预测 v{entry.forecast_ref.version}；前置任务尚无对应实际记录</p>}{entry.source_observation_id && <p>依据：已记录的业务办理观察，可在排程对象中查看原始审计。</p>}{entry.source_event_row_id && <a className="text-primary underline" href={`/projects?project=${projectId}&tab=timeline&event_id=${entry.source_event_row_id}`}>查看实际前置事件</a>}</div>)}</details> : <p className="text-muted-foreground">无排程前置关系</p>}
      </article>)}
      <ScheduleActualCorrections projectId={projectId} onCorrected={() => void refresh()} />
      <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => void refresh()}>刷新执行依赖</Button>
    </div>}
  </section>;
}
