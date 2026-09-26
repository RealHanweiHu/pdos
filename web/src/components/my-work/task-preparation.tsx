"use client";
import { TaskTemplateFields } from "@/components/projects/task-template-fields";

import { TaskTakeover } from "./task-takeover";
import { RiskFollowupResults } from "@/components/projects/risk-followup-results";
import { ProjectIntakeWorkResults } from "@/components/projects/project-intake-work-results";

import Link from "next/link";
import { TaskDirectActions } from "./task-direct-actions";
import { IntakeCompensationSummary } from "@/components/projects/issue-intake-compensations";
import { ChangeExecutionTaskSummary } from "@/components/projects/change-execution-tasks";
import { FirmwareTaskSummary } from "@/components/projects/firmware-package-tasks";
import { TestPreparationSummary } from "@/components/projects/test-execution-preparation";
import { ContextKnowledge } from "@/components/knowledge/context-knowledge";
import { useEffect, useState } from "react";

import { caseLinkRequest } from "@/components/cases/case-requirements";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import { MyWorkIdDesignAction } from "./my-work-id-design";
import type { MyWorkIdDesign } from "./my-work-types";

function record(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) throw new Error("接手资料格式不完整，请刷新");
  return value;
}
function text(value: unknown): string {
  if (typeof value !== "string") throw new Error("接手资料字段不完整，请刷新");
  return value;
}
function maybeText(value: unknown): string | null {
  return value === null ? null : text(value);
}
function positiveInteger(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 1) throw new Error("计划版本不完整");
  return value;
}
function flag(value: unknown): boolean {
  if (typeof value !== "boolean") throw new Error("接收状态格式不完整");
  return value;
}
function list<T>(value: unknown, parse: (item: unknown) => T): T[] {
  if (!Array.isArray(value)) throw new Error("接手资料列表不完整");
  return value.map(parse);
}
function link(value: unknown): string {
  const href = text(value);
  if (!/^\/projects\?project=[0-9a-f-]{36}&tab=[a-z-]+(?:&entity_id=[0-9a-f-]{36})?$/.test(href)) {
    throw new Error("接手资料入口无效");
  }
  return href;
}
function parsePreparation(value: unknown) {
  const body = record(value), task = record(body.task);
  if (body.preparation_kind !== "business_records") throw new Error("接手资料来源不明确");
  const plan = body.plan === null ? null : record(body.plan);
  const source = body.source === null ? null : record(body.source);
  return {
    canEdit: body.can_edit === true,
    riskFollowupId: typeof body.risk_followup_risk_id === "string" ? body.risk_followup_risk_id : null,
    intakeInitialization: Array.isArray(body.intake_initialization) ? body.intake_initialization.filter(isRecord) : [],
    intakeInitializationMore: body.intake_initialization_more === true,
    intakeCompensations: Array.isArray(body.intake_compensations) ? body.intake_compensations.filter(isRecord) : [],
    changeExecution: Array.isArray(body.change_execution) ? body.change_execution.filter(isRecord) : [],
    engineeringReviews: Array.isArray(body.engineering_reviews) ? body.engineering_reviews.filter(isRecord) : [],
    firmware: isRecord(body.firmware_workpackage) ? body.firmware_workpackage : null,
    verification: isRecord(body.verification_workpackage) ? body.verification_workpackage : null,
    preparedAt: text(body.prepared_at), task: {
      status: text(task.status), updatedAt: text(task.updated_at), blockedReason: maybeText(task.blocked_reason),
      id: text(task.id), title: text(task.title), description: maybeText(task.description),
      assigneeId: maybeText(task.assignee_user_id), href: link(task.href),
      completionEvidence: maybeText(task.completion_evidence_ref),
    },
    hasDesignConditions: list(body.conditions, record).length > 0,
    expectedOutput: maybeText(body.expected_output), criteria: maybeText(body.completion_criteria),
    plan: plan ? { baselineId: text(plan.baseline_id), version: positiveInteger(plan.baseline_version),
      nodeKey: text(plan.node_key), receiverId: maybeText(plan.receiver_user_id) } : null,
    source: source ? { title: text(source.title), status: maybeText(source.status), href: link(source.href) } : null,
    people: list(body.people, (value) => { const p = record(value); return { id: text(p.id), name: text(p.display_name), active: flag(p.is_active) }; }),
    gaps: list(body.gaps, text), startBlockers: list(body.start_blockers, text), finishBlockers: list(body.finish_blockers, text),
    dependencies: list(body.dependencies, (value) => { const p = record(value); return { id: text(p.id), title: text(p.title), satisfied: flag(p.satisfied), href: link(p.href) }; }),
    decisions: list(body.decisions, (value) => { const d = record(value); return { id: text(d.id), title: text(d.title), rationale: maybeText(d.rationale), href: link(d.href) }; }),
    deliveries: list(body.deliveries, (value) => {
      const d = record(value), artifact = record(d.artifact);
      return { id: text(d.id), title: text(d.title), criteria: text(d.criteria),
        receiverId: text(d.receiver_user_id), handoffId: text(d.handoff_id),
        accepted: flag(d.accepted), reason: maybeText(d.reason), filename: text(artifact.filename),
        documentHref: link(d.document_href), handoffHref: link(d.handoff_href),
        residuals: list(d.residuals, (value) => { const r = record(value); return {
          description: text(r.description), ownerId: text(r.owner_user_id), dueAt: text(r.due_at),
        }; }),
      };
    }),
  };
}

