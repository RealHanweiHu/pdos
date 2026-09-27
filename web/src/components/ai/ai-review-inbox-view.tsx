"use client";

import { QualityWorkPackageProposalView } from "./quality-work-package-proposal";
import { ChangeWorkPackageProposalView } from "./change-work-package-proposal";

import { MeetingBusinessProposalView, meetingBusinessTypes } from "./meeting-business-proposal";

import { MeetingDecisionProposalView } from "./meeting-decision-proposal";

import { MeetingActionProposalView } from "./meeting-action-proposal";

import {
  ArrowSquareOutIcon,
  CheckCircleIcon,
  PencilSimpleIcon,
  SparkleIcon,
  TrayIcon,
  XCircleIcon,
} from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import type { Project } from "@/components/projects/project-types";
import { Button } from "@/components/ui/button";
import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { cn } from "@/lib/utils";

import { TestPlanProposalView } from "./test-plan-proposal";
import { MeetingMinutesProposalView } from "./meeting-minutes-proposal";
import { SupplierRecoveryProposalView, SupplierRecoveryAppliedTasks } from "./supplier-recovery-proposal";
import { fieldLabels, proposalReady, PayloadEditor } from "./finding-proposal";
import { FINDING_TYPE_LABELS, type AiFinding, type FindingType } from "./ai-types";

export type FindingFilter = "all" | FindingType;

const typeLabels = FINDING_TYPE_LABELS;

const agentLabels: Record<string, string> = {
  project_intelligence: "Project Intelligence",
  knowledge_lite: "Knowledge Lite",
  engineering_intelligence: "Engineering Intelligence",
  quality_intelligence: "Quality Intelligence",
  supplier_intelligence: "Supplier Intelligence",
  executive_intelligence: "Executive Intelligence",
};

const statusLabels = {
  pending_review: "待人审",
  accepted: "待应用",
  rejected: "已拒绝",
  applied: "已应用",
  archived: "已归档",
} as const;

const rejectionReasons = ["不准确", "重复", "不相关", "证据不足"] as const;

function projectLabel(finding: AiFinding, projects: Map<string, Project>) {
  const project = projects.get(finding.project_id);
  return project ? `${project.code} · ${project.name}` : finding.project_id;
}

const timestampFormatter = new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" });

function formatTimestamp(value: string) {
  return timestampFormatter.format(new Date(value));
}

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  return JSON.stringify(value);
}

function payloadFor(finding: AiFinding) {
  return finding.accepted_payload ?? finding.proposed_payload;
}

function StatusBadge({ finding }: { finding: AiFinding }) {
  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5 text-[10px] font-semibold",
        finding.status === "pending_review" && "border-pending/30 bg-pending/10 text-pending",
        finding.status === "accepted" && "border-success/30 bg-success/10 text-success",
        finding.status === "rejected" && "border-destructive/30 bg-destructive/10 text-destructive",
        finding.status === "applied" && "border-applied/30 bg-applied/10 text-applied",
        finding.status === "archived" && "border-muted-foreground/30 bg-muted text-muted-foreground",
      )}
    >
      {statusLabels[finding.status]}
    </span>
  );
}

