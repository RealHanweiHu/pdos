"use client";

import { CaretDownIcon, CheckCircleIcon, WarningCircleIcon } from "@phosphor-icons/react";
import { useState } from "react";
import { useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { MaterialAdmissionControl } from "./material-admission-control";
import { ProjectGateAssignments } from "./project-gate-assignments";
import { ProjectGateConditions } from "./project-gate-conditions";
import { ProjectGateDecisionForm } from "./project-gate-decision-form";
import type { ProjectGate } from "./project-gate-document-types";
import type { ProjectWorkspaceTab, WorkItemLoadState } from "./project-workspace-view";

const statusLabels: Record<string, string> = {
  preparing: "准备中",
  reviewing: "评审中",
  approved: "已批准",
  conditional: "有条件通过",
  hold: "暂缓",
  rejected: "已拒绝",
};

const kindLabels: Record<string, string> = {
  material: "物料准入",
  round: "签核轮次",
  signoff: "专业签核",
  task: "阻塞任务",
  issue: "关键问题",
  risk: "高风险",
  deliverable_check: "交付检查项",
  build: "试制批次",
  sample: "样机",
  test_case: "测试用例",
  test_report: "测试报告",
  sample_signoff: "样机签核",
  certification: "认证",
};

const slotLabels = { product: "产品", engineering: "工程", quality: "质量" } as const;
const roleSlots: Record<string, readonly (keyof typeof slotLabels)[]> = {
  owner: ["product", "engineering", "quality"],
  admin: ["product", "engineering", "quality"],
  project_manager: ["product"],
  engineer: ["engineering"],
  quality: ["quality"],
};

const recoveryTabs: Partial<Record<string, { tab: ProjectWorkspaceTab; label: string }>> = {
  task: { tab: "work-items", label: "查看任务" },
  issue: { tab: "work-items", label: "查看问题" },
  risk: { tab: "work-items", label: "查看风险" },
  deliverable_check: { tab: "documents", label: "查看文档" },
  build: { tab: "engineering", label: "查看产品工程" },
  sample: { tab: "engineering", label: "查看产品工程" },
  test_case: { tab: "quality", label: "查看质量记录" },
  test_report: { tab: "quality", label: "查看质量记录" },
  sample_signoff: { tab: "quality", label: "查看质量记录" },
  certification: { tab: "documents", label: "查看认证材料" },
};

function blockerLabel(kind: string, key: string, original: string) {
  if (kind === "round") return "尚未开启 Gate 签核轮次";
  if (kind === "signoff") {
    const slot = key.split(":", 2)[1] as keyof typeof slotLabels;
    return `${slotLabels[slot] ?? slot}签核尚未完成`;
  }
  if (kind === "build" && original.includes("missing")) return "缺少已完成的试制批次";
  if (kind === "sample" && original.includes("missing")) return "缺少有效样机";
  if (kind === "test_report" && original.includes("missing")) return "缺少已批准的测试报告";
  return original;
}

function GateState({ onRetry, state }: { onRetry: () => void; state: WorkItemLoadState }) {
  if (state === "loading" || state === "idle") {
    return <p className="rounded-lg border px-4 py-10 text-center text-sm text-muted-foreground">正在计算 Gate 就绪度…</p>;
  }
  if (state === "error") {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-8 text-center">
        <h3 className="font-semibold">Gate 就绪度暂不可用</h3>
        <p className="mt-1 text-sm text-muted-foreground">读取失败不会被显示为零缺项。</p>
        <Button className="mt-4 h-11" onClick={onRetry} variant="outline">重新加载 Gate</Button>
      </div>
    );
  }
  return null;
}

