"use client";

import {
  ArrowSquareOutIcon,
  CheckCircleIcon,
  PencilSimpleIcon,
  SparkleIcon,
  TrayIcon,
  XCircleIcon,
} from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useState } from "react";

import type { Project } from "@/components/projects/project-types";
import { Button } from "@/components/ui/button";
import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { cn } from "@/lib/utils";

import type { AiFinding, FindingType } from "./ai-types";

export type FindingFilter = "all" | FindingType;

const typeLabels: Record<FindingType, string> = {
  risk_suggestion: "风险建议",
  blocker_alert: "阻塞预警",
  gate_readiness_anomaly: "Gate 异常",
  knowledge_draft: "知识草稿",
  bom_impact_suggestion: "BOM 影响建议",
  change_impact_suggestion: "变更影响建议",
  quality_cluster_alert: "质量聚类预警",
  capa_suggestion: "CAPA 建议",
};

const agentLabels: Record<string, string> = {
  project_intelligence: "Project Intelligence",
  knowledge_lite: "Knowledge Lite",
  engineering_intelligence: "Engineering Intelligence",
  quality_intelligence: "Quality Intelligence",
};

const statusLabels = {
  pending_review: "待人审",
  accepted: "待应用",
  rejected: "已拒绝",
  applied: "已应用",
} as const;

const fieldLabels: Record<string, string> = {
  title: "标题",
  description: "描述",
  likelihood: "发生概率",
  impact: "影响程度",
  mitigation_plan: "缓解计划",
  contingency_plan: "应急计划",
  target_date: "目标日期",
  draft_text: "知识草稿",
  applicability: "适用范围",
};

const rejectionReasons = ["不准确", "重复", "不相关", "证据不足"] as const;

function projectLabel(finding: AiFinding, projects: Project[]) {
  const project = projects.find((item) => item.id === finding.project_id);
  return project ? `${project.code} · ${project.name}` : finding.project_id;
}

function formatTimestamp(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
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
      )}
    >
      {statusLabels[finding.status]}
    </span>
  );
}

function PayloadEditor({
  finding,
  onChange,
  payload,
}: {
  finding: AiFinding;
  onChange: (payload: Record<string, unknown>) => void;
  payload: Record<string, unknown>;
}) {
  const fields = finding.finding_type === "knowledge_draft"
    ? ["title", "draft_text", "applicability"]
    : [
        "title",
        "description",
        "likelihood",
        "impact",
        "mitigation_plan",
        "contingency_plan",
        "target_date",
      ];
  return (
    <div className="grid gap-3 border-t bg-muted/20 p-4 sm:grid-cols-2">
      {fields.map((field) => {
        const numeric = field === "likelihood" || field === "impact";
        const multiline = ["description", "mitigation_plan", "contingency_plan", "draft_text", "applicability"].includes(field);
        return (
          <label className={cn("grid gap-1.5 text-xs font-medium", multiline && "sm:col-span-2")} key={field}>
            {fieldLabels[field] ?? field}
            {multiline ? (
              <textarea
                className="min-h-24 rounded-lg border bg-background px-3 py-2 text-sm font-normal"
                onChange={(event) => onChange({ ...payload, [field]: event.target.value || null })}
                value={typeof payload[field] === "string" ? payload[field] : ""}
              />
            ) : (
              <input
                className="h-11 rounded-lg border bg-background px-3 text-sm font-normal"
                max={numeric ? 5 : undefined}
                min={numeric ? 1 : undefined}
                onChange={(event) => onChange({
                  ...payload,
                  [field]: numeric ? Number(event.target.value) : event.target.value || null,
                })}
                required={field === "title" || numeric}
                type={numeric ? "number" : field === "target_date" ? "date" : "text"}
                value={typeof payload[field] === "string" || typeof payload[field] === "number" ? String(payload[field]) : ""}
              />
            )}
          </label>
        );
      })}
    </div>
  );
}

