"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { AgentRunProgressPanel } from "@/components/ai/agent-run-progress";
import { parseAgentRunProgress } from "@/components/ai/ai-api";
import { RouteRehearsalResults } from "./process-template-route-rehearsal";
import { FieldRehearsalResults } from "./process-template-field-rehearsal";
import { NamedSignerDifference, NamedSignerResults } from "./process-template-named-signers";
import { RiskFieldDifference } from "./process-template-risk-fields";
import { RiskFieldRehearsalResults } from "./process-template-risk-field-rehearsal";
import { TaskFieldDifference } from "./process-template-task-fields";
import { TaskFieldRehearsalResults } from "./process-template-task-field-rehearsal";
import { IssueFieldDifference } from "./process-template-fields";
import { ApprovalRouteDifference, ApprovalRehearsalResults } from "./process-template-approval-routes";
import { ReminderRehearsalResults } from "./process-template-reminder-rehearsal";
import { reminderLabels, reminderValue, type ReminderPolicy } from "./process-template-reminders";
import { professionalRoles } from "./process-template-routing";
import { gateSlots, gateRequirements, type GateRequirements, type GateSlot, type GateRequirement } from "./process-template-gates";
import { ProcessTemplateAssessmentEditor, normalizedAssessment, type Assessment, type TemplateBase } from "./process-template-assessment-editor";