export function ProjectGatePanel({
  actorRole,
  actorUserId,
  busy,
  canManage,
  error,
  gates,
  onNavigate,
  onOpenRound,
  onRetry,
  onSignoff,
  projectId,
  state,
}: {
  actorRole: string;
  actorUserId?: string;
  busy: boolean;
  canManage: boolean;
  error: string | null;
  gates: ProjectGate[] | null;
  onNavigate: (tab: ProjectWorkspaceTab) => void;
  onOpenRound: (gate: ProjectGate) => void;
  onRetry: () => void;
  onSignoff: (gate: ProjectGate, slot: "product" | "engineering" | "quality") => void;
  projectId: string;
  state: WorkItemLoadState;
}) {
  const search = useSearchParams();
  const parameter = (key: string) => { const value = search.get(key); return value && /^[0-9a-f-]{36}$/i.test(value) ? value.toLowerCase() : undefined; };
  const targetGate = parameter("gate"), targetRound = parameter("gate_round"), targetSigner = parameter("gate_signer");
  const scope = `${projectId}:${targetGate ?? ""}:${targetRound ?? ""}`;
  const [selection, setSelection] = useState<{ id: string; scope: string } | null>(null);
  const selectedId = selection?.scope === scope ? selection.id : null;
  const [expanded, setExpanded] = useState(false);
  if (state !== "ready" || gates === null) return <GateState onRetry={onRetry} state={state} />;
  if (gates.length === 0) {
    return <div className="rounded-lg border px-4 py-10 text-center"><h3 className="font-semibold">尚未实例化 Gate</h3><p className="mt-1 text-sm text-muted-foreground">项目阶段建立后将在这里显示就绪度。</p></div>;
  }
  const selected = gates.find((gate) => gate.id === selectedId) ?? gates.find((gate) => gate.id === targetGate) ?? gates.find((gate) => gate.is_current) ?? gates[0];
  const blockers = selected.readiness.blockers;
  const historicalReadiness = selected.round?.readiness_snapshot != null;
  function blockerRow(blocker: (typeof blockers)[number], hidden = false) {
    const recovery = recoveryTabs[blocker.kind];
    const slot = blocker.kind === "signoff"
      ? blocker.key.split(":", 2)[1] as keyof typeof slotLabels
      : null;
    const assigned = slot ? selected.round?.routing_snapshot?.assignment?.signers[slot] : null;
    const canSign = selected.status === "reviewing" && selected.round?.status === "open" && slot !== null && roleSlots[actorRole]?.includes(slot) && (!assigned || assigned.user_id === actorUserId);
    return (
      <li className="flex flex-wrap items-center gap-3 px-3 py-3" hidden={hidden} key={blocker.key}>
        <span className="size-1.5 shrink-0 rounded-full bg-primary" />
        <div className="min-w-48 flex-1">
          <p className="text-sm font-medium">{blockerLabel(blocker.kind, blocker.key, blocker.label)}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{kindLabels[blocker.kind] ?? "Gate 缺项"}</p>
          {assigned && <p className="mt-1 text-xs">本轮签核人：{assigned.display_name}</p>}
          {slot && Boolean(selected.round?.routing_blockers?.[slot]?.length) && <p className="mt-1 text-xs text-primary">先完成{selected.round?.routing_blockers?.[slot]?.map(prior => slotLabels[prior as keyof typeof slotLabels]).join("、")}签核，再办理本项。</p>}
        </div>
        {blocker.kind === "round" && canManage && selected.is_current && !selected.named_signer_policy?.required_slots?.length ? (
          <Button disabled={busy} onClick={() => onOpenRound(selected)} size="sm">开启签核轮次</Button>
        ) : null}
        {blocker.kind === "signoff" && slot && canSign && selected.round ? (
          <Button disabled={busy || Boolean(selected.round.routing_blockers?.[slot]?.length)} onClick={() => onSignoff(selected, slot)} size="sm">
            批准{slotLabels[slot]}签核
          </Button>
        ) : null}
        {recovery ? (
          <Button disabled={busy} onClick={() => onNavigate(recovery.tab)} size="sm" variant="outline">
            {recovery.label}
          </Button>
        ) : null}
      </li>
    );
  }
  return (
    <div className="space-y-4">
      {targetGate && !gates.some(gate => gate.id === targetGate) && <p className="rounded-md border p-3 text-sm" role="alert">未找到移交链接指向的 Gate。以下显示当前项目资料，请先核对项目及原移交记录。</p>}
      {error ? <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive" role="alert">{error}</p> : null}
      <div className="flex gap-2 overflow-x-auto pb-1" aria-label="Gate 阶段" role="list">
        {gates.map((gate) => (
          <button aria-pressed={selected.id === gate.id} className={cn("min-h-11 shrink-0 rounded-lg border px-3 text-left text-sm", selected.id === gate.id ? "border-primary bg-primary/5 text-primary" : "text-muted-foreground")} key={gate.id} onClick={() => { setSelection({ id: gate.id, scope }); setExpanded(false); }} type="button">
            <span className="block font-medium">{gate.stage.name}</span>
            <span className="text-[11px]">{gate.round?.readiness_snapshot != null ? (statusLabels[gate.status] ?? gate.status) : gate.readiness.ready ? "就绪" : `${gate.readiness.blockers.length} 个缺项`}</span>
          </button>
        ))}
      </div>
      <section aria-label={`${selected.stage.name} Gate 就绪度`} className="rounded-lg border bg-card p-4 sm:p-5">
        <div className="flex flex-wrap items-start gap-3">
          {selected.readiness.ready ? <CheckCircleIcon aria-hidden="true" className="mt-0.5 size-5 text-success" weight="fill" /> : <WarningCircleIcon aria-hidden="true" className="mt-0.5 size-5 text-primary" weight="fill" />}
          <div className="min-w-0 flex-1">
            <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{selected.code} · {statusLabels[selected.status] ?? selected.status}</p>
            <h3 className="mt-1 font-semibold">{historicalReadiness ? (selected.readiness.ready ? "原裁决时材料已就绪" : `原裁决时有 ${blockers.length} 个缺项`) : selected.readiness.ready ? "当前 Gate 已就绪" : `${blockers.length} 个例外需要处理`}</h3>
            <p className="mt-1 text-sm text-muted-foreground">{historicalReadiness ? "以下为原轮次固定的就绪记录；当前条件任务需另行核对，不据此推定已落实。" : "默认只显示缺项与风险；完整材料包按需展开。"}</p>
          </div>
        </div>
        <MaterialAdmissionControl key={selected.id} projectId={projectId} targetKind="gate" targetId={selected.id} onChanged={onRetry} />
        <ProjectGateAssignments key={`${selected.id}:${selected.round?.id}:${selected.signing_basis}:${targetRound ?? ""}:${targetSigner ?? ""}`} gate={selected} canManage={canManage} busy={busy} onChanged={onRetry} handoverRoundId={selected.id === targetGate ? targetRound : undefined} handoverUserId={selected.id === targetGate ? targetSigner : undefined} />
        {selected.round?.routing_snapshot?.dependencies && <details className="mt-3 rounded-md border p-3"><summary className="cursor-pointer text-sm">本轮签核先后依赖</summary><div className="mt-2 space-y-1 text-xs">{Object.entries(selected.round.routing_snapshot.dependencies).map(([slot, priors]) => <p key={slot}>{slotLabels[slot as keyof typeof slotLabels]}签核前须满足{priors.map(prior => slotLabels[prior as keyof typeof slotLabels]).join("、")}签核。</p>)}<p>修改上游结果或说明后，受影响的下游需重新确认；原结果保留在审计记录中。</p>{selected.round.routing_snapshot.source && <p>创建时模板 {selected.round.routing_snapshot.source.template_id} v{selected.round.routing_snapshot.source.template_version}。</p>}</div></details>}
        {blockers.length ? <ul className="mt-4 divide-y rounded-lg border" aria-label="Gate 缺项">{blockerRow(blockers[0])}{blockers.slice(1).map((blocker) => blockerRow(blocker, !expanded))}</ul> : <p className="mt-4 rounded-lg border border-success/30 bg-success/5 px-3 py-3 text-sm text-success">{historicalReadiness ? "原裁决时未记录确定性阻塞项；当前条件落实见下方。" : "没有确定性阻塞项。"}</p>}
        {blockers.length > 1 ? <Button aria-expanded={expanded} className="mt-3 h-11" onClick={() => setExpanded((value) => !value)} variant="ghost">{expanded ? "收起完整材料包" : `展开其余 ${blockers.length - 1} 项`}<CaretDownIcon aria-hidden="true" className={cn("size-4 transition-transform", expanded && "rotate-180")} /></Button> : null}
      </section>
      {canManage && selected.status === "reviewing" && selected.round?.status === "open" ? (
        <ProjectGateDecisionForm
          gateReady={selected.readiness.ready}
          gateId={selected.id}
          gateLabel={selected.stage.name}
          key={selected.id}
          onRecorded={onRetry}
          projectId={projectId}
        />
      ) : null}
      <ProjectGateConditions key={`${projectId}:${selected.id}:${selected.round?.id}:${selected.status}`} projectId={projectId} gateId={selected.id} />
    </div>
  );
}
