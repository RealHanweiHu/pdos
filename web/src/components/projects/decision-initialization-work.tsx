"use client";

import { ProjectIntakeWorkResults } from "@/components/projects/project-intake-work-results";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
type Row = Record<string, unknown>;
const text = (v: unknown) => v == null ? "未提供" : String(v);
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
export function DecisionInitializationWork({ projectId, decisionId }: { projectId: string; decisionId: string }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  async function load(more = false) {
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/intake/decision-work/${decisionId}${more && data?.next_id ? `?before_id=${data.next_id}` : ""}`, { cache: "no-store" });
      const value: unknown = await responseBody(response).catch(() => null);
      if (!response.ok || !isRecord(value)) throw new Error("实际工作暂不可读取，请稍后刷新");
      setData(old => more ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); }
  }
  return <details className="rounded-md border p-3 text-xs" onToggle={e => { if (e.currentTarget.open && !data && !busy) void load(); }}>
    <summary className="cursor-pointer font-medium">补齐、复核与补偿工作</summary>
    <div className="mt-2 space-y-2">
      <p>按当前记录和来源修订安排实际任务，负责人、日期、交付要求与办理依据需另行确认。历史内容不代表当前批准，任务完成也不自动改写原决策。</p>
      <a className="text-primary underline" href={`/projects?project=${projectId}&tab=overview&intake_decision=${decisionId}#project-intake`}>带入当前现状版本，准备后续工作</a>
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新实际工作</Button>
      {rows(data?.items).map(item => <div key={text(item.id)} className="space-y-1 border-t pt-2">
        {isRecord(item.task) && <p><a className="text-primary underline" href={text(item.task.href)}>{text(item.task.title)}</a> · {text(item.task.status)} · 到期 {text(item.task.due_date)}</p>}
        <p className="whitespace-pre-wrap">{text(item.basis_note)}</p>
        {item.source_current !== true && <p className="text-destructive">决策或历史来源关联已变化，原任务保留；请核对是否需要修正安排或继续补偿。</p>}
        <a className="text-primary underline" href={`/projects?project=${projectId}&tab=overview&intake_proposal=${item.proposal_id}#project-intake`}>原初始化版本 {text(item.revision)}</a>
        <ProjectIntakeWorkResults projectId={projectId} bindingId={text(item.id)}/>
      </div>)}
      {data && !rows(data.items).length && <p>尚未通过初始化流程安排工作；无后续事项时不要求创建任务。</p>}
      {data?.next_id != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>继续读取其他工作</Button>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
