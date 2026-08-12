"use client";

import { CaretDownIcon, CheckCircleIcon, WarningCircleIcon } from "@phosphor-icons/react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { ProjectGate } from "./project-gate-document-types";
import type { WorkItemLoadState } from "./project-workspace-view";

const statusLabels: Record<string, string> = {
  preparing: "准备中",
  reviewing: "评审中",
  approved: "已批准",
  rejected: "已拒绝",
};

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

export function ProjectGatePanel({ gates, onRetry, state }: { gates: ProjectGate[] | null; onRetry: () => void; state: WorkItemLoadState }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  if (state !== "ready" || gates === null) return <GateState onRetry={onRetry} state={state} />;
  if (gates.length === 0) {
    return <div className="rounded-lg border px-4 py-10 text-center"><h3 className="font-semibold">尚未实例化 Gate</h3><p className="mt-1 text-sm text-muted-foreground">项目阶段建立后将在这里显示就绪度。</p></div>;
  }
  const selected = gates.find((gate) => gate.id === selectedId) ?? gates.find((gate) => gate.is_current) ?? gates[0];
  const blockers = selected.readiness.blockers;
  return (
    <div className="space-y-4">
      <div className="flex gap-2 overflow-x-auto pb-1" aria-label="Gate 阶段" role="list">
        {gates.map((gate) => (
          <button aria-pressed={selected.id === gate.id} className={cn("min-h-11 shrink-0 rounded-lg border px-3 text-left text-sm", selected.id === gate.id ? "border-primary bg-primary/5 text-primary" : "text-muted-foreground")} key={gate.id} onClick={() => { setSelectedId(gate.id); setExpanded(false); }} type="button">
            <span className="block font-medium">{gate.stage.name}</span>
            <span className="text-[11px]">{gate.readiness.ready ? "就绪" : `${gate.readiness.blockers.length} 个缺项`}</span>
          </button>
        ))}
      </div>
      <section aria-label={`${selected.stage.name} Gate 就绪度`} className="rounded-lg border bg-card p-4 sm:p-5">
        <div className="flex flex-wrap items-start gap-3">
          {selected.readiness.ready ? <CheckCircleIcon aria-hidden="true" className="mt-0.5 size-5 text-success" weight="fill" /> : <WarningCircleIcon aria-hidden="true" className="mt-0.5 size-5 text-primary" weight="fill" />}
          <div className="min-w-0 flex-1">
            <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{selected.code} · {statusLabels[selected.status] ?? selected.status}</p>
            <h3 className="mt-1 font-semibold">{selected.readiness.ready ? "当前 Gate 已就绪" : `${blockers.length} 个例外需要处理`}</h3>
            <p className="mt-1 text-sm text-muted-foreground">默认只显示缺项与风险；完整材料包按需展开。</p>
          </div>
        </div>
        {blockers.length ? <ul className="mt-4 divide-y rounded-lg border" aria-label="Gate 缺项"><li className="flex gap-3 px-3 py-3"><span className="mt-1 size-1.5 shrink-0 rounded-full bg-primary" /><div><p className="text-sm font-medium">{blockers[0].label}</p><p className="mt-0.5 text-xs text-muted-foreground">{blockers[0].kind}</p></div></li>{blockers.slice(1).map((blocker) => <li className="flex gap-3 px-3 py-3" hidden={!expanded} key={blocker.key}><span className="mt-1 size-1.5 shrink-0 rounded-full bg-primary" /><div><p className="text-sm font-medium">{blocker.label}</p><p className="mt-0.5 text-xs text-muted-foreground">{blocker.kind}</p></div></li>)}</ul> : <p className="mt-4 rounded-lg border border-success/30 bg-success/5 px-3 py-3 text-sm text-success">没有确定性阻塞项。</p>}
        {blockers.length > 1 ? <Button aria-expanded={expanded} className="mt-3 h-11" onClick={() => setExpanded((value) => !value)} variant="ghost">{expanded ? "收起完整材料包" : `展开其余 ${blockers.length - 1} 项`}<CaretDownIcon aria-hidden="true" className={cn("size-4 transition-transform", expanded && "rotate-180")} /></Button> : null}
      </section>
    </div>
  );
}
