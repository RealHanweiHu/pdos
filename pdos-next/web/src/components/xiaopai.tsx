"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Sparkle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import { proofClockCurrent } from "@/lib/proof-clock";
import { RunFeedback } from "@/components/pai/run-feedback";
import { RunProcess } from "@/components/pai/run-process";
import type { RunProcessData } from "@/lib/run-process";
import { RunReconciliation } from "@/components/pai/run-reconciliation";
import { reconciliationNeeded } from "@/lib/run-reconciliation";
import { RunCandidates } from "@/components/pai/run-candidates";
import { ResearchResult } from "@/components/pai/research-result";
import { restoreRunStart } from "@/lib/run-start-intent";

type Source = { id: string; title: string; revision: number; status: string };
type Question = { id: string; question: string; why: string; options: { value: string; label: string }[]; allow_free_text: boolean };
type Run = { process?: RunProcessData; reconciliation?: unknown; run_id: string; product_id: string | null; proposal_id?: string | null; cancel_epoch: number; status: string; error_code: string | null; reverted: boolean; result: { summary?: string; unfinished?: string[]; result?: Record<string, unknown> } };
type History = { items: (Run & { goal: string; created_at: string; product_id: string | null })[]; next_cursor: string | null };
type Candidate = { command: Record<string, unknown> & { payload: { statement: string; quote: string; prepared_event_id: string } }; event_id: string };
type Event = { id?: string; sequence: number; event: { type: string; questions?: Question[]; status?: string; command?: Candidate["command"]; prepared_event_id?: string } };
type Pending = { path: string; body: unknown };
const labels: Record<string, string> = { queued: "已保存，等待执行", running: "正在执行", waiting_input: "等待你的答复", completed: "已完成", partial: "已形成部分结果", cancelled: "已取消后续执行", failed: "执行未完成" };

