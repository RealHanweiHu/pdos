"use client";

import { useEffect, useState } from "react";
import { CaretRightIcon, CheckIcon, CircleIcon, SpinnerGapIcon, WarningCircleIcon } from "@phosphor-icons/react";

type StepState = "running" | "completed" | "partial" | "failed" | "stopped";
export type ReplyProcess = {
  state: Exclude<StepState, "partial">;
  elapsed_ms: number;
  earlier_steps_omitted?: number;
  steps: { key: string; label: string; detail: string; state: StepState; at_ms: number }[];
};

export function XiaopaiProcess({ process, live = false }: { process?: ReplyProcess | null; live?: boolean }) {
  const [open, setOpen] = useState(live);
  const [started] = useState(() => Date.now() - (process?.elapsed_ms ?? 0));
  const [now, setNow] = useState(() => Date.now());
  const running = live && process?.state === "running";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  if (!process?.steps.length) return null;
  const seconds = Math.max(0, Math.floor(Math.max(process.elapsed_ms, running ? now - started : 0) / 1000));
  const state = process.state === "completed" ? "已完成" : process.state === "failed" ? "未完成" : process.state === "stopped" ? "已停止" : live ? "进行中" : "等待核对";
  return <details open={open} onToggle={event => setOpen(event.currentTarget.open)} className="mb-3 min-w-0 rounded-lg border border-border/60 bg-muted/20 text-xs">
    <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-muted-foreground [&::-webkit-details-marker]:hidden">
      {running ? <SpinnerGapIcon aria-hidden="true" className="size-3.5 shrink-0 text-primary motion-safe:animate-spin"/> : <CaretRightIcon aria-hidden="true" className={`size-3.5 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}/>}
      <span className="font-medium">思考与处理过程</span><span className="ml-auto whitespace-nowrap">{state} · {seconds} 秒</span>
    </summary>
    {!!process.earlier_steps_omitted && <p className="border-t border-border/50 px-3 py-2 text-muted-foreground">显示最近 {process.steps.length} 步，较早的 {process.earlier_steps_omitted} 步已收起。研究来源可在“已检索资料”中查看。</p>}
    <ol aria-label="小Pai处理步骤" className="space-y-3 border-t border-border/50 px-3 py-3">
      {process.steps.map(step => {
        const Icon = step.state === "running" && running ? SpinnerGapIcon : step.state === "completed" ? CheckIcon : ["failed", "partial"].includes(step.state) ? WarningCircleIcon : CircleIcon;
        return <li key={step.key} className="flex min-w-0 gap-2.5">
          <Icon aria-hidden="true" className={`mt-0.5 size-3.5 shrink-0 ${step.state === "running" && running ? "text-primary motion-safe:animate-spin" : step.state === "failed" ? "text-destructive" : step.state === "partial" ? "text-pending" : "text-muted-foreground"}`}/>
          <div className="min-w-0 flex-1"><div className="flex items-start justify-between gap-2"><p className="break-words font-medium leading-5 text-foreground/80">{step.label}</p><span className="shrink-0 pt-0.5 text-[10px] text-muted-foreground">{Math.floor(step.at_ms / 1000)} 秒</span></div>{step.detail && <p className="mt-1 whitespace-pre-wrap break-words leading-5 text-muted-foreground">{step.detail}</p>}</div>
        </li>;
      })}
    </ol>
  </details>;
}
