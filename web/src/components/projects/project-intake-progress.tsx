"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const text = (value: unknown) => value == null ? "" : String(value);
const strings = (value: unknown): string[] => Array.isArray(value) ? value.map(String) : [];
const states: Record<string, string> = {
  ready: "可确认办理", missing_mapping: "待补映射", waiting_work: "待办理前置工作",
  recheck: "待重新核对", in_execution: "实际任务执行中", waiting_task: "实际任务等待前置",
  blocked: "实际任务受阻", pending_approval: "实际任务待审批", done: "实际任务已完成",
  skipped: "实际任务已跳过", task_unavailable: "实际任务暂不可读",
};

export function ProjectIntakeProgress({ projectId, proposalId, value, onWork, onVersion }: {
  projectId: string; proposalId: string; value: Row; onWork: (key: string) => void; onVersion: (id: string) => void;
}) {
  const [filter, setFilter] = useState("all"), [error, setError] = useState<string | null>(null), [busy, setBusy] = useState(false);
  const [earlier, setEarlier] = useState<Row>(isRecord(value.earlier_work) ? value.earlier_work : {});
  const entries = rows(value.entries), gaps = rows(value.gap_observations), counts = isRecord(value.counts) ? value.counts : {};
  const visible = entries.filter(item => filter === "all" || (filter === "recheck_all" ? strings(item.recheck_reasons).length > 0 : item.state === filter));
  async function more() {
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/intake/proposals/${proposalId}/earlier-work?before_id=${encodeURIComponent(text(earlier.next_id))}`, { cache: "no-store" });
      const body: unknown = await responseBody(response);
      if (!response.ok || !isRecord(body)) throw new Error("更早办理记录暂不可读，请重试。");
      setEarlier(old => ({ ...body, items: [...rows(old.items), ...rows(body.items)] }));
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); }
  }
  function taskLink(task: unknown) {
    if (!isRecord(task)) return <span>实际任务暂不可读</span>;
    return <a href={text(task.href)} className="text-primary underline">{text(task.title)} · {text(task.status)}</a>;
  }
  return <section aria-label="初始化办理进展" className="space-y-3 rounded-md border bg-muted/20 p-3">
    <h5 className="font-medium">本版安排与实际进展</h5>
    <p>本版 {text(value.total)} 项，已创建或关联 {text(value.applied)} 项，需重新核对 {text(value.needs_recheck)} 项。读取时间：{text(value.read_at)}</p>
    <p className="text-xs text-muted-foreground">任务状态来自实际办理记录；跳过与完成分列。这里的任务进展不代表原问题已关闭、原文缺项已解决或项目关卡已通过。刷新版本可读取最新进展。</p>
    <label className="block">查看工作<select className="ml-2 rounded-md border bg-background p-2" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">全部（{entries.length}）</option><option value="recheck_all">需重新核对（{text(value.needs_recheck)}）</option>{Object.entries(states).filter(([key]) => Number(counts[key]) > 0).map(([key, label]) => <option key={key} value={key}>{label}（{text(counts[key])}）</option>)}</select></label>
    {!visible.length && <p className="text-muted-foreground">当前筛选没有工作条目。</p>}
    {visible.map(item => <article key={text(item.key)} className="space-y-1 border-t pt-2">
      <p className="font-medium">{text(item.title)} · {states[text(item.state)] ?? text(item.state)}</p>
      {item.task != null && <p>{taskLink(item.task)}{isRecord(item.task) && <> · 当前到期 {text(item.task.due_date) || "未提供"} · 完成依据 {text(item.task.completion_evidence_ref) || "未登记"}</>}</p>}
      {strings(item.recheck_reasons).map(reason => <p key={reason} className="text-destructive">{reason}</p>)}
      {strings(item.missing).length > 0 && <p>保存时缺项：{strings(item.missing).join("、")}</p>}
      {strings(item.waiting_work_keys).length > 0 && <p>尚未按本版办理的前置：{strings(item.waiting_work_keys).map(key => text(entries.find(entry => entry.key === key)?.title) || key).join("、")}</p>}
      {rows(item.unresolved_predecessors).map(task => <p key={text(task.id)}>尚未完成或跳过的实际前置：{taskLink(task)}</p>)}
      <Button type="button" size="sm" variant="outline" onClick={() => onWork(text(item.key))}>定位本版条目及办理入口</Button>
    </article>)}
    <details><summary className="cursor-pointer">原文缺项与安排覆盖（{gaps.length}）</summary>
      {!gaps.length && <p>本版尚未标记缺项原文；不据此推定资料完整。</p>}
      {gaps.map(gap => <div key={text(gap.key)} className="my-2 space-y-1 border-t pt-2"><p className="max-h-36 overflow-auto whitespace-pre-wrap">{text(gap.quote)}</p><a className="text-primary underline" href={text(gap.document_href)}>原件 · {text(gap.locator)}</a>{gap.source_current !== true && <p className="text-destructive">原文来源已变化，请重新核对。</p>}<p>{strings(gap.work_keys).length ? `已被 ${strings(gap.work_keys).length} 项工作引用，其中 ${strings(gap.applied_work_keys).length} 项已按本版办理。` : "尚无本版工作引用此缺项，可载入版本后补安排。"}</p>{strings(gap.work_keys).map(key => <Button key={key} type="button" size="sm" variant="ghost" onClick={() => onWork(key)}>{text(entries.find(item => item.key === key)?.title) || "查看安排"}</Button>)}</div>)}
    </details>
    <details><summary className="cursor-pointer">本版未纳入的其他已办工作（{text(earlier.total)}）</summary><p className="text-muted-foreground">这些任务仍然存在，移出本版不会撤销任务；从原任务继续办理，或读取原现状版本核对来源。</p>{rows(earlier.items).map(item => <div key={text(item.id)} className="my-2 space-y-1 border-t pt-2"><p>{text(item.title)} · 首次办理来源版本 {text(item.origin_revision)}</p><p>{taskLink(item.task)}</p><Button type="button" size="sm" variant="outline" onClick={() => onVersion(text(item.proposal_id))}>读取原现状版本</Button></div>)}{earlier.next_id != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void more()}>继续读取其他已办工作</Button>}</details>
    {error && <p role="alert" className="text-destructive">{error}</p>}
  </section>;
}
