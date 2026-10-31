"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { CaretDown, Sparkle, Wrench } from "@phosphor-icons/react";
import { contextIssueLabel, conversationProgress, mergeProcessSteps, processAge, processStepLabel } from "@/lib/run-process";
import type { ProcessStep, RunProcessData } from "@/lib/run-process";
import styles from "./run-progress.module.css";
import { ContextMetricsDetails } from "./context-metrics";

type Api = <T>(path: string, body?: unknown) => Promise<T>;
export function RunProcess({ value, api, root, presentation = "record", onUnavailable }: { value?: RunProcessData; api: Api; root: string; presentation?: "record" | "conversation"; onUnavailable?: () => void }) {
  const [older, setOlder] = useState<ProcessStep[]>([]);
  const [cursor, setCursor] = useState<number | null | undefined>(undefined);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [hiddenSnapshot, setHiddenSnapshot] = useState<string | null>(null);
  const [extra, setExtra] = useState<Partial<Pick<RunProcessData,"sources" | "receipts" | "next_source_cursor" | "next_receipt_cursor">>>({});
  const [clock, setClock] = useState({ snapshot: "", seconds: 0 });
  const [expanded, setExpanded] = useState<boolean | null>(null);
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
    } catch (failure) { if (own === generation.current) { setError(failure instanceof Error ? failure.message : "早期记录暂不可读。"); if ([401, 403, 404].includes((failure as {status?:number}).status ?? 0)) { setOlder([]); setExtra({}); setCursor(undefined); setHiddenSnapshot(value.observed_at); onUnavailable?.(); } } }
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
    } catch (failure) { if (own === generation.current) { setError(failure instanceof Error ? failure.message : "记录暂不可读。"); if ([401, 403, 404].includes((failure as {status?:number}).status ?? 0)) { setExtra({}); setOlder([]); setCursor(undefined); setHiddenSnapshot(value.observed_at); onUnavailable?.(); } } }
    finally { if (own===generation.current) { lock.current=false;setBusy(false); } }
  };
  const sources = extra.sources ?? value.sources, receipts = extra.receipts ?? value.receipts;
  const sourceCursor = extra.next_source_cursor === undefined ? value.next_source_cursor : extra.next_source_cursor;
  const receiptCursor = extra.next_receipt_cursor === undefined ? value.next_receipt_cursor : extra.next_receipt_cursor;
  if (hiddenSnapshot === value.observed_at) return <section aria-label="小Pai处理过程" className="rounded-lg border p-3"><p role="alert" className="text-sm">当前无权读取处理过程。请核对当前状态，原记录不会因此重发。</p></section>;
  if (presentation === "conversation") {
    const open = expanded ?? active;
    const entries = conversationProgress(steps);
    const state = value.reverted ? "结果已撤回" : ({ queued: "等待处理", running: "正在处理", waiting_input: "等待继续", completed: "处理过程", partial: "处理过程 · 部分完成", failed: "处理过程 · 未完成", cancelled: "处理过程 · 已停止" } as Record<string, string>)[value.status] ?? "处理过程";
    return <details className={styles.progress} open={open} aria-label="小Pai处理进展">
      <summary onClick={event => { event.preventDefault(); setExpanded(!open); }}><Sparkle size={13} aria-hidden="true" /><span>{state}</span><small>{processAge(value, clock.snapshot === value.observed_at ? clock.seconds : 0)}</small><CaretDown size={11} aria-hidden="true" /></summary>
      <div className={styles.transcript}>
        {error && <p role="alert">{error}</p>}
        {before !== null && <button className={styles.more} type="button" disabled={busy} onClick={() => void more()}>{busy ? "正在读取…" : "查看更早过程"}</button>}
        <ol>{entries.map(entry => <li key={entry.id} className={entry.kind === "tools" ? styles.tools : styles.narration}>
          {entry.kind === "summary" ? <p>{entry.text}</p> : <><Wrench size={14} aria-hidden="true" /><div>{entry.actions.map(action => <span key={action.id}>{action.text}<small>{action.state === "loaded" ? "已加载" : action.state === "returned" ? "已返回" : value.status === "running" ? "进行中" : value.status === "waiting_input" ? "等待核对" : "未记录返回"}</small></span>)}</div></>}
        </li>)}</ol>
        {!entries.length && <p className={styles.empty}>尚无已登记的处理步骤。</p>}
        <ContextMetricsDetails steps={steps} />
      </div>
    </details>;
  }
  const title = value.reverted ? "原草稿结果已撤回" : value.status === "failed" ? "执行未完成，记录已保留" : value.status === "cancelled" ? "后续执行已停止" : value.status === "waiting_input" ? value.error_code === "EXTERNAL_OUTCOME_UNKNOWN" ? "原调用结果待核对" : value.error_code ? "等待执行条件恢复" : "等待你的答复或确认" : latest ? processStepLabel(latest) : "已保存，等待执行服务";
  return <section aria-label="小Pai处理过程" className="rounded-lg border border-border p-3 space-y-2">
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm"><span className="font-medium">处理过程</span><span className="subtle">{value.ended_at ? "受理至结束" : active ? "从受理起（含等待）" : ""} {processAge(value, clock.snapshot === value.observed_at ? clock.seconds : 0)}</span></div>
    <p role="status" className="text-sm break-words">{title}</p>
    <p className="subtle">已保存 {value.call_counts.completed} 次处理 · 已提交 {value.business_receipt_count} 条动作{value.call_counts.pending > 0 ? ` · ${value.call_counts.pending} 次处理中或待核实` : ""}</p>
    <ContextMetricsDetails steps={steps} />
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
