"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { readProjectWork, type ProjectWorkView } from "@/lib/project-work";
import { workAnswerSources, workFollowupStart, type WorkAnswerRun } from "@/lib/work-followup";
import type { SourceRead } from "@/lib/project-plan-view";
import type { WorkspaceTransport } from "@/lib/workspace-api";

type Props = { api: WorkspaceTransport; categoryId: string; principalId: string; run: WorkAnswerRun; disabled?: boolean; additionalSources?: SourceRead[]; onStart: (value: ReturnType<typeof workFollowupStart>) => void; onUnavailable?: () => void };
export function WorkFollowupAction(props: Props) {
  const sources = workAnswerSources(props.run);
  if (!sources.length) return null;
  return <Action key={props.run.run_id} {...props} sources={sources}/>;
}
function Action({ api, categoryId, principalId, run, disabled, additionalSources = [], onStart, onUnavailable, sources }: Props & { sources: ReturnType<typeof workAnswerSources> }) {
  const [open, setOpen] = useState(false), [reading, setReading] = useState<ProjectWorkView | null>(null), [error, setError] = useState("");
  const [citations, setCitations] = useState(sources.map(value => value.citation_id)), [originals, setOriginals] = useState<string[]>([]);
  const [assignee, setAssignee] = useState(""), [recipient, setRecipient] = useState("");
  useEffect(() => {
    if (!open) return;
    let active = true;
    void readProjectWork(api, { categoryId, productId: run.product_id!, projectId: run.project_id!, principalId }).then(value => {
      if (active) { setReading(value); setError(""); }
    }).catch(failure => {
      if (!active) return;
      setReading(null); setError(failure instanceof Error ? failure.message : "项目资料暂不可读。");
      if ([401, 403].includes((failure as { status?: number }).status ?? 0)) { setOpen(false); onUnavailable?.(); }
    });
    return () => { active = false; };
  }, [api, open, categoryId, principalId, run.product_id, run.project_id, onUnavailable]);
  if (!open) return <Button size="sm" variant="outline" disabled={disabled} onClick={() => setOpen(true)}>准备资料跟进任务</Button>;
  const selected = [...additionalSources, ...sources.filter(value => value.source_type === "artifact" && originals.includes(value.citation_id)).map(value => ({ artifact_id: value.source_id, expected_revision: value.source_revision }))];
  const mayAssign = reading?.project.owner_id === principalId;
  const incompletePeople = mayAssign && !!assignee !== !!recipient;
  function start() {
    try { onStart(workFollowupStart(run, citations, selected, crypto.randomUUID(), mayAssign && assignee && recipient ? { assignee_id: assignee, recipient_id: recipient } : undefined)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "任务入口暂不可用。"); }
  }
  return <section aria-label="准备资料跟进任务" className="min-w-0 space-y-3 rounded-lg border p-3 text-sm [overflow-wrap:anywhere]">
    <div className="flex items-center justify-between gap-2"><h4 className="font-medium">准备资料跟进任务</h4><Button size="sm" variant="ghost" disabled={disabled} onClick={() => setOpen(false)}>收起</Button></div>
    {error && <p role="alert">{error}</p>}
    {reading ? <p>关联项目：{reading.project.name} · v{reading.project.revision}</p> : <p role="status">正在核对本项目…</p>}
    <fieldset disabled={disabled} className="space-y-1"><legend className="font-medium">讨论依据</legend>{sources.map(value => <label className="flex gap-2" key={value.citation_id}><input type="checkbox" checked={citations.includes(value.citation_id)} onChange={event => setCitations(old => event.target.checked ? [...old, value.citation_id] : old.filter(id => id !== value.citation_id))}/><span>{value.title} · v{value.source_revision}</span></label>)}</fieldset>
    <fieldset disabled={disabled} className="space-y-1"><legend className="font-medium">任务原件（选中后纳入本次读取）</legend>{sources.filter(value => value.source_type === "artifact").map(value => <label className="flex gap-2" key={value.citation_id}><input type="checkbox" checked={originals.includes(value.citation_id)} onChange={event => setOriginals(old => event.target.checked ? [...old, value.citation_id] : old.filter(id => id !== value.citation_id))}/><span>{value.title} · v{value.source_revision}</span></label>)}<p className="text-muted-foreground">另选原件：{additionalSources.length} 份。可在附件中选择已登记原件；聊天不能代替原件。</p></fieldset>
    {mayAssign && <div className="grid gap-2 sm:grid-cols-2">{([["执行人（可暂不选）", assignee, setAssignee], ["成果接收人（可暂不选）", recipient, setRecipient]] as const).map(([label, value, change]) => <label key={label}>{label}<select className="mt-1 w-full" value={value} disabled={disabled} onChange={event => change(event.target.value)}><option value="">待本人选择</option>{reading.members.filter(member => member.can_write).map(member => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label>)}</div>}
    {incompletePeople && <p role="alert">分派需要同时选择执行人与成果接收人，也可以都暂不选。</p>}
    <p className="text-muted-foreground">先由小Pai起草，核对后再创建。分派另由项目负责人一次确认；日期未确定，不据此作出承诺。</p>
    <Button size="sm" variant="outline" disabled={disabled || !reading || !citations.length || !selected.length || incompletePeople} onClick={start}>开始准备任务</Button>
  </section>;
}