type Row = Record<string, unknown>;
const text = (value: unknown) => value == null ? "" : String(value);
const object = (value: unknown): Row => isRecord(value) ? value : {};
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const strings = (value: unknown): string[] => Array.isArray(value) ? value.map(text) : [];
const path = "/api/admin/organization/process-templates";
const statuses: Record<string, string> = { running: "正在准备建议", succeeded: "建议已准备", degraded: "本次生成已停止", failed: "本次未生成建议", pending_review: "待审阅", accepted: "已接受，待单独应用", rejected: "已拒绝", applied: "已应用为配置候选", archived: "已归档" };
const labels: Record<string, string> = { title: "名称", title_en: "英文名称", stage: "阶段", responsibility: "专业职责", discipline: "专业说明", depends_on: "前置任务", output: "交付内容", receiver: "接收要求", required_features: "适用功能", hard_milestone: "必须冻结或接收", minimum_evidence: "最低证据" };
const display = (value: unknown): string => value == null ? "无" : typeof value === "boolean" ? value ? "是" : "否" : Array.isArray(value) ? value.join("、") || "无" : text(value);
function formError(value: unknown): string {
  const fields: Record<string,string> = { ...labels, summary: "建议摘要", name: "模板名称", name_en: "英文名称", task_upserts: "任务修改", task_removals: "任务移除", feature_upserts: "功能配置", stage_upserts: "阶段配置", gate_requirements: "签核配置", task_routes: "办理路由", routing_cases: "路由场景", reminder_policy: "提醒规则", reminder_cases: "提醒场景", approval_routes: "签核先后依赖", approval_cases: "签核先后场景", named_gate_slots: "必须具名的签核槽位", signer_cases: "具名签核分派场景", scenario: "人员条件", expected_valid: "预期允许", risk_fields: "风险补充字段", risk_field_cases: "风险字段填写场景", task_fields: "任务补充字段", task_field_cases: "任务字段填写场景", issue_fields: "问题补充字段", field_cases: "字段填写场景", gate_checks: "签核场景", stage_codes: "关联阶段", extension_requests: "待决扩展", open_questions: "待澄清问题", requirements: "要求说明", quote: "原文引用", explanation: "处理说明", cases: "模拟场景", comment: "审阅意见" };
  return rows(value).slice(0,4).map(item => {
    const location=strings(item.loc), key=[...location].reverse().find(part => fields[part]);
    const label=fields[key ?? ""] || "建议内容", kind=text(item.type);
    return `${label}${kind === "missing" || kind.includes("too_short") ? "缺少必要内容，请补充" : kind.includes("too_long") ? "超出长度或数量限制，请精简" : "格式不正确，请核对"}`;
  }).join("；");
}
async function api(url: string, body?: unknown, signal?: AbortSignal): Promise<Row> {
  const response = await fetch(url, { cache: "no-store", signal, ...(body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });
  const value: unknown = await responseBody(response);
  if (!response.ok || !isRecord(value)) throw new Error(text(object(object(value).detail).message) || formError(object(value).detail) || "本次办理暂未返回结果，请刷新运行记录后再试");
  return value;
}
async function readOrganizationProgress(id: string) { return parseAgentRunProgress(await api(`${path}/runs/${encodeURIComponent(id)}/progress`)); }

export function ProcessTemplateSuggestions({ detail, onRefresh, onOpenRevision, onBusyChange }: {
  detail: Row; onRefresh: () => Promise<void>; onOpenRevision: (id: string) => Promise<void>;
  onBusyChange: (busy: boolean) => void;
}) {
  const brief = object(detail.brief);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [result, setResult] = useState<Row | null>(null), [comment, setComment] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [editing, setEditing] = useState(false), [draft, setDraft] = useState<Assessment | null>(null), [reviewPreview, setReviewPreview] = useState<Row | null>(null);
  const [generating, setGenerating] = useState(false);
  const generation = useRef<AbortController | null>(null);
  const attempt = useRef({ signature: "", id: "" });
  const finding = object(result?.finding), accepted = object(finding.accepted_payload);
  const proposal = editing && reviewPreview ? object(reviewPreview.proposal) : finding.accepted_payload ? accepted : object(finding.proposed_payload);
  const assessment = object(proposal.assessment), difference = object(proposal.difference), rehearsal = object(proposal.rehearsal);
  const loadFinding = async (id: string) => { const value=await api(`${path}/findings/${id}`); setResult(value); setDraft(structuredClone(object(object(value.finding).proposed_payload).assessment) as Assessment); setEditing(false); setReviewPreview(null); setConfirmed(false); setComment(""); };
  async function act(work: () => Promise<void>) { setBusy(true); onBusyChange(true); setError(""); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "办理失败"); } finally { setBusy(false); onBusyChange(false); } }
  async function generate(requestId?: string, signal?: AbortSignal) {
    const signature = JSON.stringify([brief.id, brief.source_digest]);
    if (!requestId && attempt.current.signature !== signature) attempt.current = { signature, id: crypto.randomUUID() };
    const value = await api(`${path}/briefs/${text(brief.id)}/generate`, { request_id: requestId || attempt.current.id, expected_source_digest: brief.source_digest }, signal);
    if (signal?.aborted) return;
    if (["succeeded", "degraded", "failed"].includes(text(value.status))) attempt.current = { signature: "", id: "" };
    await onRefresh();
    if (!signal?.aborted && value.finding_id) await loadFinding(text(value.finding_id));
  }
  async function startGeneration(requestId?: string) {
    if (generation.current) return;
    const controller=new AbortController(); generation.current=controller;
    setGenerating(true); setError("");
    try { await generate(requestId,controller.signal); }
    catch (failure) { if(!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "本次生成尚未返回，请刷新记录后读取原请求。"); }
    finally { if(generation.current === controller) generation.current=null; if(!controller.signal.aborted) setGenerating(false); }
  }
  useEffect(() => () => generation.current?.abort(), []);
  const shouldPoll = generating || rows(detail.runs).some(run => run.status === "running");
  useEffect(() => {
    if (!shouldPoll) return;
    let inFlight=false;
    const timer=setInterval(() => {
      if (inFlight || document.visibilityState === "hidden") return;
      inFlight=true; void onRefresh().catch(() => {}).finally(() => { inFlight=false; });
    },3000);
    return () => clearInterval(timer);
  },[shouldPoll,onRefresh]);
  async function review(decision: "accepted" | "rejected") {
    if (decision === "accepted" && editing && (!draft || !reviewPreview)) throw new Error("请先预览本次编辑后的配置差异。");
    await api(`${path}/findings/${text(finding.id)}/review`, { decision, comment, ...(decision === "accepted" && editing && draft ? { assessment: normalizedAssessment(draft), expected_preview_digest: reviewPreview?.preview_digest } : {}) });
    await loadFinding(text(finding.id)); await onRefresh();
  }
  return <section className="space-y-3 rounded-md border p-3">
    <h4 className="font-medium">智能配置建议与独立人审</h4>
    <p className="text-sm text-muted-foreground">{text(detail.generation_message)} 接受建议后只保存审阅决定；应用后形成候选，还需单独演练和发布。</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="text-sm">{notice}</p>}
    <fieldset disabled={busy} className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" disabled={generating || !detail.generation_available || !detail.source_current || rows(detail.runs).some(item => item.status === "running")} onClick={() => void startGeneration()}>{generating ? "正在生成，可查看进度或停止" : "准备智能配置建议"}</Button>
        <Button type="button" size="sm" variant="outline" onClick={() => void act(onRefresh)}>刷新生成记录</Button>
      </div>
      <p className="text-xs text-muted-foreground">原要求再次生成或补充要求会沿用原请求预算。中途离开页面后，可在此查看已保存结果。</p>
      {rows(detail.runs).map(run => <div key={text(run.id)} className="rounded-md bg-muted/40 p-2 text-sm">
        <p>{statuses[text(run.status)] || "状态待确认"} · {new Date(text(run.created_at)).toLocaleString("zh-CN")}</p>
        {!!run.error_code && <p>{run.error_code === "APPLICATION_REQUEST_CANCELLED" ? "已停止本要求链的生成。已发送调用的用量仍按实际回执记录。" : run.error_code === "PROCESS_TEMPLATE_BASE_CHANGED" ? "模板依据已变化，请基于当前版补充原要求。" : "本次未形成可应用建议，原始要求和运行记录已保留。"}</p>}
        {run.can_control === true && <AgentRunProgressPanel runId={text(run.id)} requestProgress={readOrganizationProgress}/>}
        {run.can_control === true && (run.status === "running" || run.error_code === "APPLICATION_RUN_LEASE_EXPIRED") && <Button type="button" size="sm" variant="outline" onClick={() => void act(async () => { const value=await api(`${path}/runs/${text(run.id)}/cancel`,{ confirmed: true }); await onRefresh(); setNotice(object(value.cancellation).changed ? "已停止本要求链中仍在进行的生成；已完成的历史结果保留。" : "生成已结束或此前已停止，请以刷新后的运行记录为准。"); })}>停止此要求链的生成</Button>}
        {!!run.finding_id && <Button type="button" size="sm" variant="ghost" onClick={() => void act(() => loadFinding(text(run.finding_id)))}>查看配置建议与审阅决定</Button>}
        {!run.finding_id && run.can_control === true && (run.status === "running" || run.error_code === "APPLICATION_RUN_LEASE_EXPIRED") && <Button type="button" size="sm" variant="ghost" disabled={generating || !detail.generation_available} onClick={() => void startGeneration(text(run.request_id))}>读取原请求或恢复已保存结果</Button>}
      </div>)}
      {detail.runs_truncated === true && <p className="text-xs text-muted-foreground">显示最近20次生成记录。</p>}
      {result && <div className="space-y-3 border-t pt-3">
        <p className="font-medium">{statuses[text(finding.status)] || "配置建议"}</p>
        {finding.status === "pending_review" && draft && <div className="space-y-3">
          {!editing ? <Button type="button" size="sm" variant="outline" disabled={!result.source_current} onClick={() => setEditing(true)}>修改建议后再接受</Button> : <>
            <ProcessTemplateAssessmentEditor value={draft} base={object(result.original_source).base_snapshot as TemplateBase} gateBaseline={result.gate_baseline as GateRequirements} reminderBaseline={result.reminder_policy as ReminderPolicy} contractVersion={text(result.assessment_version)} onChange={value => { setDraft(value); setReviewPreview(null); }}/>
            <div className="flex flex-wrap gap-2"><Button type="button" size="sm" disabled={!result.source_current} onClick={() => void act(async () => setReviewPreview(await api(`${path}/findings/${text(finding.id)}/preview-review`,{ assessment: normalizedAssessment(draft) })))}>预览编辑后的配置差异</Button><Button type="button" size="sm" variant="ghost" onClick={() => { setDraft(structuredClone(object(finding.proposed_payload).assessment) as Assessment); setEditing(false); setReviewPreview(null); }}>放弃本次编辑，回到原建议</Button></div>
            <p className="text-sm text-muted-foreground">{reviewPreview ? "以下为本次编辑的实际差异和模拟结果；接受会保存这份内容。" : "请先预览编辑内容。下面保留原 AI 建议供对照，当前不能接受未预览的编辑。"}</p>
          </>}
        </div>}
        <p className="whitespace-pre-wrap text-sm">{text(assessment.summary)}</p>
        {!result.source_current && <p className="text-sm text-destructive">模板依据已变化，此建议不能再接受或应用；已应用的历史记录保留。</p>}
        {rows(assessment.requirements).map((item,index) => <div className="rounded-md bg-muted/40 p-2 text-sm" key={index}>
          <p className="font-medium">{({ configured: "建议配置", unchanged: "保持原规则", extension: "待决扩展", clarification: "待澄清" } as Record<string,string>)[text(item.disposition)]}</p>
          <blockquote className="my-2 whitespace-pre-wrap border-l-2 pl-2">{text(item.quote)}</blockquote><p>{text(item.explanation)}</p>
          {strings(item.task_codes).length > 0 && <p className="text-xs text-muted-foreground">关联任务：{strings(item.task_codes).join("、")}</p>}
          {strings(item.stage_codes).length > 0 && <p className="text-xs text-muted-foreground">关联阶段：{strings(item.stage_codes).join("、")}</p>}
        </div>)}
        <SuggestionDifference difference={difference}/>
        {strings(proposal.pending_extensions).length > 0 && <div className="text-sm"><p className="font-medium">以下要求待解决，候选不能发布：</p>{strings(proposal.pending_extensions).map((item,index) => <p key={index}>{item}</p>)}</div>}
        <GateSimulationResults rehearsal={rehearsal}/>
        <NamedSignerResults value={proposal.signer_rehearsal}/>
        <RiskFieldRehearsalResults value={proposal.risk_field_rehearsal}/>
        <TaskFieldRehearsalResults value={proposal.task_field_rehearsal}/>
        <FieldRehearsalResults value={proposal.field_rehearsal}/>
        <ApprovalRehearsalResults value={proposal.approval_rehearsal}/>
        <ReminderRehearsalResults value={proposal.reminder_rehearsal}/>
        <RouteRehearsalResults value={proposal.routing_rehearsal}/>
        <details><summary className="cursor-pointer text-sm font-medium">本建议的模拟场景（仍需发布前核对）</summary>{rows(rehearsal.cases).map((item,index) => <div key={index} className="mt-2 text-sm"><p>{text(item.name)} · {item.passed ? "计算符合该预期" : "计算未符合预期"}</p><p>模拟已完成：{strings(rows(assessment.cases)[index]?.completed_codes).join("、") || "无"}</p><p>功能条件：{Object.entries(object(rows(assessment.cases)[index]?.features)).map(([key,enabled]) => `${text(object(object(object(proposal.configuration).features)[key]).label) || key}：${enabled ? "具有" : "不具有"}`).join("；") || "使用模板默认条件"}</p>{rows(assessment.cases)[index]?.expect_valid === false && <p>预期：拒绝此无效输入。</p>}{!!item.error && <p>{text(item.error)}</p>}{rows(item.checks).map(check => <p key={text(check.code)}>{text(check.code)}：预期{check.expected_ready ? "可启动" : "不可启动"}，实际{check.actual_ready ? "可启动" : "不可启动"}</p>)}</div>)}<p className="mt-2 text-xs text-muted-foreground">这些场景用于审阅建议，未替代发布演练和阶段验收。</p></details>
        {(editing || (Boolean(finding.accepted_payload) && JSON.stringify(accepted.assessment) !== JSON.stringify(object(finding.proposed_payload).assessment))) && <details className="rounded-md border p-3"><summary className="cursor-pointer text-sm font-medium">保留的原 AI 建议，供对照</summary><p className="my-2 whitespace-pre-wrap text-sm">{text(object(object(finding.proposed_payload).assessment).summary)}</p><SuggestionDifference difference={object(object(finding.proposed_payload).difference)}/>{rows(object(object(finding.proposed_payload).assessment).requirements).map((item,index) => <p className="mt-2 whitespace-pre-wrap text-sm" key={index}>原文：{text(item.quote)}；原建议：{text(item.explanation)}</p>)}</details>}
        {finding.status === "pending_review" && <div className="space-y-2"><label className="block text-sm">审阅意见<textarea className="mt-1 w-full rounded-md border bg-background p-2" maxLength={5000} value={comment} onChange={event => setComment(event.target.value)}/></label><div className="flex gap-2"><Button type="button" size="sm" disabled={!comment.trim() || !result.source_current || (editing && !reviewPreview)} onClick={() => void act(() => review("accepted"))}>{editing ? "接受预览后的编辑内容" : "接受此建议"}</Button><Button type="button" size="sm" variant="outline" disabled={!comment.trim()} onClick={() => void act(() => review("rejected"))}>拒绝并记录意见</Button></div></div>}
        {!!finding.review_comment && <p className="whitespace-pre-wrap text-sm">已记录审阅意见：{text(finding.review_comment)}</p>}
        {finding.status === "accepted" && <div className="space-y-2"><label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)}/>确认将已接受内容应用为一个待演练的配置候选</label><Button type="button" size="sm" disabled={!confirmed || !result.source_current} onClick={() => void act(async () => { const value = await api(`${path}/findings/${text(finding.id)}/apply`, { confirmed: true }); await loadFinding(text(finding.id)); await onRefresh(); if (value.applied_entity_id) await onOpenRevision(text(value.applied_entity_id)); })}>单独应用为配置候选</Button></div>}
        {finding.status === "applied" && <Button type="button" size="sm" variant="outline" onClick={() => void act(() => onOpenRevision(text(finding.applied_entity_id)))}>打开候选，继续演练和发布</Button>}
      </div>}
    </fieldset>
  </section>;
}

