"use client";

import { ArrowSquareOutIcon, RobotIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";

import { WorkResponsibility } from "@/components/product-work/work-responsibility";

import { cn } from "@/lib/utils";

import { cancelAgentRun, controlAgentPause, requestAgentRuns } from "./ai-api";
import type { AgentRunList } from "./ai-types";
import { AgentRunProgressPanel } from "./agent-run-progress";

const runStatusLabels: Record<string, string> = {
  debouncing: "防抖中",
  queued: "排队中",
  running: "运行中",
  waiting_input: "等待补充",
  succeeded: "已完成",
  degraded: "已降级",
  failed: "失败",
  cancelled: "已取消",
  paused: "已暂停",
  pausing: "将在检查点暂停",
};

const agentLabels: Record<string, string> = {
  ai_chat: "项目问答",
  project_intelligence: "Project",
  knowledge_lite: "Knowledge",
  engineering_intelligence: "Engineering",
  quality_intelligence: "Quality",
  supplier_intelligence: "Supplier",
  executive_intelligence: "Executive",
};

function statusTone(status: string) {
  if (status === "failed") return "border-destructive/30 bg-destructive/10 text-destructive";
  if (status === "degraded" || status === "waiting_input") return "border-pending/30 bg-pending/10 text-pending";
  if (status === "succeeded") return "border-success/30 bg-success/10 text-success";
  return "border-primary/30 bg-primary/10 text-primary";
}

export function AgentRunsCard({ projectId }: { projectId: string }) {
  return <AgentRunsSession key={projectId} projectId={projectId} />;
}

function subscribeWaitLocation(callback:()=>void) { window.addEventListener("popstate",callback);return ()=>window.removeEventListener("popstate",callback); }
function selectedInputWait() {const value=new URLSearchParams(window.location.search).get("input_wait_id");return value && /^[0-9a-f-]{36}$/.test(value) ? value : null;}

function AgentRunsSession({ projectId }: { projectId: string }) {
  const focusedWait=useSyncExternalStore(subscribeWaitLocation,selectedInputWait,()=>null);
  const [ownerLocked,setOwnerLocked]=useState<string | null>(null);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [controlError, setControlError] = useState<string | null>(null);
  const [runs, setRuns] = useState<AgentRunList | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    let active = true;
    requestAgentRuns(projectId).then(
      (loaded) => {
        if (!active) return;
        setRuns(loaded);
        setState("ready");
      },
      () => {
        if (active) setState("error");
      },
    );
    return () => {
      active = false;
    };
  }, [projectId]);

  useEffect(() => {
    if (ownerLocked || !runs?.items.some((run) => ["queued", "running", "pausing", "paused"].includes(run.status))) return;
    let active = true;
    const timer = setTimeout(() => {
      requestAgentRuns(projectId).then((value) => { if (active) setRuns(value); }, () => {
        if (active) setControlError("运行状态暂不可读，请刷新状态。");
      });
    }, 5000);
    return () => { active = false; clearTimeout(timer); };
  }, [runs, projectId, ownerLocked]);

  async function pause(runId: string, action: "pause" | "resume") {
    setCancelling(runId); setControlError(null);
    try { await controlAgentPause(runId, action); setRuns(await requestAgentRuns(projectId)); }
    catch (error) { setControlError(error instanceof Error ? error.message : "操作失败，请重试"); }
    finally { setCancelling(null); }
  }

  async function refresh() {
    setControlError(null);
    try { setRuns(await requestAgentRuns(projectId)); setState("ready"); }
    catch { setControlError("运行状态暂不可读，请重试。"); }
  }

  async function cancel(runId: string) {
    setCancelling(runId);
    setControlError(null);
    try {
      await cancelAgentRun(runId);
      setRuns(await requestAgentRuns(projectId));
    } catch (error) {
      setControlError(error instanceof Error ? error.message : "暂时无法取消，请重试");
    } finally {
      setCancelling(null);
    }
  }

  return (
    <section aria-label="Agent 运行状态" className="mb-4 overflow-hidden rounded-lg border bg-card">
      <header className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
        <RobotIcon aria-hidden className="size-4 text-primary" />
        <h2 className="font-semibold">Agent 运行状态</h2>
        <button type="button" className="min-h-8 px-2 text-xs text-primary" disabled={!!ownerLocked} onClick={() => void refresh()}>刷新状态</button>
        {state === "ready" && runs !== null ? (
          <Link
            className="ml-auto inline-flex min-h-11 items-center gap-1 text-xs font-medium text-primary sm:min-h-0"
            href="/ai-review"
          >
            本项目待审 Finding {runs.pending_review_findings}
            <ArrowSquareOutIcon aria-hidden />
          </Link>
        ) : null}
      </header>
      {focusedWait && <div className="border-b p-3"><h3 className="mb-2 text-sm font-medium">本次移交的待补充信息</h3><WorkResponsibility key={focusedWait} spaceId={projectId} kind="input_wait" recordId={focusedWait} initiallyOpen disabled={!!ownerLocked && ownerLocked !== focusedWait} onLock={locked => setOwnerLocked(locked ? focusedWait : null)}/></div>}
      {controlError ? <p role="alert" className="px-4 py-2 text-xs text-destructive">{controlError}</p> : null}
      {state === "loading" ? (
        <p className="px-4 py-4 text-xs text-muted-foreground">正在读取运行记录…</p>
      ) : null}
      {state === "error" ? (
        <p className="px-4 py-4 text-xs text-muted-foreground" role="status">
          运行记录暂不可读；这不代表 Agent 不可用。
        </p>
      ) : null}
      {state === "ready" && runs !== null ? (
        runs.items.length === 0 ? (
          <p className="px-4 py-4 text-xs text-muted-foreground" role="status">
            尚无运行记录；队列为空不代表 Agent 已就绪，模型状态见模型治理。
          </p>
        ) : (
          <ol className="divide-y" role="list">
            {runs.items.slice(0, 6).map((run) => (
              <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2" key={run.id}>
                <span className="rounded-lg bg-accent px-2 py-0.5 text-[10px] font-semibold text-accent-foreground">
                  {run.agent_key === "quality_intelligence" && run.event_count === 0
                    ? "报告映射" : (agentLabels[run.agent_key] ?? run.agent_key)}
                </span>
                <span
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-[10px] font-semibold",
                    statusTone(run.status),
                  )}
                >
                  {runStatusLabels[run.status] ?? run.status}
                </span>
                <span className="font-mono text-[11px] text-muted-foreground">
                  {run.event_count === 0 ? "主动请求" : `${run.event_count} 事件`}
                </span>
                {run.status === "waiting_input" && run.input_wait ? (
                  <div className="order-last w-full rounded-lg bg-muted/30 px-3 py-2 text-xs">
                    <p className="font-medium">{run.input_wait.summary}</p>
                    <ul className="mt-1 list-disc space-y-1 pl-4 text-muted-foreground">
                      {run.input_wait.questions.map((question, index) => <li key={index}>{question}</li>)}
                    </ul>
                    <Link className="mt-2 inline-flex min-h-11 items-center gap-1 text-primary"
                      href={`/ai-review?finding=${encodeURIComponent(run.input_wait.finding_id)}`}>
                      查看问题与候选 <ArrowSquareOutIcon aria-hidden />
                    </Link>
                  </div>
                ) : null}
                {run.input_wait && run.input_wait.id !== focusedWait && <div className="order-last w-full"><WorkResponsibility spaceId={projectId} kind="input_wait" recordId={run.input_wait.id} disabled={!!ownerLocked && ownerLocked !== run.input_wait.id} onLock={locked => setOwnerLocked(locked ? run.input_wait!.id : null)}/></div>}
                {run.can_cancel ? (
                  <button type="button" className="min-h-11 rounded-lg border px-3 text-xs disabled:opacity-50"
                    disabled={cancelling !== null || !!ownerLocked} onClick={() => void cancel(run.id)}>
                    {cancelling === run.id ? "正在取消…" : "取消任务"}
                  </button>
                ) : null}
                {run.can_pause ? <button type="button" className="min-h-11 rounded-lg border px-3 text-xs disabled:opacity-50"
                  disabled={cancelling !== null || !!ownerLocked} onClick={() => void pause(run.id, "pause")}>暂停任务</button> : null}
                {run.can_resume ? <button type="button" className="min-h-11 rounded-lg border px-3 text-xs disabled:opacity-50"
                  disabled={cancelling !== null || !!ownerLocked} onClick={() => void pause(run.id, "resume")}>继续执行</button> : null}
                {run.status === "pausing" ? <p className="order-last w-full text-xs text-muted-foreground">当前调用完成并保存结果后暂停。</p> : null}
                <AgentRunProgressPanel projectId={projectId} runId={run.id} />
                {run.error_code && run.status !== "cancelled" ? (
                  <span className="font-mono text-[10px] text-destructive">{run.error_code}</span>
                ) : null}
                <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                  {new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(
                    new Date(run.created_at),
                  )}
                </span>
              </li>
            ))}
          </ol>
        )
      ) : null}
    </section>
  );
}
