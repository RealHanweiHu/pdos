"use client";

import { useEffect, useState } from "react";
import { requestAgentRunProgress } from "./ai-api";
import type { AgentRunProgress } from "./ai-types";

const phases: Record<string, string> = {
  pausing: "等待当前调用保存后暂停", paused: "已暂停，进度和原预算保留",
  debouncing: "正在合并业务事件", queued: "等待执行", running: "正在处理", collecting: "正在收集上下文",
  tool: "工具正在执行", model: "等待模型返回", receipt_unknown: "调用回执未知，等待核对",
  saving: "结果已保存，正在完成后续处理", waiting_input: "等待补充信息", completed: "本次运行已完成",
  stopped: "本次运行已停止", cancelled: "本次运行已取消",
};
const activeStates = new Set(["debouncing", "queued", "running", "waiting_input", "pausing", "paused"]);

export function AgentRunProgressPanel({ projectId, runId, requestProgress }: { runId: string } & (
  { projectId: string; requestProgress?: never } | { projectId?: never; requestProgress: (id: string) => Promise<AgentRunProgress> }
)) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState<AgentRunProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!open) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function read() {
      try {
        const result = requestProgress ? await requestProgress(runId) : await requestAgentRunProgress(projectId, runId);
        if (!active) return;
        setValue(result); setError(null);
        if (activeStates.has(result.status)) timer = setTimeout(() => void read(), 5000);
      } catch {
        if (active) setError("详情暂不可读，请重新查询。");
      }
    }
    void read();
    return () => { active = false; clearTimeout(timer); };
  }, [open, projectId, runId, revision, requestProgress]);
  const budget = value?.budget;
  return <details className="order-last w-full text-xs" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary className="min-h-8 cursor-pointer content-center text-primary">查看运行详情</summary>
    {open && <div className="space-y-2 rounded-lg bg-muted/30 p-3">
      {error && <p role="alert" className="text-destructive">{error}{value ? " 以下为上次查询记录。" : ""}</p>}
      {!value && !error && <p role="status">正在读取运行详情…</p>}
      {value && <>
        <p className="font-medium" role="status">{phases[value.phase] ?? "正在处理"}</p>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
          <dt>已保存工具步骤</dt><dd>{value.saved_tool_steps}</dd>
          <dt>工具执行记录</dt><dd>{value.tool_dispatches}</dd>
          <dt>观察记录</dt><dd>{value.observations}</dd>
          <dt>模型调用回执</dt><dd>{value.model_receipts}</dd>
          <dt>已保存结果</dt><dd>{value.saved_results}</dd>
        </dl>
        {value.last_tool && <p>最近执行工具：<span className="font-mono">{value.last_tool}</span></p>}
        {budget ? <>
          <p>累计 token：已计入 {budget.charged_tokens.toLocaleString()} · 预留 {budget.held_tokens.toLocaleString()} · 剩余 {budget.remaining_tokens.toLocaleString()} / {budget.token_limit.toLocaleString()}</p>
          <p>累计活动时间：{budget.active_seconds === null ? "历史未知" : `${budget.active_seconds.toFixed(1)} 秒`} / {budget.active_limit_seconds} 秒；等待补充期间不计活动时间。</p>
          <p>请求截止：{new Date(budget.absolute_deadline).toLocaleString("zh-CN")}</p>
          <p>模型已知费用：${(budget.priced_model_cost_microusd / 1_000_000).toFixed(6)}{budget.model_cost_complete ? "" : " · 费用记录尚不完整"}</p>
          {budget.unresolved_calls > 0 && <p>尚有 {budget.unresolved_calls} 次调用待返回或核对，预留额度仍保留。</p>}
          <p className="text-muted-foreground">用量累计包含本请求的关联运行。</p>
        </> : <p>本次运行没有完整预算记录，历史用量未知。</p>}
        {value.stop_code && <p>停止原因：<span className="font-mono">{value.stop_code}</span></p>}
        <p className="text-muted-foreground">运行完成与建议应用、业务完成分别记录。</p>
        <p className="text-muted-foreground">查询时间：{new Date(value.as_of).toLocaleString("zh-CN")}</p>
      </>}
      <button type="button" className="min-h-8 rounded-lg border px-3" onClick={() => setRevision((n) => n + 1)}>重新查询</button>
    </div>}
  </details>;
}
