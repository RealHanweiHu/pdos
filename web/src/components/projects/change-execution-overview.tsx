"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import { scopeKinds, sourceLabel } from "./change-impact-scope";

type Row = Record<string, unknown>;
const obj = (v: unknown): Row => isRecord(v) ? v : {};
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const text = (v: unknown) => v == null || v === "" ? "未记录" : String(v);
const statuses: Record<string, string> = {
  unassigned: "待安排任务", no_result: "待登记实际结果", evidence_gaps: "证据待补齐 / 重核",
  returned: "已退回补齐", follow_up: "仍需后续处理", recorded: "执行说明已记录",
  awaiting_confirmation: "待独立确认", verified: "当前证据支持独立确认", no_action: "本版未要求执行",
};
const actions: Record<string, string> = { retest: "复验", rereview: "复审", recertification: "复认证", coordination: "协同", none: "无需执行" };
const taskStatuses: Record<string, string> = { todo: "待执行", in_progress: "执行中", blocked: "受阻", done: "任务已完成", skipped: "任务已跳过", pending_approval: "待批准" };
const evidenceKinds: Record<string, string> = { test_run: "实际测试", engineering_review: "专业复审", certification: "认证记录", document: "项目文件" };

export function ChangeExecutionOverview({ projectId, ecrId, refreshKey }: { projectId: string; ecrId: string; refreshKey: number }) {
  const [enabled, setEnabled] = useState(false);
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<Row | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const [action, setAction] = useState("all");
  const [loadedKey, setLoadedKey] = useState("");
  const key = `${projectId}:${ecrId}:${refreshKey}:${revision}`;
  const pending = enabled && loadedKey !== key;
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    void fetch(`/api/projects/${projectId}/changes/ecrs/${ecrId}/execution-overview`, { cache: "no-store" })
      .then(async response => {
        const value: unknown = await response.json();
        if (!response.ok || !isRecord(value) || !Array.isArray(value.items)) {
          throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "执行汇总暂不可读，请重试");
        }
        if (active) { setData(value); setError(null); }
      })
      .catch((error: unknown) => { if (active) { setData(null); setError(error instanceof Error ? error.message : "读取失败"); } })
      .finally(() => { if (active) setLoadedKey(key); });
    return () => { active = false; };
  }, [enabled, projectId, ecrId, refreshKey, revision, key]);
  const items = rows(data?.items);
  const scope = obj(data?.scope);
  const counts = obj(data?.counts);
  const person = (id: unknown) => text(rows(data?.people).find(p => p.id === id)?.display_name ?? id);
  const visible = items.filter(row => (action === "all" || obj(row.item).action === action) &&
    (filter === "all" || (filter === "remaining" ? row.required === true && row.status !== "verified" : row.status === filter)));
  return <details className="rounded-md border p-3" onToggle={event => { if (event.currentTarget.open) setEnabled(true); }}>
    <summary className="cursor-pointer font-medium">获批范围执行汇总</summary>
    <div className="mt-3 space-y-3 text-xs">
      <p className="text-muted-foreground">逐项核对本版范围的任务、实际证据和独立确认。汇总只覆盖已纳入的范围；任务关闭、工程变更审批与生产生效仍按原流程办理。</p>
      {pending && <p role="status">正在重新核对本版范围和原证据…</p>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {!pending && data && <>
        <p>读取时间：{text(data.read_at)} · 本版 {items.length} 项，其中 {text(data.required_count)} 项要求实际执行。</p>
        {data.scope != null && <div className="space-y-1 rounded-md bg-muted/40 p-3">
          <p className="font-medium">获批范围 v{text(scope.revision_number)}</p>
          <p className="whitespace-pre-wrap">覆盖：{text(scope.coverage)}</p>
          <p className="whitespace-pre-wrap">排除：{text(scope.exclusions)}</p>
        </div>}
        {Array.isArray(data.scope_gaps) && data.scope_gaps.length > 0 && <p className="text-primary">{data.scope_gaps.map(String).join("；")}</p>}
        {data.all_required_verified === true && <p role="status">本版要求执行的各条目均已有独立确认，当前原证据仍支持这些确认。请继续核对逐项未覆盖范围与后续要求。</p>}
        {Number(data.historical_binding_count) > 0 && <p>另有 {text(data.historical_binding_count)} 条历史范围任务保留在原执行安排中，未计入本版。</p>}
        {rows(data.source_changes).length > 0 && <details><summary className="cursor-pointer">获批来源的当前变化（{rows(data.source_changes).length}）</summary><ul className="mt-2 space-y-1">{rows(data.source_changes).map(change => <li key={`${text(change.kind)}:${text(change.id)}`}>{scopeKinds[text(change.kind)] ?? text(change.kind)} · {sourceLabel(obj(change.before))}：{change.blocking ? "设计或原证据变化，需重核范围" : "执行进展变化，结合实际结果核对"}</li>)}</ul></details>}
        <div className="flex flex-wrap gap-3">
          <label>查看条目<select className="ml-2 rounded-md border bg-background p-2" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">全部范围</option><option value="remaining">尚待办理的执行项</option>{Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{label}（{Number(counts[value] ?? 0)}）</option>)}</select></label>
          <label>执行类别<select className="ml-2 rounded-md border bg-background p-2" value={action} onChange={e => setAction(e.target.value)}><option value="all">全部类别</option>{Object.entries(actions).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        </div>
        <p className="text-muted-foreground">当前显示 {visible.length} / {items.length} 项。</p>
        {visible.map(row => {
          const item = obj(row.item), task = obj(row.task), result = obj(row.result), resultScope = obj(row.result_scope), confirmation = obj(row.confirmation);
          return <article className="space-y-2 rounded-md border p-3" key={text(item.key)}>
            <p className="font-medium">{scopeKinds[text(item.kind)] ?? text(item.kind)} · {sourceLabel(obj(item.snapshot))} · {actions[text(item.action)]}</p>
            <p className={row.status === "verified" || row.status === "no_action" ? "text-muted-foreground" : "text-primary"}>{statuses[text(row.status)]}</p>
            <p className="whitespace-pre-wrap">范围依据：{text(item.basis)}</p>
            <p className="whitespace-pre-wrap">获批要求：{text(item.next_action)}</p>{Number(row.follow_up_count)>0&&<p>已安排 {text(row.follow_up_count)} 个后续补齐任务，逐项回应请在结果办理中核对。</p>}
            {row.task != null && <><p><a className="text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${text(task.id)}`}>{text(task.title)}</a> · {taskStatuses[text(task.status)] ?? text(task.status)} · {person(task.assignee_user_id)} · 截止 {text(task.due_date)}</p><p className="whitespace-pre-wrap">完成判据：{text(row.completion_criteria)}</p></>}
            {row.result != null && <>
              <p>结果 v{text(result.revision_number)} · {person(result.created_by_user_id)} · {text(result.created_at)} · 确认人 {person(result.reviewer_user_id)}</p>
              <p className="whitespace-pre-wrap">已完成：{text(resultScope.completed_scope)}</p>
              <p className="whitespace-pre-wrap">未覆盖：{text(resultScope.excluded_scope)}</p>
              <p className="whitespace-pre-wrap">判据回应：{text(resultScope.criteria_response)}</p>
              <p className="whitespace-pre-wrap">后续要求：{text(resultScope.follow_up)}</p>
              <details><summary className="cursor-pointer">实际证据对应（{rows(row.evidence).length}）</summary><div className="mt-2 space-y-2">{rows(row.evidence).map(ref => <div key={`${text(ref.kind)}:${text(ref.id)}`}><p>{evidenceKinds[text(ref.kind)]} · {ref.role === "verification" ? "完成依据" : "对照资料"} · {ref.changed ? "原记录已变化 / 不可用" : "摘要一致"}</p><p className="whitespace-pre-wrap">{text(ref.correspondence)}</p>{Array.isArray(obj(ref.assessment).gaps) && <p className="text-primary">{(obj(ref.assessment).gaps as unknown[]).map(String).join("；")}</p>}</div>)}</div></details>
            </>}
            {row.confirmation != null && <p className="whitespace-pre-wrap">原{confirmation.outcome === "verified" ? "确认" : "退回"}：{person(confirmation.created_by_user_id)} · {text(confirmation.created_at)} · {text(confirmation.note)}</p>}
            {Array.isArray(row.gaps) && row.gaps.length > 0 && <p className="text-primary">{row.gaps.map(String).join("；")}</p>}
            {row.binding_id != null && <a className="inline-block text-primary underline" href={`#change-execution-${ecrId}-${text(row.binding_id)}`}>前往本条任务、原证据与结果办理</a>}
          </article>;
        })}
      </>}
      <Button type="button" size="sm" variant="outline" disabled={pending} onClick={() => { setEnabled(true); setRevision(v => v + 1); }}>刷新范围、结果与原证据</Button>
    </div>
  </details>;
}
