"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { restoreReconciliation } from "@/lib/run-reconciliation";
import type { ReconciliationReading, ReconciliationRecord, ReconciliationRequest } from "@/lib/run-reconciliation";

type Api = <T>(path: string, body?: unknown) => Promise<T>;
type Run = { run_id: string; status: string; cancel_epoch: number; error_code?: string | null; reconciliation?: unknown; result?: { result?: Record<string, unknown> } };
const states: Record<string, string> = { started: "原调用未结束", unknown: "原结果待核实", completed: "已完成", failed: "未能核实，已结束等待", reconciled: "已核对" };

export function RunReconciliation({ api, root, run, onSettled }: { api: Api; root: string; run: Run; onSettled: () => Promise<void> }) {
  const [reading, setReading] = useState<ReconciliationReading | null>(null);
  const [pending, setPending] = useState<ReconciliationRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const lock = useRef(false);
  const generation = useRef(0);
  const visible = run.error_code === "EXTERNAL_OUTCOME_UNKNOWN" || !!run.reconciliation;
  const storageKey = `pdos:run-reconciliation:${root}:${run.run_id}`;
  const endpoint = `${root}/${run.run_id}/reconciliation`;
  const remember = useCallback((value: ReconciliationRequest | null) => {
    setPending(value);
    try { if (value) localStorage.setItem(storageKey, JSON.stringify(value)); else localStorage.removeItem(storageKey); } catch { /* The exact request remains in memory. */ }
  }, [storageKey]);
  const load = useCallback(async () => {
    const own = ++generation.current;
    const value = await api<ReconciliationReading>(endpoint);
    if (own !== generation.current) return value;
    if (value.run_id !== run.run_id) throw new Error("核对结果与当前运行不一致。");
    setReading(value);
    if (value.completed) remember(null);
    return value;
  }, [api, endpoint, run.run_id, remember]);
  useEffect(() => {
    if (!visible) return;
    let active = true;
    const counter = generation;
    void Promise.resolve().then(() => {
      if (!active) return;
      try { const value = restoreReconciliation(JSON.parse(localStorage.getItem(storageKey) ?? "null"), run.run_id, root); setPending(value); } catch { setPending(null); }
      return load();
    }).catch(failure => { if (active) setError(failure.message); });
    return () => { active = false; counter.current++; };
  }, [visible, storageKey, root, run.run_id, run.status, run.cancel_epoch, load]);

  const perform = async (original?: ReconciliationRequest) => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try {
      const latest = await load();
      if (latest.completed) { remember(null); await onSettled(); return; }
      if (!latest.required || !latest.can_finalize) throw new Error("当前没有可由本人办理的待核对运行，请刷新状态。");
      const request = original ?? { run_id: run.run_id, root, expected_cancel_epoch: latest.cancel_epoch };
      if (request.expected_cancel_epoch !== latest.cancel_epoch) throw new Error("运行版本已变化，请核对当前状态后重新办理。");
      remember(request);
      const result = await api<{ run_id: string; status: string; reconciliation: ReconciliationRecord | null; workflow_cleanup_pending?: boolean }>(endpoint, { expected_cancel_epoch: request.expected_cancel_epoch });
      if (result.run_id !== run.run_id || !result.reconciliation) throw new Error("未取得匹配的核对记录，请保留原请求再核对。");
      remember(null);
      setNotice(result.workflow_cleanup_pending ? "原工作已结束等待，已做结果保留；执行服务恢复后清理后台等待。" : "原工作已结束等待，已做结果保留。原目标尚未全部完成，可调整目标后另开新工作。");
      await load(); await onSettled();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "原核对结果待确认，请保留同一请求。"); }
    finally { lock.current = false; setBusy(false); }
  };
  const more = async (kind: "calls" | "receipts", cursor: string) => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try {
      const value = await api<ReconciliationReading>(`${endpoint}?${kind === "calls" ? "call_cursor" : "receipt_cursor"}=${encodeURIComponent(cursor)}`);
      if (value.run_id !== run.run_id) throw new Error("分页结果与当前运行不一致。");
      setReading(old => !old ? value : { ...value,
        calls: kind === "calls" ? [...old.calls, ...value.calls.filter(row => !old.calls.some(prior => prior.id === row.id))] : old.calls,
        receipts: kind === "receipts" ? [...old.receipts, ...value.receipts.filter(row => !old.receipts.some(prior => prior.id === row.id))] : old.receipts,
        next_call_cursor: kind === "calls" ? value.next_call_cursor : old.next_call_cursor,
        next_receipt_cursor: kind === "receipts" ? value.next_receipt_cursor : old.next_receipt_cursor,
      });
    } catch (failure) { setError(failure instanceof Error ? failure.message : "核对记录暂不可读。"); }
    finally { lock.current = false; setBusy(false); }
  };
  if (!visible) return null;
  return <section className="rounded-lg border border-border p-3 space-y-3" aria-label="原运行结果核对">
    <h4 className="font-medium">原运行结果核对</h4>
    <p className="subtle">先核对已提交动作，再结束不确定调用的等待。此处不会重发模型、领域动作或外部发送。</p>
    {error && <p role="alert" className="break-words text-sm">{error}</p>}
    {notice && <p role="status" className="text-sm">{notice}</p>}
    {pending && <div className="space-y-2"><p className="text-sm">原结束请求的结果待核对。刷新只读取原记录，不自动再次提交。</p><Button variant="outline" disabled={busy} onClick={() => void perform(pending)}>核对并重试原结束请求</Button></div>}
    {reading && <>
      <p className="text-sm">已提交动作 {reading.counts.business_receipts} 条 · 原调用 {reading.counts.calls} 次 · 待核实 {reading.counts.pending_calls} 次</p>
      {reading.required && <p className="subtle">{reading.automatic_after ? `最早 ${new Date(reading.automatic_after).toLocaleString()} 由执行服务自动核对。` : "等待执行服务核对；管理员也可提前办理。"}服务不可用时保留原记录，不盲目重发。</p>}
      {reading.estimated_micro_usd > 0 && <p className="subtle">原费用按预留上界保留估算，尚无真实用量凭证；没有把未知调用当成免费。</p>}
      {reading.completed && <div className="text-sm space-y-2"><p>已于 {new Date(reading.completed.closed_at).toLocaleString()} {reading.completed.mode === "automatic" ? "自动" : "由管理员"}核对，保留 {reading.completed.business_receipt_count} 条已提交动作。</p>{reading.completed.external_effect_unknown && <p>外部发送的实际结果仍不确定，请先向对方核实，避免重复发送。</p>}<p className="subtle break-all">核对记录 {reading.completed.event_id}</p></div>}
      {reading.can_finalize && !pending && <Button variant="outline" disabled={busy} onClick={() => void perform()}>保留已做结果，结束本次等待</Button>}
      <Button variant="outline" size="sm" disabled={busy} onClick={() => { setError(""); void load().catch(failure => setError(failure.message)); }}>读取原核对记录</Button>
      <details><summary className="cursor-pointer text-sm">查看调用与实际提交记录</summary><ul className="mt-3 space-y-2">{reading.calls.map(call => <li key={call.id} className="text-sm break-words">{call.tool} · {states[call.state] ?? call.state}<span className="block subtle break-all">{call.id}</span></li>)}</ul>{reading.next_call_cursor && <Button size="sm" variant="outline" disabled={busy} onClick={() => void more("calls", reading.next_call_cursor!)}>更多原调用</Button>}<ul className="mt-3 space-y-2">{reading.receipts.map(receipt => <li key={receipt.id} className="text-sm break-words">{receipt.operation} · 第 {receipt.subject_revision} 版<span className="block subtle break-all">回执 {receipt.id}</span></li>)}</ul>{reading.next_receipt_cursor && <Button size="sm" variant="outline" disabled={busy} onClick={() => void more("receipts", reading.next_receipt_cursor!)}>更多提交回执</Button>}</details>
    </>}
  </section>;
}