function SuggestionDifference({ difference }: { difference: Row }) {
  return <details open>
<summary className="cursor-pointer text-sm font-medium">实际配置差异</summary>
    <NamedSignerDifference value={difference.named_signer_changes}/>
    <RiskFieldDifference value={difference.risk_field_changes}/>
    <TaskFieldDifference value={difference.task_field_changes}/>
    <IssueFieldDifference value={difference.issue_field_changes}/>
    <ApprovalRouteDifference value={difference.approval_route_changes}/>
    {rows(difference.reminder_changes).map(item => <p key={text(item.key)} className="text-sm">{reminderLabels[text(item.key)]}：{reminderValue(text(item.key), item.before)} → {reminderValue(text(item.key), item.after)}</p>)}
          <p className="my-2 text-sm">模板名称：{text(object(difference.name).before)} → {text(object(difference.name).after)}</p>
          {rows(difference.feature_definitions).map(item => <p className="text-sm" key={text(item.key)}>功能 {text(item.key)}：{text(object(item.before).label) || "新增"} → {text(object(item.after).label)}；默认：{display(object(item.before).default)} → {display(object(item.after).default)}</p>)}
          {rows(difference.route_changes).map(item => <div key={text(item.code)} className="mt-2 rounded-md border p-2 text-sm"><p>{text(item.code)} · 办理路由</p>{([['owner','负责人'],['receiver','接收人']] as const).map(([slot,label]) => <p key={slot}>{label}：{professionalRoles[text(object(item.before)[slot])] ?? "逐项指定"} → {professionalRoles[text(object(item.after)[slot])] ?? "逐项指定"}</p>)}</div>)}
          {rows(difference.stage_changes).map(item => <div key={text(item.code)} className="mt-2 rounded-md border p-2 text-sm"><p className="font-medium">阶段 {text(item.code)}</p>{([['name','中文名称'],['name_en','英文名称'],['description','办理说明']] as const).filter(([key]) => object(item.before)[key] !== object(item.after)[key]).map(([key,label]) => <p key={key} className="whitespace-pre-wrap">{label}：{display(object(item.before)[key])} → {display(object(item.after)[key])}</p>)}</div>)}
          {rows(difference.gate_changes).map(item => <p className="mt-2 text-sm" key={`${text(item.stage)}:${text(item.slot)}`}>{text(item.stage)} · {gateSlots[item.slot as GateSlot]}签核：{gateRequirements[item.before as GateRequirement]} → {gateRequirements[item.after as GateRequirement]}</p>)}
          {rows(difference.task_changes).map(item => <details key={text(item.code)} className="mt-2 rounded-md border p-2 text-sm"><summary className="cursor-pointer">{text(item.code)} · {text(object(item.after).title) || text(object(item.before).title)} · {!item.before ? "新增" : !item.after ? "移除" : "调整"}</summary>{Object.entries(labels).filter(([key]) => JSON.stringify(object(item.before)[key]) !== JSON.stringify(object(item.after)[key])).map(([key,label]) => <div key={key} className="mt-2 whitespace-pre-wrap"><p className="font-medium">{label}</p><p>原：{display(object(item.before)[key])}</p><p>新：{display(object(item.after)[key])}</p></div>)}</details>)}
        </details>;
}

