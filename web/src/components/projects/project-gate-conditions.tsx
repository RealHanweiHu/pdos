"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";

type Original = { title: string; owner_name: string | null; owner_user_id: string; due_date: string; closure_evidence: string };
type Current = { title: string; assignee_name: string | null; status: string; due_date: string | null; expected_output: string | null; completed_at: string | null; completion_evidence_ref: string | null };
type Condition = { task_id: string; original: Original | null; current: Current | null; changed_fields: string[] };
type Decision = { audit_id: number; decided_at: string; decided_by_name: string | null; decision_id: string | null; round_id: string | null; round_number: number | null; conditions: Condition[] };
type History = { items: Decision[]; next_before: number | null };
const statuses: Record<string, string> = { todo: "待开始", in_progress: "进行中", blocked: "受阻", done: "已完成", skipped: "已跳过", pending_approval: "待批准" };

export function ProjectGateConditions({ projectId, gateId }: { projectId: string; gateId: string }) {
  const [history, setHistory] = useState<History | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function load(append = false) {
    setBusy(true); setError("");
    try {
      const query = append && history?.next_before ? `?before=${history.next_before}` : "";
      const response = await fetch(`/api/projects/${projectId}/gates/${gateId}/conditions${query}`, { cache: "no-store" });
      const body = await response.json().catch(() => null);
      if (!response.ok || !Array.isArray(body?.items)) throw new Error(body?.detail?.message ?? "条件落实记录暂不可用，请重新读取");
      const next = body as History;
      setHistory(old => ({ ...next, items: append ? [...old?.items ?? [], ...next.items] : next.items }));
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded-md border p-3" aria-label="Gate条件与落实">
    <div className="flex flex-wrap items-center justify-between gap-2"><h4 className="text-sm font-semibold">附带条件与实际落实</h4><Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void load()}>{history ? "刷新条件落实" : "查看条件与落实"}</Button></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {history && <p className="text-xs text-muted-foreground">原裁决条件固定保留；当前任务按本次读取展示。任务完成不自动批准 Gate，跳过也不代表条件已满足。</p>}
    {history?.items.length === 0 && <p className="text-sm text-muted-foreground">没有已登记的有条件通过回执；不据此补造历史条件。</p>}
    {history?.items.map(decision => <article key={decision.audit_id} className="space-y-3 border-t pt-3 text-sm">
      <p className="font-medium">原第 {decision.round_number ?? "未知"} 轮 · 有条件通过</p>
      <p>{decision.decided_by_name ?? "原人员资料不可用"} · {new Date(decision.decided_at).toLocaleString()}</p>
      {decision.conditions.length === 0 && <p>旧回执未保存条件任务引用，需回查原裁决资料。</p>}
      {decision.conditions.map(condition => <div key={condition.task_id} className="space-y-2 rounded-md bg-muted/30 p-3">
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1"><p className="font-medium">原裁决条件</p>{condition.original ? <><p className="whitespace-pre-wrap break-words">{condition.original.title}</p><p>{condition.original.owner_name ?? "原人员资料不可用"} · {condition.original.due_date}</p><p className="whitespace-pre-wrap break-words">原关闭依据要求：{condition.original.closure_evidence}</p></> : <p className="text-muted-foreground">旧回执未保存原正文，不用当前任务内容替代。</p>}</div>
          <div className="space-y-1"><p className="font-medium">当前任务</p>{condition.current ? <><p className="whitespace-pre-wrap break-words">{condition.current.title}</p><p>{condition.current.assignee_name ?? "未指定"} · {condition.current.due_date ?? "未设期限"} · {statuses[condition.current.status] ?? condition.current.status}</p><p className="whitespace-pre-wrap break-words">当前关闭依据要求：{condition.current.expected_output ?? "未记录"}</p><p className="whitespace-pre-wrap break-words">实际完成依据：{condition.current.completion_evidence_ref ?? "未记录"}</p>{condition.current.completed_at && <p>实际完成：{new Date(condition.current.completed_at).toLocaleString()}</p>}</> : <p className="text-muted-foreground">原任务当前不可读取，不能推定已完成。</p>}</div>
        </div>
        {condition.changed_fields.length > 0 && <p className="text-primary">与原裁决不同：{condition.changed_fields.join("、")}。请核对是否仍满足原条件。</p>}
        {condition.current && <a className="inline-flex min-h-11 items-center text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${condition.task_id}`}>办理原条件任务</a>}
      </div>)}
      <details><summary className="cursor-pointer text-xs">原轮次与裁决编号</summary><p className="break-all text-xs">轮次 {decision.round_id ?? "未记录"}；裁决 {decision.decision_id ?? "未记录"}；回执 {decision.audit_id}</p></details>
    </article>)}
    {history?.next_before != null && <Button variant="outline" size="sm" disabled={busy} onClick={() => void load(true)}>更早条件记录</Button>}
  </section>;
}