export function AiReviewInboxView({
  busy,
  error,
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

  function resetInteraction() {
    setEditing(false);
    setRejecting(false);
    setConfirmingApply(false);
    setRejectionReason("");
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
      if (selected?.status === "pending_review" && event.key.toLowerCase() === "a") void onAccept(selected);
      if (selected?.status === "pending_review" && event.key.toLowerCase() === "e") {
        setRejecting(false);
        setConfirmingApply(false);
        setRejectionReason("");
        setEditedPayload({ ...selected.proposed_payload });
        setEditing(true);
      }
      if (selected?.status === "pending_review" && event.key.toLowerCase() === "r") {
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
          <h1 className="mt-1 text-lg font-semibold">AI Review 收件箱</h1>
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

      <div className="mt-5 flex flex-wrap gap-2" aria-label="Finding 类型筛选">
        {filters.map((item) => (
          <button
            aria-pressed={filter === item.key}
            className={cn(
              "min-h-11 rounded-full border px-3 text-xs font-medium transition-colors sm:min-h-8",
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
        <div className="mt-5 min-h-[620px] overflow-hidden rounded-lg border bg-card lg:grid lg:grid-cols-[288px_minmax(0,1fr)]">
          <aside aria-label="Finding 队列" className="max-h-[340px] overflow-y-auto border-b lg:max-h-[700px] lg:border-b-0 lg:border-r">
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
                    <p className="mt-1 truncate text-[11px] text-muted-foreground">{projectLabel(finding, projects)}</p>
                    <p className="mt-1 font-mono text-[10px] text-muted-foreground">置信 {(finding.confidence_basis_points / 10_000).toFixed(2)} · {formatTimestamp(finding.created_at)}</p>
                  </button>
                </li>
              ))}
            </ol>
          </aside>

          {selected ? (
            <article aria-label="Finding 详情" className="min-w-0 overflow-y-auto lg:max-h-[700px]">
              <header className="border-b px-4 py-4 sm:px-5">
                <div className="flex flex-wrap items-center gap-2"><StatusBadge finding={selected} /><span className="text-[11px] text-muted-foreground">{typeLabels[selected.finding_type]}</span></div>
                <h2 className="mt-2 text-base font-semibold">{selected.title}</h2>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">{selected.summary}</p>
                <details className="mt-3 text-xs text-muted-foreground">
                  <summary className="min-h-11 cursor-pointer py-3 font-medium sm:min-h-0 sm:py-0">展开触发链</summary>
                  <p className="mt-2 break-all font-mono text-[10px]">events {selected.evidence_event_ids.map((id) => `#${id}`).join(", ") || "none"} → {selected.agent_key} → run {selected.run_id}</p>
                </details>
              </header>

              <section aria-labelledby="finding-diff-title">
                <h3 className="border-b px-4 py-3 font-semibold sm:px-5" id="finding-diff-title">建议内容 · 逐字段对比</h3>
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
                {editing ? <PayloadEditor finding={selected} onChange={setEditedPayload} payload={editedPayload} /> : null}
              </section>

              <section aria-labelledby="finding-evidence-title" className="border-t">
                <h3 className="border-b px-4 py-3 font-semibold sm:px-5" id="finding-evidence-title">证据引用（{selected.evidence.length}）</h3>
                {selected.evidence.length === 0 ? <p className="px-4 py-4 text-sm text-destructive sm:px-5">无引用，不能据此直接应用。</p> : (
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
                    {selected.finding_type === "knowledge_draft"
                      ? "将按下方已接受载荷创建未验证 Memory 草稿；它不会进入检索，仍须由另一位成员验证。"
                      : "将按下方已接受载荷创建项目 Risk。提交时服务端会重新检查身份、项目状态、run、invocation 与证据真值。"}
                  </p>
                  <pre className="mt-3 max-h-52 overflow-auto rounded-lg border bg-background p-3 text-xs leading-5">{JSON.stringify(selected.accepted_payload, null, 2)}</pre>
                </section>
              ) : null}

              <footer className="sticky bottom-0 flex flex-wrap items-center gap-2 border-t bg-card/95 px-4 py-3 backdrop-blur sm:px-5">
                {selected.status === "pending_review" && !editing && !rejecting ? (
                  <>
                    <Button className="h-11" disabled={busy} onClick={() => void onAccept(selected)}><CheckCircleIcon aria-hidden="true" />接受建议 <kbd className="ml-1 text-[10px] opacity-70">A</kbd></Button>
                    <Button className="h-11" disabled={busy} onClick={() => startEditing(selected)} variant="outline"><PencilSimpleIcon aria-hidden="true" />修改后接受 <kbd className="ml-1 text-[10px] opacity-70">E</kbd></Button>
                    <Button className="h-11" disabled={busy} onClick={() => { resetInteraction(); setRejecting(true); }} variant="destructive"><XCircleIcon aria-hidden="true" />拒绝 <kbd className="ml-1 text-[10px] opacity-70">R</kbd></Button>
                  </>
                ) : null}
                {selected.status === "pending_review" && editing ? (
                  <>
                    <Button className="h-11" disabled={busy} onClick={async () => { if (await onEditAccept(selected, editedPayload)) setEditing(false); }}>确认修改并接受</Button>
                    <Button className="h-11" disabled={busy} onClick={() => setEditing(false)} variant="outline">取消</Button>
                  </>
                ) : null}
                {selected.status === "pending_review" && rejecting ? (
                  <>
                    <Button className="h-11" disabled={busy || !rejectionReason} onClick={async () => { if (await onReject(selected, rejectionReason)) setRejecting(false); }} variant="destructive">确认拒绝</Button>
                    <Button className="h-11" disabled={busy} onClick={() => setRejecting(false)} variant="outline">取消</Button>
                  </>
                ) : null}
                {selected.status === "accepted" && !confirmingApply ? <Button className="h-11" disabled={busy} onClick={() => setConfirmingApply(true)}>{selected.finding_type === "knowledge_draft" ? "创建 Memory 草稿" : "应用到业务对象"}</Button> : null}
                {selected.status === "accepted" && confirmingApply ? (
                  <>
                    <Button className="h-11" disabled={busy} onClick={() => { setConfirmingApply(false); onApply(selected); }}>确认应用</Button>
                    <Button className="h-11" disabled={busy} onClick={() => setConfirmingApply(false)} variant="outline">取消</Button>
                  </>
                ) : null}
                {selected.status === "applied" && selected.applied_entity_type === "memory" ? <Link className="inline-flex min-h-11 items-center gap-1 text-sm font-medium text-applied" href={`/knowledge?project=${selected.project_id}&memory=${selected.applied_entity_id}`}>查看 Memory 草稿 <ArrowSquareOutIcon aria-hidden="true" /></Link> : null}
                {selected.status === "applied" && selected.applied_entity_type !== "memory" ? <Link className="inline-flex min-h-11 items-center gap-1 text-sm font-medium text-applied" href={`/projects?project=${selected.project_id}&tab=risks`}>查看已应用 Risk <ArrowSquareOutIcon aria-hidden="true" /></Link> : null}
                <span className="ml-auto hidden items-center gap-1 text-[10px] text-muted-foreground xl:inline-flex"><SparkleIcon aria-hidden="true" />j/k 切换条目</span>
              </footer>
            </article>
          ) : null}
        </div>
      )}
    </WorkspaceShell>
  );
}