function GateSimulationResults({ rehearsal }: { rehearsal: Row }) {
  const statuses: Record<string,string> = { pending: "待签核", approved: "批准", conditional: "有条件批准", rejected: "拒绝", not_applicable: "不适用" };
  const checks: Row[] = rows(rehearsal.cases).flatMap(item => rows(item.gate_checks).map(check => ({ ...check, name: item.name })));
  const coverage = rows(rehearsal.gate_coverage);
  if (!checks.length && !coverage.length) return null;
  return <details open className="rounded-md border p-3"><summary className="cursor-pointer text-sm font-medium">签核配置的模拟计算</summary>{checks.map((item,index) => <div key={index} className="mt-3 text-sm"><p>{text(item.name)} · {text(item.stage)} · 预期{item.expected_ready ? "满足" : "不满足"}，计算{item.actual_ready ? "满足" : "不满足"}</p>{Object.entries(gateSlots).map(([slot,label]) => <p key={slot} className="text-xs text-muted-foreground">{label}要求：{gateRequirements[object(item.requirements)[slot] as GateRequirement]} · 模拟状态：{statuses[text(object(item.signoffs)[slot])] ?? "待签核"}</p>)}</div>)}{coverage.map(item => <p key={`${text(item.stage)}:${text(item.slot)}`} className="mt-2 text-xs">{text(item.stage)} · {gateSlots[item.slot as GateSlot]}：正例{item.positive ? "已覆盖" : "缺失"}，规则差异反例{item.negative ? "已覆盖" : "缺失"}</p>)}<p className="mt-2 text-xs text-muted-foreground">{text(rehearsal.scope)}</p></details>;
}