export function AiReviewInboxView({
  busy,
  error,
  extraSections,
  filter,
  findings,
  identity,
  loggingOut,
  onAccept,
  onApply,
  onEditAccept,
  onFilterChange,
  onLogout,
  onReject,
  onSelect,
  projects,
  selected,
  status,
}: {
  busy: boolean;
  error: string | null;
  extraSections?: ReactNode;
  filter: FindingFilter;
  findings: AiFinding[];
  identity: WorkspaceIdentity;
  loggingOut: boolean;
  onAccept: (finding: AiFinding) => Promise<boolean>;
  onApply: (finding: AiFinding) => void;
  onEditAccept: (finding: AiFinding, payload: Record<string, unknown>) => Promise<boolean>;
  onFilterChange: (filter: FindingFilter) => void;
  onLogout: () => void;
  onReject: (finding: AiFinding, reason: string) => Promise<boolean>;
  onSelect: (findingId: string) => void;
  projects: Project[];
  selected: AiFinding | null;
  status: string | null;
}) {
  const [editing, setEditing] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [confirmingApply, setConfirmingApply] = useState(false);
  const [editedPayload, setEditedPayload] = useState<Record<string, unknown>>({});
  const [rejectionReason, setRejectionReason] = useState("");
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const projectsById = useMemo(() => new Map(projects.map((project) => [project.id, project])), [projects]);

  function resetInteraction() {
    setEditing(false);
    setRejecting(false);
    setConfirmingApply(false);
    setRejectionReason("");
    setSummaryExpanded(false);
  }

  function selectFinding(findingId: string) {
    resetInteraction();
    onSelect(findingId);
  }

  function startEditing(finding: AiFinding) {
    resetInteraction();
    setEditedPayload({ ...finding.proposed_payload });
    setEditing(true);
  }

  useEffect(() => {
    function keyboard(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey || busy) return;
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, textarea, select, button, a")) return;
      if ((event.key === "j" || event.key === "k") && selected) {
        const current = findings.findIndex((item) => item.id === selected.id);
        const next = event.key === "j" ? Math.min(current + 1, findings.length - 1) : Math.max(current - 1, 0);
        if (findings[next]) {
          setEditing(false);
          setRejecting(false);
          setConfirmingApply(false);
          setRejectionReason("");
          onSelect(findings[next].id);
        }
      }
      if (selected?.status === "pending_review" && !selected.superseded_by && !selected.ai_draft_id && event.key.toLowerCase() === "a" && proposalReady(selected, selected.proposed_payload)) void onAccept(selected);
      if (selected?.status === "pending_review" && !selected.superseded_by && !selected.ai_draft_id && event.key.toLowerCase() === "e") {
        setRejecting(false);
        setConfirmingApply(false);
        setRejectionReason("");
        setEditedPayload({ ...selected.proposed_payload });
        setEditing(true);
      }
      if (selected?.status === "pending_review" && !selected.superseded_by && !selected.ai_draft_id && event.key.toLowerCase() === "r") {
        setEditing(false);
        setConfirmingApply(false);
        setRejectionReason("");
        setRejecting(true);
      }
    }
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  }, [busy, findings, onAccept, onSelect, selected]);

  const decided = findings.filter((item) => item.status !== "pending_review").length;
  const accepted = findings.filter((item) => ["accepted", "applied"].includes(item.status)).length;
  const acceptanceRate = decided === 0 ? "—" : `${Math.round((accepted / decided) * 100)}%`;
  const filters: { key: FindingFilter; label: string }[] = [
    { key: "all", label: "全部" },
    ...Object.entries(typeLabels).map(([key, label]) => ({ key: key as FindingType, label })),
  ];

  return (
    <WorkspaceShell active="ai-review" identity={identity} loggingOut={loggingOut} onLogout={onLogout}>
      <div className="flex flex-wrap items-end justify-between gap-4 border-b pb-4">
        <div>
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">Engineer Workspace</p>
          <h1 className="mt-1 text-lg font-semibold" data-testid="ai-review-ready">AI Review 收件箱</h1>
          <p className="mt-1 text-sm text-muted-foreground">每条建议由人独立裁决；接受后仍需再次确认才写入业务对象。</p>
        </div>
        <dl className="flex overflow-hidden rounded-lg border bg-card text-center">
          <div className="min-w-24 px-3 py-2"><dt className="text-[10px] text-muted-foreground">可见接受率</dt><dd className="mt-0.5 font-mono text-base font-semibold">{acceptanceRate}</dd></div>
          <div className="min-w-24 border-l px-3 py-2"><dt className="text-[10px] text-muted-foreground">待处理</dt><dd className="mt-0.5 font-mono text-base font-semibold">{findings.filter((item) => item.status === "pending_review").length}</dd></div>
          <div className="min-w-24 border-l px-3 py-2"><dt className="text-[10px] text-muted-foreground">待应用</dt><dd className="mt-0.5 font-mono text-base font-semibold">{findings.filter((item) => item.status === "accepted").length}</dd></div>
        </dl>
      </div>

      {status ? <p className="mt-4 rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-sm text-success" role="status">{status}</p> : null}
      {error ? <p className="mt-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</p> : null}

      <div className="mt-5 flex flex-nowrap gap-2 overflow-x-auto sm:flex-wrap sm:overflow-visible" aria-label="Finding 类型筛选" role="group">
        {filters.map((item) => (
          <button
            aria-pressed={filter === item.key}
            className={cn(
              "min-h-11 shrink-0 whitespace-nowrap rounded-full border px-3 text-xs font-medium transition-colors sm:min-h-8",
              filter === item.key ? "border-primary bg-primary text-primary-foreground" : "bg-card text-muted-foreground hover:bg-muted",
            )}
            key={item.key}
            onClick={() => { resetInteraction(); onFilterChange(item.key); }}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </div>

      {findings.length === 0 ? (
        <section className="mt-5 flex min-h-96 flex-col items-center justify-center rounded-lg border border-dashed bg-card px-6 text-center" role="status">
          <TrayIcon aria-hidden="true" className="size-9 text-muted-foreground" />
          <h2 className="mt-3 font-semibold">当前没有 Finding</h2>
          <p className="mt-1 max-w-lg text-sm leading-6 text-muted-foreground">
            当前筛选没有待处理或历史 Finding；队列为空不代表模型或 Agent 可用。
          </p>
          {["owner", "admin"].includes(identity.user.role) ? (
            <Link className="mt-3 inline-flex min-h-11 items-center text-sm font-medium text-primary" href="/governance/models">
              检查模型治理状态
            </Link>
          ) : null}
        </section>
      ) : (
        <div className="mt-5 flex min-h-[620px] flex-col overflow-hidden rounded-lg border bg-card lg:grid lg:grid-cols-[288px_minmax(0,1fr)]">
          <aside aria-label="Finding 队列" className="order-last max-h-[340px] overflow-y-auto border-t lg:order-none lg:max-h-[700px] lg:border-t-0 lg:border-r">
            <ol role="list">
              {findings.map((finding) => (
                <li className="border-b last:border-b-0" key={finding.id}>
                  <button
                    aria-current={selected?.id === finding.id ? "true" : undefined}
                    className={cn(
                      "w-full px-4 py-3 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-ring/25",
                      selected?.id === finding.id && "bg-primary/8 shadow-[inset_2px_0_0_var(--primary)]",
                    )}
                    onClick={() => selectFinding(finding.id)}
                    type="button"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="rounded-lg bg-accent px-2 py-0.5 text-[10px] font-semibold text-accent-foreground">{agentLabels[finding.agent_key] ?? finding.agent_key}</span>
                      <StatusBadge finding={finding} />
                    </div>
                    <p className="mt-2 line-clamp-2 text-sm font-medium">{finding.title}</p>
                    <p className="mt-1 truncate text-[11px] text-muted-foreground">{projectLabel(finding, projectsById)}</p>
                    <p className="mt-1 font-mono text-[10px] text-muted-foreground">{["supplier_recovery", "capa_work_package", "change_work_package", "test_plan_change", "meeting_minutes", "meeting_action", "meeting_decision", ...meetingBusinessTypes].includes(finding.finding_type) ? "待人工核对" : `置信 ${(finding.confidence_basis_points / 10_000).toFixed(2)}`} · {formatTimestamp(finding.created_at)}</p>
                  </button>
                </li>
              ))}
            </ol>
          </aside>

          {selected ? (
            <article aria-label="Finding 详情" className="order-first max-h-[70svh] min-w-0 overflow-y-auto lg:order-none lg:max-h-[min(700px,calc(100svh-20rem))]">
              <header className="border-b px-4 py-4 sm:px-5">
                <div className="flex flex-wrap items-center gap-2"><StatusBadge finding={selected} /><span className="text-[11px] text-muted-foreground">{typeLabels[selected.finding_type]}</span></div>
                <h2 className="mt-2 text-base font-semibold">{selected.title}</h2>
                <p className={cn("mt-1 text-sm leading-6 text-muted-foreground", !summaryExpanded && "line-clamp-3")} id="finding-summary">{selected.summary}</p>
                {selected.summary.length > 180 ? <button aria-controls="finding-summary" aria-expanded={summaryExpanded} className="mt-1 min-h-8 text-xs font-medium text-primary" onClick={() => setSummaryExpanded((current) => !current)} type="button">{summaryExpanded ? "收起说明" : "展开完整说明"}</button> : null}
                <details className="mt-3 text-xs text-muted-foreground">
                  <summary className="min-h-11 cursor-pointer py-3 font-medium sm:min-h-0 sm:py-0">展开触发链</summary>
                  <p className="mt-2 break-all font-mono text-[10px]">events {selected.evidence_event_ids.map((id) => `#${id}`).join(", ") || "none"} → {selected.agent_key} → run {selected.run_id}</p>
                </details>
              </header>

              {selected.superseded_by ? <p className="p-4 text-pending">此建议已有新修订。<Link className="underline" href={`/ai-review?finding=${selected.superseded_by}`} onClick={() => onSelect(selected.superseded_by!)}>查看最新建议</Link></p> : null}
              <section aria-labelledby="finding-diff-title">
                <h3 className="border-b px-4 py-3 font-semibold sm:px-5" id="finding-diff-title">建议内容 · 逐字段对比</h3>
                {selected.finding_type === "supplier_recovery" ? (!editing && !confirmingApply ? <SupplierRecoveryProposalView projectId={selected.project_id} payload={payloadFor(selected)} /> : null) : selected.finding_type === "capa_work_package" ? (!editing && !confirmingApply ? <QualityWorkPackageProposalView projectId={selected.project_id} payload={payloadFor(selected)} /> : null) : selected.finding_type === "change_work_package" ? (!editing && !confirmingApply ? <ChangeWorkPackageProposalView projectId={selected.project_id} payload={payloadFor(selected)} /> : null) : meetingBusinessTypes.includes(selected.finding_type) ? (!editing && !confirmingApply ? <MeetingBusinessProposalView projectId={selected.project_id} payload={payloadFor(selected)} /> : null) : selected.finding_type === "meeting_decision" ? (!editing && !confirmingApply ? <MeetingDecisionProposalView draftOwned={Boolean(selected.ai_draft_id)} projectId={selected.project_id} payload={payloadFor(selected)} /> : null) : selected.finding_type === "meeting_action" ? (!editing && !confirmingApply ? <MeetingActionProposalView draftOwned={Boolean(selected.ai_draft_id)} projectId={selected.project_id} payload={payloadFor(selected)} /> : null) : selected.finding_type === "meeting_minutes" ? (!editing && !confirmingApply ? <MeetingMinutesProposalView draftOwned={Boolean(selected.ai_draft_id)} projectId={selected.project_id} payload={payloadFor(selected)} /> : null) : selected.finding_type === "test_plan_change" ? (!editing && !confirmingApply ? <TestPlanProposalView payload={payloadFor(selected)} /> : null) : <>
                <div className="hidden grid-cols-[140px_minmax(0,1fr)_minmax(0,1fr)] border-b bg-muted/30 px-4 py-2 text-[11px] text-muted-foreground sm:grid sm:px-5"><span>字段</span><span>业务现状</span><span>AI 建议</span></div>
                <dl>
                  {Object.entries(payloadFor(selected)).map(([field, value]) => (
                    <div className="grid gap-1 border-b px-4 py-3 text-xs sm:grid-cols-[140px_minmax(0,1fr)_minmax(0,1fr)] sm:px-5" key={field}>
                      <dt className="font-medium">{fieldLabels[field] ?? field}</dt>
                      <dd className="text-muted-foreground">{selected.finding_type === "knowledge_draft" ? "未验证知识中无此内容" : "业务对象尚未创建"}</dd>
                      <dd className="break-words bg-success/8 px-2 py-1 text-foreground">{formatValue(value)}</dd>
                    </div>
                  ))}
                </dl>
                </>}
                {editing ? <PayloadEditor finding={selected} onChange={setEditedPayload} payload={editedPayload} /> : null}
              </section>

              <section aria-labelledby="finding-evidence-title" className="border-t">
                <h3 className="border-b px-4 py-3 font-semibold sm:px-5" id="finding-evidence-title">{["supplier_recovery", "change_work_package", "capa_work_package"].includes(selected.finding_type) ? "原字段引用" : `证据引用（${selected.evidence.length}）`}</h3>
                {["supplier_recovery", "change_work_package", "capa_work_package"].includes(selected.finding_type) ? <p className="px-4 py-4 text-sm sm:px-5">本候选逐条保留上方业务资料的原字段、实际摘录及固定版本。请同时核对覆盖限制与未知影响。</p> : ["meeting_minutes", "meeting_action", "meeting_decision", ...meetingBusinessTypes].includes(selected.finding_type) ? <p className="px-4 py-4 text-sm sm:px-5">本候选使用上方的转写片段原句，不以事件编号替代转写证据。</p> : selected.evidence.length === 0 ? <p className="px-4 py-4 text-sm text-destructive sm:px-5">无引用，不能据此直接应用。</p> : (
                  <ol className="divide-y">
                    {selected.evidence.map((evidence, index) => (
                      <li className="flex min-w-0 items-center gap-3 px-4 py-3 sm:px-5" key={evidence.event_row_id}>
                        <span className="font-mono text-[11px] text-muted-foreground">[{index + 1}]</span>
                        <span className="min-w-0 flex-1 truncate text-xs">{evidence.label}</span>
                        <Link className="inline-flex min-h-11 shrink-0 items-center gap-1 text-xs font-medium text-primary sm:min-h-0" href={evidence.href}>{evidence.event_row_id ? "查看事件" : "查看证据"}<ArrowSquareOutIcon aria-hidden="true" /></Link>
                      </li>
                    ))}
                  </ol>
                )}
              </section>

              {rejecting ? (
                <section className="border-t bg-destructive/5 p-4 sm:p-5" aria-label="拒绝原因">
                  <label className="grid gap-1.5 text-xs font-medium">拒绝原因（必选）
                    <select className="h-11 rounded-lg border bg-background px-3 text-sm" onChange={(event) => setRejectionReason(event.target.value)} value={rejectionReason}>
                      <option value="">请选择原因</option>
                      {rejectionReasons.map((reason) => <option key={reason} value={reason}>{reason}</option>)}
                    </select>
                  </label>
                </section>
              ) : null}

              {confirmingApply ? (
                <section className="border-t border-applied/30 bg-applied/5 p-4 sm:p-5" aria-label="最终写入预览">
                  <h3 className="font-semibold text-applied">最终写入预览</h3>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    {selected.finding_type === "supplier_recovery" ? "将按人工核对内容逐项创建具名恢复任务，保留原资料与沟通草稿。实际到货、替代验证、拆借授权与工装可用证据继续在原业务办理。" : selected.finding_type === "capa_work_package" ? "将按已接受内容建立具名调查待办或待执行 CAPA 措施。服务端重新核对原质量状态、责任资格与日期；不会批准根因、完成整改或关闭 NCR。" : selected.finding_type === "change_work_package" ? "将按逐项人工结论生成变更范围新版本，保留原有其他条目和关系。应用前复核当前来源和范围；后续分析、批准及任务安排仍在原变更办理。" : meetingBusinessTypes.includes(selected.finding_type) ? "将按已接受内容创建对应的问题、风险或变更申请，并保存转写及人审来源；后续分析、处置、审批和关闭仍沿原业务办理。" : selected.finding_type === "meeting_decision" ? "仅指定批准人本人可应用：将记录已接受的决策结论与原文依据，保留待跟进要求，不直接完成基线、定义发布或其他业务执行。" : selected.finding_type === "meeting_action" ? "将按已接受的负责人、日期和完成标准创建实际会议行动任务，并回链所选议题；后续沿任务执行和会议复查办理。" : selected.finding_type === "meeting_minutes" ? "将创建已接受的正式纪要新版本，保留原版与来源；服务端重新核对当前版本、转写、说话人及纪要确认权限。此操作不创建或批准决定和行动。" : selected.finding_type === "test_plan_change" ? "将创建测试计划新修订，所有用例从待测开始。旧计划、报告与结果保留。"
                      : selected.finding_type === "knowledge_draft"
                      ? "将按下方已接受载荷创建未验证 Memory 草稿；它不会进入检索，仍须由另一位成员验证。"
                      : "将按下方已接受载荷创建项目 Risk。提交时服务端会重新检查身份、项目状态、run、invocation 与证据真值。"}
                  </p>
                  {selected.finding_type === "supplier_recovery" ? <SupplierRecoveryProposalView projectId={selected.project_id} payload={selected.accepted_payload ?? {}} /> : selected.finding_type === "capa_work_package" ? <QualityWorkPackageProposalView projectId={selected.project_id} payload={selected.accepted_payload ?? {}} /> : selected.finding_type === "change_work_package" ? <ChangeWorkPackageProposalView projectId={selected.project_id} payload={selected.accepted_payload ?? {}} /> : meetingBusinessTypes.includes(selected.finding_type) ? <MeetingBusinessProposalView projectId={selected.project_id} payload={selected.accepted_payload ?? {}} /> : selected.finding_type === "meeting_decision" ? <MeetingDecisionProposalView draftOwned={Boolean(selected.ai_draft_id)} projectId={selected.project_id} payload={selected.accepted_payload ?? {}} /> : selected.finding_type === "meeting_action" ? <MeetingActionProposalView draftOwned={Boolean(selected.ai_draft_id)} projectId={selected.project_id} payload={selected.accepted_payload ?? {}} /> : selected.finding_type === "meeting_minutes" ? <MeetingMinutesProposalView draftOwned={Boolean(selected.ai_draft_id)} projectId={selected.project_id} payload={selected.accepted_payload ?? {}} /> : selected.finding_type === "test_plan_change" ? <TestPlanProposalView payload={selected.accepted_payload ?? {}} /> : <pre className="mt-3 max-h-52 overflow-auto rounded-lg border bg-background p-3 text-xs leading-5">{JSON.stringify(selected.accepted_payload, null, 2)}</pre>}
                </section>
              ) : null}

              {selected.finding_type === "supplier_recovery" && selected.status === "applied" && <SupplierRecoveryAppliedTasks key={selected.id} projectId={selected.project_id} findingId={selected.id}/>}
              <footer className="sticky bottom-0 flex flex-wrap items-center gap-2 border-t bg-card/95 px-4 py-3 backdrop-blur sm:px-5">
                {selected.ai_draft_id && <Link className="inline-flex min-h-11 items-center text-sm font-medium text-primary" href={`/projects?project=${selected.project_id}&tab=decisions&meeting=${String(selected.proposed_payload.meeting_id ?? "")}`}>打开会议，确认或修订 AI 会议草稿</Link>}
                {selected.status === "pending_review" && !selected.superseded_by && !selected.ai_draft_id && !editing && !rejecting ? (
                  <>
                    <Button className="h-11" disabled={busy || !proposalReady(selected, selected.proposed_payload)} onClick={() => void onAccept(selected)}><CheckCircleIcon aria-hidden="true" />接受建议 <kbd className="ml-1 text-[10px] opacity-70">A</kbd></Button>
                    <Button className="h-11" disabled={busy} onClick={() => startEditing(selected)} variant="outline"><PencilSimpleIcon aria-hidden="true" />修改后接受 <kbd className="ml-1 text-[10px] opacity-70">E</kbd></Button>
                    <Button className="h-11" disabled={busy} onClick={() => { resetInteraction(); setRejecting(true); }} variant="destructive"><XCircleIcon aria-hidden="true" />拒绝 <kbd className="ml-1 text-[10px] opacity-70">R</kbd></Button>
                  </>
                ) : null}
                {selected.status === "pending_review" && editing ? (
                  <>
                    <Button className="h-11" disabled={busy || !proposalReady(selected, editedPayload)} onClick={async () => { if (await onEditAccept(selected, editedPayload)) setEditing(false); }}>确认修改并接受</Button>
                    <Button className="h-11" disabled={busy} onClick={() => setEditing(false)} variant="outline">取消</Button>
                  </>
                ) : null}
                {selected.status === "pending_review" && rejecting ? (
                  <>
                    <Button className="h-11" disabled={busy || !rejectionReason} onClick={async () => { if (await onReject(selected, rejectionReason)) setRejecting(false); }} variant="destructive">确认拒绝</Button>
                    <Button className="h-11" disabled={busy} onClick={() => setRejecting(false)} variant="outline">取消</Button>
                  </>
                ) : null}
                {selected.status === "accepted" && !selected.superseded_by && !selected.ai_draft_id && !confirmingApply ? <Button className="h-11" disabled={busy} onClick={() => setConfirmingApply(true)}>{selected.finding_type === "knowledge_draft" ? "创建 Memory 草稿" : "应用到业务对象"}</Button> : null}
                {selected.status === "accepted" && confirmingApply ? (
                  <>
                    <Button className="h-11" disabled={busy} onClick={() => { setConfirmingApply(false); onApply(selected); }}>确认应用</Button>
                    <Button className="h-11" disabled={busy} onClick={() => setConfirmingApply(false)} variant="outline">取消</Button>
                  </>
                ) : null}
                {selected.status === "applied" && selected.applied_entity_type === "quality_work_package" ? <Link className="inline-flex min-h-11 items-center text-sm font-medium text-applied" href={`/projects?project=${selected.project_id}&tab=quality&ncr=${String(selected.accepted_payload?.ncr_id ?? "")}`}>查看实际品质任务、措施与后续观察要求</Link> : null}
                {selected.status === "applied" && selected.applied_entity_type === "change_impact_scope" ? <Link className="inline-flex min-h-11 items-center text-sm font-medium text-applied" href={`/projects?project=${selected.project_id}&tab=engineering&ecr=${String(selected.accepted_payload?.ecr_id ?? "")}`}>查看实际变更范围与后续办理</Link> : null}
                {selected.status === "applied" && selected.applied_entity_type === "memory" ? <Link className="inline-flex min-h-11 items-center gap-1 text-sm font-medium text-applied" href={`/knowledge?project=${selected.project_id}&memory=${selected.applied_entity_id}`}>查看 Memory 草稿 <ArrowSquareOutIcon aria-hidden="true" /></Link> : null}
                {selected.status === "applied" && selected.applied_entity_type === "risk" ? <Link className="inline-flex min-h-11 items-center gap-1 text-sm font-medium text-applied" href={`/projects?project=${selected.project_id}&tab=work-items`}>查看已应用 Risk <ArrowSquareOutIcon aria-hidden="true" /></Link> : null}
                {selected.status === "applied" && meetingBusinessTypes.includes(selected.finding_type) ? <Link className="inline-flex min-h-11 items-center text-sm font-medium text-applied" href={selected.finding_type === "meeting_change" ? `/projects?project=${selected.project_id}&tab=engineering&ecr=${selected.applied_entity_id}` : `/projects?project=${selected.project_id}&tab=work-items&entity_id=${selected.applied_entity_id}`}>打开实际业务记录</Link> : null}
                {selected.status === "applied" && selected.finding_type === "meeting_decision" ? <Link className="inline-flex min-h-11 items-center text-sm font-medium text-applied" href={`/projects?project=${selected.project_id}&tab=decisions`}>查看正式决策及执行跟进</Link> : null}
                {selected.status === "applied" && selected.finding_type === "meeting_action" ? <Link className="inline-flex min-h-11 items-center text-sm font-medium text-applied" href={`/projects?project=${selected.project_id}&tab=work-items&entity_id=${selected.applied_entity_id}`}>打开实际会议行动任务</Link> : null}
                {selected.status === "applied" && selected.applied_entity_type === "meeting_minutes" ? <Link className="inline-flex min-h-11 items-center text-sm font-medium text-applied" href={`/projects?project=${selected.project_id}&tab=decisions&meeting=${String(selected.accepted_payload?.meeting_id ?? "")}`}>查看正式纪要版本</Link> : null}
                {selected.status === "applied" && selected.applied_entity_type === "test_plan" ? <Link className="inline-flex min-h-11 items-center text-sm font-medium text-applied" href={`/projects?project=${selected.project_id}&tab=quality`}>查看测试计划新修订</Link> : null}
                <span className="ml-auto hidden items-center gap-1 text-[10px] text-muted-foreground xl:inline-flex"><SparkleIcon aria-hidden="true" />j/k 切换条目</span>
              </footer>
            </article>
          ) : null}
        </div>
      )}
      {extraSections ?? null}
    </WorkspaceShell>
  );
}
