"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { contextIssueLabel, mergeProcessSteps, processAge, processStepLabel } from "@/lib/run-process";
import type { ProcessStep, RunProcessData } from "@/lib/run-process";

type Api = <T>(path: string, body?: unknown) => Promise<T>;
export function RunProcess({ value, api, root }: { value?: RunProcessData; api: Api; root: string }) {
  const [older, setOlder] = useState<ProcessStep[]>([]);
  const [cursor, setCursor] = useState<number | null | undefined>(undefined);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [hiddenSnapshot, setHiddenSnapshot] = useState<string | null>(null);
  const [extra, setExtra] = useState<Partial<Pick<RunProcessData,"sources" | "receipts" | "next_source_cursor" | "next_receipt_cursor">>>({});
  const [clock, setClock] = useState({ snapshot: "", seconds: 0 });
  const generation = useRef(0);
  const lock = useRef(false);
  const active = !!value && !["completed", "partial", "failed", "cancelled"].includes(value.status) && !value.reverted;
  useEffect(() => {
    if (!value || !active) return;
    const snapshot = value.observed_at;
    const started = Date.now();
    const timer = setInterval(() => setClock({ snapshot, seconds: Math.max(0, (Date.now()-started)/1000) }), 1000);
    return () => clearInterval(timer);
  }, [active, value?.observed_at, value]);
  useEffect(() => { const version = generation; return () => { version.current++; }; }, []);
  if (!value) return null;
  const steps = mergeProcessSteps(older, value.steps);
  const before = cursor === undefined ? value.next_before : cursor;
  const more = async () => {
    if (lock.current || before === null) return;
    lock.current = true; setBusy(true); setError("");
    const own = generation.current;
    try {
      const next = await api<RunProcessData>(`${root}/${value.run_id}/process?before=${before}`);
      if (own !== generation.current) return;
      if (next.run_id !== value.run_id) throw new Error("过程记录与当前工作不一致。");
      setOlder(old => mergeProcessSteps(next.steps, mergeProcessSteps(old, value.steps)));
      setCursor(next.next_before);
    } catch (failure) { if (own === generation.current) { setError(failure instanceof Error ? failure.message : "早期记录暂不可读。"); if ((failure as {status?:number}).status === 403) { setOlder([]); setHiddenSnapshot(value.observed_at); } } }
    finally { if (own === generation.current) { lock.current=false; setBusy(false); } }
  };
  const latest = value.steps.at(-1);
  const moreRecords = async (kind:"sources"|"receipts") => {
    const key = kind === "sources" ? "next_source_cursor" : "next_receipt_cursor";
    const nextCursor = extra[key] === undefined ? value[key] : extra[key];
    if (lock.current || !nextCursor) return;
    const own = generation.current;
    lock.current=true; setBusy(true); setError("");
    try {
      const next = await api<RunProcessData>(`${root}/${value.run_id}/process?${kind === "sources" ? "source_cursor" : "receipt_cursor"}=${nextCursor}`);
      if (own !== generation.current) return;
      if (next.run_id !== value.run_id) throw new Error("过程记录与当前工作不一致。");
      setExtra(old => ({...old, [kind]:[...new Map([...(old[kind] ?? value[kind]), ...next[kind]].map(row=>[row.id,row])).values()], [key]:next[key]}));
    } catch (failure) { if (own === generation.current) { setError(failure instanceof Error ? failure.message : "记录暂不可读。"); if ((failure as {status?:number}).status===403) { setExtra({}); setOlder([]); setHiddenSnapshot(value.observed_at); } } }
    finally { if (own===generation.current) { lock.current=false;setBusy(false); } }
  };
  const sources = extra.sources ?? value.sources, receipts = extra.receipts ?? value.receipts;
  const sourceCursor = extra.next_source_cursor === undefined ? value.next_source_cursor : extra.next_source_cursor;
  const receiptCursor = extra.next_receipt_cursor === undefined ? value.next_receipt_cursor : extra.next_receipt_cursor;
  if (hiddenSnapshot === value.observed_at) return <section aria-label="小Pai处理过程" className="rounded-lg border p-3"><p role="alert" className="text-sm">当前无权读取处理过程。请核对当前状态，原记录不会因此重发。</p></section>;
  const title = value.reverted ? "原草稿结果已撤回" : value.status === "failed" ? "执行未完成，记录已保留" : value.status === "cancelled" ? "后续执行已停止" : value.status === "waiting_input" ? value.error_code === "EXTERNAL_OUTCOME_UNKNOWN" ? "原调用结果待核对" : value.error_code ? "等待执行条件恢复" : "等待你的答复或确认" : latest ? processStepLabel(latest) : "已保存，等待执行服务";
  return <section aria-label="小Pai处理过程" className="rounded-lg border border-border p-3 space-y-2">
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm"><span className="font-medium">处理过程</span><span className="subtle">{value.ended_at ? "受理至结束" : active ? "从受理起（含等待）" : ""} {processAge(value, clock.snapshot === value.observed_at ? clock.seconds : 0)}</span></div>
    <p role="status" className="text-sm break-words">{title}</p>
    <p className="subtle">已保存 {value.call_counts.completed} 次处理 · 已提交 {value.business_receipt_count} 条动作{value.call_counts.pending > 0 ? ` · ${value.call_counts.pending} 次处理中或待核实` : ""}</p>
    <details><summary className="cursor-pointer text-sm">查看步骤、依据与提交记录</summary>
      <div className="mt-3 space-y-3 text-sm">
        <p className="subtle">以下为实际行动记录；步骤返回不等于业务批准。绑定依据 {value.source_count} 份，人员等待计入总历时。</p>
        {error && <p role="alert">{error}</p>}
        {before !== null && <Button size="sm" variant="outline" disabled={busy} onClick={() => void more()}>{busy ? "正在读取…" : "读取更早步骤"}</Button>}
        {!steps.length && <p className="subtle">尚无已登记的处理步骤。</p>}
        {sources.length > 0 && <div className="space-y-2"><p className="font-medium">本次绑定依据</p>{sources.map(source => <p key={source.id} className="break-words">{source.title} · 第 {source.bound_revision} 版{source.current_revision !== source.bound_revision ? "（当前版本已变化）" : ""}</p>)}{sourceCursor && <Button size="sm" variant="outline" disabled={busy} onClick={()=>void moreRecords("sources")}>更多绑定依据</Button>}</div>}
        <ol className="space-y-3">{steps.map(step => <li key={step.id} className="space-y-1 break-words"><p>{processStepLabel(step)}</p>{[...(step.context_omitted ?? []), ...(step.context_issues ?? [])].map((issue, index) => <p key={index} className="subtle">{contextIssueLabel(issue)}</p>)}<time className="subtle" dateTime={step.at}>{new Date(step.at).toLocaleString()}</time></li>)}</ol>
        {receipts.length > 0 && <div className="space-y-2"><p className="font-medium">实际提交记录</p>{receipts.map(receipt => <p key={receipt.id} className="subtle break-all">{receipt.operation} · 第 {receipt.subject_revision} 版<br/>回执 {receipt.id}</p>)}{receiptCursor && <Button size="sm" variant="outline" disabled={busy} onClick={()=>void moreRecords("receipts")}>更多提交记录</Button>}</div>}
        <p className="subtle">运行中按实际记录更新；关闭或刷新页面不启动新的模型调用。</p>
      </div>
    </details>
  </section>;
}