type Preparation = ReturnType<typeof parsePreparation>;

export function TaskPreparation({ projectId, taskId, handoffActions = [], onChanged, inlineActions = false, onAction }: {
  projectId: string; taskId: string; handoffActions?: MyWorkIdDesign[]; onChanged?: () => void; inlineActions?: boolean; onAction?: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<Preparation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const [handoff, setHandoff] = useState<MyWorkIdDesign | null>(null);
  useEffect(() => {
    if (!open) return;
    let active = true;
    caseLinkRequest<unknown>(`projects/${projectId}/tasks/${taskId}/preparation`)
      .then(parsePreparation).then((value) => { if (active) setData(value); })
      .catch((error: unknown) => { if (active) setError(error instanceof Error ? error.message : "接手资料暂不可用"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [projectId, taskId, open, revision]);
  const refresh = () => { setLoading(true); setError(null); setRevision((value) => value + 1); };
  const person = (id: string | null) => {
    const found = data?.people.find((p) => p.id === id);
    return found ? `${found.name}${found.active ? "" : "（已停用）"}` : id ? "责任成员待核对" : "未指定";
  };
  return <div className="px-4 pb-3">
    <Button type="button" variant="outline" size="sm" aria-expanded={open}
      onClick={() => { if (!open) refresh(); setOpen(!open); }}>
      {open ? "收起接手资料" : inlineActions ? "查看依据并办理" : "接手准备"}
    </Button>
    {open && <section aria-label="任务接手资料" className="mt-2 space-y-3 rounded-lg border bg-muted/20 p-3 text-sm">
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {!data && !error && <p className="text-muted-foreground">正在整理当前任务、计划和接收依据…</p>}
      {(data || error) && <Button type="button" size="sm" variant="ghost" onClick={refresh}>刷新当前依据</Button>}
      {loading && data && <p className="text-muted-foreground">正在刷新当前任务及前置，填写内容保留…</p>}
      <TaskTemplateFields projectId={projectId} taskId={taskId} onChanged={refresh}/>
      {data && <>
        <p className="text-xs text-muted-foreground">按业务记录整理 · {new Date(data.preparedAt).toLocaleString("zh-CN")} · 业务状态以实际办理时复核为准</p>
        <dl className="grid gap-2 sm:grid-cols-2">
          <div><dt className="text-xs text-muted-foreground">负责人 / 接收人</dt><dd>{person(data.task.assigneeId)} / {person(data.plan?.receiverId ?? null)}</dd></div>
          <div><dt className="text-xs text-muted-foreground">计划依据</dt><dd>{data.plan ? `基线 v${data.plan.version} · ${data.plan.nodeKey}` : "当前未绑定正式计划"}</dd></div>
          <div><dt className="text-xs text-muted-foreground">预期输出</dt><dd className="whitespace-pre-wrap">{data.expectedOutput ?? "待确认"}</dd></div>
          <div><dt className="text-xs text-muted-foreground">验收标准</dt><dd className="whitespace-pre-wrap">{data.criteria ?? "待确认"}</dd></div>
        </dl>
        {data.task.description && <p className="whitespace-pre-wrap">{data.task.description}</p>}
        {data.gaps.length > 0 && <div><h4 className="font-medium">接手前核对</h4><ul className="list-inside list-disc text-muted-foreground">{data.gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul></div>}
        {data.engineeringReviews.map(review => <div key={String(review.package_id)} className="space-y-1 rounded-md border p-2 text-xs"><p className="font-medium">{String(review.title)} · 评审 v{String(review.revision_number)}</p><p className="whitespace-pre-wrap">范围：{String(review.scope)}</p><p className="whitespace-pre-wrap">未知影响：{String(review.unknown_impacts)}</p>{Array.isArray(review.lines) && review.lines.filter(isRecord).map(line => <p key={String(line.key)}>核对 {String(line.parameter)}：{String(line.verification_criteria)}</p>)}{review.latest_id !== review.package_id && <p className="text-primary">此评审已有新修订，请核对本任务是否继续适用。</p>}<Link className="text-primary underline" href={`/projects?project=${projectId}&tab=engineering&engineering_review_id=${String(review.package_id)}`}>查看原评审、逐项出处与历次任务</Link></div>)}
        <ChangeExecutionTaskSummary values={data.changeExecution} projectId={projectId} />
        {data.firmware && <FirmwareTaskSummary value={data.firmware} projectId={projectId} />}
        {data.riskFollowupId && <RiskFollowupResults projectId={projectId} riskId={data.riskFollowupId} taskId={taskId} onRecorded={onChanged}/>}
        {data.intakeCompensations.map(binding => <IntakeCompensationSummary key={String(binding.id)} value={binding}/>)}
        {data.verification && <div className="space-y-2"><TestPreparationSummary preparation={data.verification} /><Link className="text-primary underline" href={`/projects?project=${projectId}&tab=quality&test_case_id=${encodeURIComponent(String(data.verification.test_case_id))}`}>打开该测试项办理执行与证据</Link></div>}
        {data.source && <p>工作来源：<Link className="text-primary underline" href={data.source.href}>{data.source.title}</Link></p>}
        {data.decisions.length > 0 && <div><h4 className="font-medium">关联决定</h4>{data.decisions.map((decision) => <div key={decision.id} className="mt-1"><Link className="text-primary underline" href={decision.href}>{decision.title}</Link><p className="text-xs text-muted-foreground">{decision.rationale}</p></div>)}</div>}
        {data.intakeInitialization.length > 0 && <section className="space-y-2 rounded-md border p-3"><h4 className="font-medium">在途项目初始化依据</h4>{data.intakeInitialization.map(item => <div key={String(item.work_key)}><p>现状版本 {String(item.revision)} · {String(item.purpose)}</p><p className="whitespace-pre-wrap">{String(item.basis_note)}</p>{isRecord(item.source) && <p>原业务依据：<Link className="text-primary underline" href={String(item.source.href)}>{String(item.source.title)}</Link>{item.source_current === false && <span className="text-destructive"> · 记录或历史来源关联有变化，请重新核对</span>}</p>}<Link className="text-primary underline" href={`/projects?project=${projectId}&tab=overview&intake_proposal=${encodeURIComponent(String(item.proposal_id))}#project-intake`}>回查原文、阶段映射及初始化办理</Link>{typeof item.binding_id === "string" && <ProjectIntakeWorkResults projectId={projectId} bindingId={item.binding_id}/>}</div>)}{data.intakeInitializationMore && <p>当前显示最近20条依据；更早依据可进入项目现状版本回查。</p>}<p className="text-xs text-muted-foreground">来源记录不代表任务已完成；实际执行与完成证据继续在本任务办理。</p></section>}
        {data.dependencies.length > 0 && <div><h4 className="font-medium">前置任务</h4><ul>{data.dependencies.map((dependency) => <li key={dependency.id}><Link className="text-primary underline" href={dependency.href}>{dependency.title}</Link> · {dependency.satisfied ? "已结束" : "尚未结束"}</li>)}</ul></div>}
        {(data.startBlockers.length > 0 || data.finishBlockers.length > 0) && <div className="rounded-lg border p-2">
          {data.startBlockers.length > 0 && <><h4 className="font-medium">开始条件未满足</h4><ul>{data.startBlockers.map((reason) => <li key={reason}>{reason}</li>)}</ul></>}
          {data.finishBlockers.length > 0 && <><h4 className="mt-1 font-medium">完成条件未满足</h4><ul>{data.finishBlockers.map((reason) => <li key={reason}>{reason}</li>)}</ul></>}
        </div>}
        {data.deliveries.length > 0 && <div><h4 className="font-medium">输入交付与遗留事项</h4>{data.deliveries.map((item) => {
          const action = handoffActions.find((action) => action.id === item.handoffId && action.project.id === projectId && action.kind === "handoff");
          return <div key={item.id} className="mt-2 rounded-lg border bg-background p-2">
            <p className="font-medium">{item.title} · {item.accepted ? "本轮交接已接收" : "本轮交接待办"}</p>
            <p>验收：{item.criteria}</p><p>接收人：{person(item.receiverId)}</p>
            <Link className="text-primary underline" href={item.documentHref}>{item.filename}</Link>
            {item.reason && <p className="mt-1 text-xs text-muted-foreground">{item.reason}</p>}
            {item.residuals.map((residual, index) => <p key={index} className="mt-1 text-xs">遗留：{residual.description} · {person(residual.ownerId)} · {new Date(residual.dueAt).toLocaleDateString("zh-CN")}</p>)}
            <div className="mt-2">{action ? <Button type="button" size="sm" variant="outline" onClick={() => setHandoff(action)}>逐项接收或退回</Button> : <Link className="text-primary underline" href={item.handoffHref}>查看项目交接</Link>}</div>
          </div>;
        })}</div>}
        {data.hasDesignConditions && <Link className="block text-primary underline" href={`/projects?project=${projectId}&tab=overview`}>查看项目交接与冻结安排</Link>}
        {data.task.completionEvidence && <p className="break-words text-xs">已记录完成证据：{data.task.completionEvidence}</p>}
        {inlineActions && <TaskDirectActions projectId={projectId} task={data.task} preparedAt={data.preparedAt} canEdit={data.canEdit} loading={loading || !!error} startBlockers={data.startBlockers} finishBlockers={data.finishBlockers} receiver={person(data.plan?.receiverId ?? null)} onRefresh={refresh} onChanged={message => { onAction?.(message); onChanged?.(); }}/>}
        <Link className="inline-flex min-h-11 items-center font-medium text-primary underline" href={data.task.href}>{inlineActions ? "查看原任务完整记录" : "到任务办理"}</Link>
      </>}
      {data && <TaskTakeover projectId={projectId} taskId={taskId} onChanged={() => { refresh(); onChanged?.(); }}/>}
      {data && <ContextKnowledge key={`${projectId}:${taskId}`} projectId={projectId} contextKind="task_takeover" entityId={taskId} />}
      {handoff && <div className="rounded-lg border bg-background p-3"><Button type="button" variant="ghost" size="sm" onClick={() => setHandoff(null)}>关闭交接办理</Button><MyWorkIdDesignAction key={`${handoff.id}:${revision}`} item={handoff} onChanged={() => { refresh(); onChanged?.(); }} /></div>}
    </section>}
  </div>;
}