/** Runs and events are server facts. Reading or reopening this panel never starts inference. */
export function Xiaopai({ api, productId, sources, composeOpen, onComposeChange, initialRunId, categoryId, principalId, proposalId }: {
  api: WorkspaceTransport; productId: string; sources: Source[]; composeOpen: boolean; onComposeChange: (open: boolean) => void;
  initialRunId?: string; proposalId?: string;
  categoryId: string; principalId: string;
}) {
  const historyPath = `v1/agent-runs?page_size=50${proposalId ? `&proposal_id=${proposalId}` : ""}`;
  const [goal, setGoal] = useState("");
  const [useProduct, setUseProduct] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [history, setHistory] = useState<History>({ items: [], next_cursor: null });
  const [run, setRun] = useState<Run | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [eventSequence, setEventSequence] = useState(0);
  const [adoption, setAdoption] = useState<{ command: unknown; expires_at: string; review: { effect: string } } | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [revert, setRevert] = useState<{ command: unknown; expires_at: string; review: { effect: string; receipts: { id: string; operation: string }[] } } | null>(null);
  const generation = useRef(0);
  const writeLock = useRef(false);
  const request = useRef<Pending | null>(null);
  const current = useRef<string | null>(null);
  const startStorageKey = `pdos-next:run-start:${principalId}:${categoryId}:${proposalId ?? "category"}`;

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      try {
        const original = restoreRunStart(JSON.parse(localStorage.getItem(startStorageKey) ?? "null"), proposalId);
        if (original) { request.current = original; setPending(original); }
      } catch { /* Optional local recovery; server history remains authoritative. */ }
    });
    return () => { active = false; };
  }, [startStorageKey, proposalId]);

  useEffect(() => () => { generation.current++; }, []);
  const readRun = useCallback(async (id: string) => {
    const own = ++generation.current;
    current.current = id;
    try {
    const value = await api<Run>(`v1/agent-runs/${id}`);
    if (own !== generation.current) return;
    if (proposalId && value.proposal_id !== proposalId) throw new Error("运行不属于当前提案，请刷新本提案的运行历史。");
    const events: Event[] = [];
    let after = 0;
    for (;;) {
      const page = await api<{ items: Event[]; next_cursor: number }>(`v1/agent-runs/${id}/events?after=${after}&page_size=200`);
      if (own !== generation.current) return;
      events.push(...page.items);
      if (page.items.length < 200 || page.next_cursor <= after) break;
      after = page.next_cursor;
    }
    if (own !== generation.current) return;
    setRun(value);
    setEventSequence(events.at(-1)?.sequence ?? 0);
    const adopted = new Set(events.filter(item => item.event.type === "claim_candidate_adopted").map(item => item.event.prepared_event_id));
    setCandidates(value.reconciliation ? [] : events.filter(item => item.event.type === "claim_candidate" && item.event.command && !adopted.has(item.event.command.payload.prepared_event_id)).map(item => ({ command: item.event.command!, event_id: item.event.command!.payload.prepared_event_id })));
    setAdoption(null);
    setRevert(null);
    setQuestions(value.status === "waiting_input" && !value.reverted && !reconciliationNeeded(value) ? [...events].reverse().find(item => item.event.type === "needs_input")?.event.questions ?? [] : []);
    } catch (failure) { if (own === generation.current) setRun(prior => prior?.run_id === id ? { ...prior, process: undefined } : prior); throw failure; }
  }, [api, proposalId]);
  const refreshHistory = useCallback(async (cursor?: string) => {
    const next = await api<History>(`${historyPath}${cursor ? `&cursor=${cursor}` : ""}`);
    setHistory(old => cursor ? { ...next, items: [...old.items, ...next.items.filter(row => !old.items.some(item => item.run_id === row.run_id))] } : next);
  }, [api, historyPath]);
  useEffect(() => {
    let active = true;
    void api<History>(historyPath).then(value => { if (active) setHistory(value); }).catch(failure => { if (active) setError(failure.message); });
    return () => { active = false; };
  }, [api, historyPath]);
  useEffect(() => {
    if (!initialRunId) return;
    let active = true;
    void readRun(initialRunId).catch(failure => { if (active) setError(failure.message); });
    return () => { active = false; };
  }, [initialRunId, readRun]);
  useEffect(() => {
    if (!run || run.reverted || !["queued", "running"].includes(run.status) && !reconciliationNeeded(run)) return;
    const timer = setInterval(() => {
      if (!writeLock.current) void readRun(run.run_id).catch(failure => setError(failure.message));
    }, 3000);
    return () => clearInterval(timer);
  }, [run, readRun]);

  async function send(value: Pending) {
    if (writeLock.current) return;
    writeLock.current = true;
    request.current = value; setPending(value); setBusy(true); setError(""); setNotice("");
    generation.current++;
    if (value.path === "v1/agent-runs") {
      try { localStorage.setItem(startStorageKey, JSON.stringify(value)); } catch { /* In-memory original remains available. */ }
    }
    try {
      const result = await api<{ run_id: string; execution_state?: string; workflow_cancel_pending?: boolean }>(value.path, value.body);
      if (value.path === "v1/agent-runs" && !result.run_id) throw new Error("运行受理结果尚未核对，请重试原请求。");
      request.current = null; setPending(null);
      if (value.path === "v1/agent-runs") { try { localStorage.removeItem(startStorageKey); } catch { /* Optional storage. */ } }
      setNotice(result.execution_state === "durable_runtime_unavailable" ? "运行已保存，持久执行服务暂不可用。恢复后会继续派送。" : result.workflow_cancel_pending ? "取消已记录，正在通知执行服务。" : "请求已保存，可以查看实际运行状态。");
      if (value.path === "v1/agent-runs") { setGoal(""); setSelected([]); onComposeChange(false); }
      setAnswers({});
      await readRun(result.run_id ?? current.current!);
      await refreshHistory();
    } catch (failure) {
      const status = (failure as { status?: number }).status;
      if (value.path === "v1/agent-runs" && status && status >= 400 && status < 500 && status !== 408 && status !== 429) {
        request.current = null; setPending(null);
        try { localStorage.removeItem(startStorageKey); } catch { /* Rejected requests are never retried automatically. */ }
      }
      setError(failure instanceof Error ? failure.message : "服务暂不可用。");
      // A completed POST is not retried when only the subsequent read failed.
    } finally { writeLock.current = false; setBusy(false); }
  }
  async function read(action: () => Promise<unknown>) {
    if (writeLock.current) return;
    setBusy(true); setError("");
    try { await action(); } catch (failure) { setError((failure as Error).message); } finally { setBusy(false); }
  }

  return <section className="panel space-y-5" aria-label="小Pai 运行">
    <div className="flex items-center gap-2"><Sparkle className="text-primary" aria-hidden="true" /><h2 className="font-semibold">小Pai</h2><Button className="ml-auto" size="sm" variant="outline" disabled={busy} onClick={() => void read(() => refreshHistory())}>刷新运行</Button></div>
    <p className="subtle">{proposalId ? "在当前提案内委派起草、抽取或查漏。资料范围由服务器核对；G0 仍由具名评审人决定。" : "在当前品类委派工作。结果、待答问题和未完成事项会保留，关闭页面后仍可回来查看。"}</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {pending && <div className="rounded-lg border p-3"><p>原请求仍待核对，输入暂时保留。</p><Button variant="outline" className="mt-3" disabled={busy} onClick={() => { if (request.current) void send(request.current); }}>重试原请求</Button></div>}
    <details open={composeOpen} onToggle={event => onComposeChange(event.currentTarget.open)}>
      <summary className="cursor-pointer font-medium">新建委派</summary>
      <form className="mt-4" onSubmit={event => {
        event.preventDefault();
        if (useProduct && selected.some(id => !sources.some(source => source.id === id && source.status === "active"))) { setError("型号或来源已变化，请重新选择本次工作依据。"); return; }
        void send({ path: "v1/agent-runs", body: { goal, idempotency_key: crypto.randomUUID(), product_id: useProduct && productId ? productId : null, ...(proposalId ? { proposal_id: proposalId } : {}), sources: selected.map(id => { const source = sources.find(item => item.id === id)!; return { artifact_id: source.id, expected_revision: source.revision }; }) } });
      }}>
        <fieldset disabled={busy || !!pending}>
          <label>希望得到什么结果<textarea required minLength={3} maxLength={8000} rows={4} value={goal} onChange={event => setGoal(event.target.value)} placeholder="说明目标、希望形成的结果和需要核对的依据" /></label>
          {productId && <label className="flex items-center gap-2"><input type="checkbox" checked={useProduct} onChange={event => { setUseProduct(event.target.checked); if (!event.target.checked) setSelected([]); }} />关联当前型号</label>}
          {useProduct && productId && <fieldset className="mb-4"><legend className="mb-2 text-sm">选择本次工作依据</legend>{sources.filter(source => source.status === "active").map(source => <label key={source.id} className="flex items-center gap-2"><input type="checkbox" checked={selected.includes(source.id)} onChange={event => setSelected(old => event.target.checked ? [...old, source.id] : old.filter(id => id !== source.id))} />{source.title} · 版本 {source.revision}</label>)}</fieldset>}
          <Button>保存并开始</Button>
        </fieldset>
      </form>
    </details>
    {run && <div className="space-y-4 border-t pt-4">
      <div className="flex flex-wrap items-center gap-3"><h3 className="font-medium">{run.reverted ? "已整次撤回" : reconciliationNeeded(run) ? "原调用结果待核对" : labels[run.status] ?? run.status}</h3><Button size="sm" variant="outline" disabled={busy} onClick={() => void read(() => readRun(run.run_id))}>核对当前状态</Button></div>
      {run.result?.summary && <p className="whitespace-pre-wrap break-words">{run.result.summary}</p>}
      <ResearchResult value={run.result?.result?.research} />
      {run.error_code && <p role="status">执行未完成 · {run.error_code}</p>}
      {run.process && <RunProcess key={`process:${run.run_id}`} value={run.process} api={api} root="v1/agent-runs" />}
      <RunFeedback key={`feedback:${run.run_id}`} api={api} root="v1/agent-runs" runId={run.run_id} />
      <RunReconciliation key={run.run_id} api={api} root="v1/agent-runs" run={run} onSettled={() => readRun(run.run_id)} />
      {!!run.result?.unfinished?.length && <div><h4 className="font-medium">未完成事项</h4><ul className="mt-2 list-disc pl-5">{run.result.unfinished.map((item, i) => <li key={i}>{item}</li>)}</ul></div>}
      {run.result?.result && Object.keys(run.result.result).length > 0 && <details><summary className="cursor-pointer">查看实际结果与回执</summary><pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words text-sm">{JSON.stringify(run.result.result, null, 2)}</pre></details>}
      {!run.reverted && run.status !== "cancelled" && candidates.map(candidate => <section key={candidate.event_id} className="rounded-lg border p-3 space-y-3"><h3 className="font-medium">待你确认的来源事实</h3><p>{candidate.command.payload.statement}</p><blockquote className="text-sm text-muted-foreground">{candidate.command.payload.quote}</blockquote><Button variant="outline" disabled={busy || !!pending} onClick={() => void read(async () => { setAdoption(await api("v1/commands/preview", candidate.command)); })}>核对并预览此事实</Button></section>)}
      {adoption && <section className="rounded-lg border p-3 space-y-3"><p>{adoption.review.effect}</p><Button disabled={busy || !!pending || !proofClockCurrent("T1", adoption.expires_at)} onClick={() => void send({ path: "v1/commands", body: adoption.command })}>确认登记此事实</Button></section>}
      {!run.reconciliation && <RunCandidates api={api} categoryId={categoryId} principalId={principalId} runId={run.run_id} eventSequence={eventSequence} disabled={busy || !!pending} />}
      {questions.length > 0 && <form onSubmit={event => { event.preventDefault(); void send({ path: `v1/agent-runs/${run.run_id}/answers`, body: { answers, idempotency_key: crypto.randomUUID() } }); }}><fieldset disabled={busy || !!pending}>
        {questions.map(question => <div key={question.id} className="mb-4"><label htmlFor={`pai-${question.id}`}>{question.question}</label><p className="subtle mb-2">{question.why}</p>{question.allow_free_text ? <><input id={`pai-${question.id}`} list={`pai-options-${question.id}`} required value={answers[question.id] ?? ""} onChange={event => setAnswers(old => ({ ...old, [question.id]: event.target.value }))} /><datalist id={`pai-options-${question.id}`}>{question.options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</datalist></> : <select id={`pai-${question.id}`} required value={answers[question.id] ?? ""} onChange={event => setAnswers(old => ({ ...old, [question.id]: event.target.value }))}><option value="">请选择</option>{question.options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select>}</div>)}
        <Button>提交答复并继续</Button>
      </fieldset></form>}
      {!run.reverted && ["queued", "running", "waiting_input"].includes(run.status) && <details><summary className="cursor-pointer text-sm">取消此次运行</summary><p className="subtle my-3">停止后续动作，已经形成的结果和回执保留。</p><Button variant="outline" disabled={busy || !!pending} onClick={() => void send({ path: `v1/agent-runs/${run.run_id}/cancel`, body: {} })}>确认取消后续执行</Button></details>}
      {!run.reverted && <details><summary className="cursor-pointer text-sm">整次撤回草稿结果</summary><p className="subtle my-3">先核对全部结果及后续引用，再一次确认撤回。</p><Button variant="outline" disabled={busy || !!pending} onClick={() => void read(async () => {
        setRevert(await api("v1/commands/preview", { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation: "ai.run.revert", product_id: run.product_id, expected_revision: run.cancel_epoch + 1, source_read_set: [], payload: { run_id: run.run_id } }));
      })}>预览整次撤回</Button>{revert && <div className="mt-4 space-y-3"><p>{revert.review.effect}</p><p className="subtle">本次包含 {revert.review.receipts.length} 条结果回执。</p><Button disabled={busy || !!pending || !proofClockCurrent("T1", revert.expires_at)} onClick={() => void send({ path: "v1/commands", body: revert.command })}>确认整次撤回</Button></div>}</details>}
    </div>}
    <div className="space-y-3 border-t pt-4"><h3 className="font-medium">我的运行历史</h3>{history.items.length === 0 && <p className="subtle">{proposalId ? "当前提案暂无运行。" : "当前品类暂无运行。"}</p>}{history.items.map(item => <button type="button" disabled={busy} key={item.run_id} className="block w-full rounded-lg border p-3 text-left" aria-pressed={item.run_id === run?.run_id} onClick={() => void read(() => readRun(item.run_id))}><p className="break-words">{item.goal}</p><p className="subtle mt-1">{item.reverted ? "已整次撤回" : reconciliationNeeded(item) ? "原调用结果待核对" : labels[item.status] ?? item.status} · <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time></p></button>)}{history.next_cursor && <Button variant="outline" disabled={busy} onClick={() => void read(() => refreshHistory(history.next_cursor!))}>查看更多运行</Button>}</div>
  </section>;
}
