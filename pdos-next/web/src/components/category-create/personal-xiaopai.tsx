"use client";

import { RunFeedback } from "@/components/pai/run-feedback";
import { RunProcess } from "@/components/pai/run-process";
import type { RunProcessData } from "@/lib/run-process";
import { RunReconciliation } from "@/components/pai/run-reconciliation";
import { reconciliationNeeded } from "@/lib/run-reconciliation";
import { ResearchResult } from "@/components/pai/research-result";

import { useCallback, useEffect, useRef, useState } from "react";
import { Sparkle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { CategoryCreateForm } from "./category-create-form";
import { ClarificationDialog, ClarificationForm, panelVisible } from "./clarification";
import type { Question } from "./clarification";
import { adoptedCategory, asCandidate, personalApi } from "./contracts";
import type { Api, CategoryAdopted, CategoryCandidate, CategoryConfirmationDraft, CreatedCategory } from "./contracts";

type Run = { process?: RunProcessData; reconciliation?: unknown; run_id: string; status: string; cancel_epoch: number; reverted: boolean; error_code?: string; result?: { summary?: string; unfinished?: string[]; result?: Record<string, unknown> } };
type History = { items: (Run & { goal: string })[]; next_cursor: string | null };
type Event = { sequence: number; event: { type: string; questions?: Question[] } };
type Pending = { path: string; body: unknown };
const root = "v1/personal/agent-runs";
const labels: Record<string, string> = { queued: "已保存，等待执行", running: "正在执行", waiting_input: "等待你的答复", completed: "已完成", partial: "已有部分结果", cancelled: "已取消", failed: "执行未完成" };

/** Opening or refreshing this panel only reads durable runs and events. */
export function PersonalXiaopai({ api = personalApi, onCreated, initialRunId }: { api?: Api; onCreated: (category: CreatedCategory) => void; initialRunId?: string }) {
  const [goal, setGoal] = useState("");
  const [history, setHistory] = useState<History>({ items: [], next_cursor: null });
  const [run, setRun] = useState<Run | null>(null);
  const [candidates, setCandidates] = useState<CategoryCandidate[]>([]);
  const [adoptions, setAdoptions] = useState<{ proof: CategoryAdopted; category: CreatedCategory }[]>([]);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [questionDialog, setQuestionDialog] = useState(false);
  const [confirmationDrafts, setConfirmationDrafts] = useState<Record<string, CategoryConfirmationDraft>>({});
  const generation = useRef(0);
  const lock = useRef(false);
  const request = useRef<Pending | null>(null);
  const panel = useRef<HTMLElement | null>(null);
  const answerAnchor = useRef<HTMLDivElement | null>(null);
  const questionIdentity = useRef<string | null>(null);
  const seenInterrupts = useRef(new Set<string>());

  const readRun = useCallback(async (id: string, mode: "restore" | "live" = "restore") => {
    const own = ++generation.current;
    try {
      const value = await api<Run>(`${root}/${id}`);
      if (value.run_id !== id) throw new Error("读取结果与所选个人运行不一致，请重新选择。");
      const events: Event[] = [];
      let after = 0;
      for (;;) {
        if (generation.current !== own) return;
        const page = await api<{ items: Event[]; next_cursor: number }>(`${root}/${id}/events?after=${after}&page_size=200`);
        events.push(...page.items);
        if (page.items.length < 200 || page.next_cursor <= after) break;
        after = page.next_cursor;
      }
      if (generation.current !== own) return;
      setRun(value);
      const allCandidates = events.flatMap(item => { const candidate = asCandidate(item.event); return candidate ? [candidate] : []; });
      const adopted = events.flatMap(item => {
        const proof = adoptedCategory(item.event, id);
        const candidate = proof && allCandidates.find(item => item.candidate_digest === proof.candidate_digest);
        return proof ? [{ proof, category: { id: proof.category_id, name: candidate?.input.name ?? "已创建品类",
          purpose: candidate?.input.purpose ?? "", receiptId: proof.receipt_id } }] : [];
      });
      setAdoptions(adopted);
      setCandidates(value.reconciliation ? [] : allCandidates.filter(item => !adopted.some(adoption => adoption.proof.candidate_digest === item.candidate_digest)));
      const latestInput = [...events].reverse().find(item => ["needs_input", "category_candidate", "category_adopted"].includes(item.event.type));
      const currentQuestions = value.status === "waiting_input" && !value.reverted && !reconciliationNeeded(value) && latestInput?.event.type === "needs_input"
        ? latestInput.event.questions ?? [] : [];
      const identity = currentQuestions.length && latestInput ? `${id}:${latestInput.sequence}` : null;
      if (identity !== questionIdentity.current) {
        setAnswers({});
        setQuestionDialog(!!identity && mode === "live" && !seenInterrupts.current.has(identity) && panelVisible(panel.current));
        questionIdentity.current = identity;
      }
      if (identity) seenInterrupts.current.add(identity);
      else setQuestionDialog(false);
      if (mode === "restore") for (const event of events) {
        if (event.event.type === "needs_input") seenInterrupts.current.add(`${id}:${event.sequence}`);
      }
      setQuestions(currentQuestions);
    } catch (failure) { if (generation.current === own) { setRun(prior => prior?.run_id === id ? { ...prior, process: undefined } : prior); throw failure; } }
  }, [api]);

  const readHistory = useCallback(async (cursor?: string) => {
    const value = await api<History>(`${root}?page_size=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
    setHistory(old => cursor ? { ...value, items: [...old.items, ...value.items.filter(item => !old.items.some(previous => previous.run_id === item.run_id))] } : value);
  }, [api]);
  useEffect(() => {
    const hide = () => { if (document.visibilityState !== "visible") setQuestionDialog(false); };
    document.addEventListener("visibilitychange", hide);
    return () => document.removeEventListener("visibilitychange", hide);
  }, []);
  useEffect(() => {
    let active = true;
    const counter = generation;
    void api<History>(`${root}?page_size=50`).then(value => { if (active) setHistory(value); })
      .catch(failure => { if (active) setError(failure.message); });
    return () => { active = false; counter.current++; };
  }, [api]);
  useEffect(() => {
    if (!initialRunId) return;
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      return readRun(initialRunId).catch(failure => { if (active) setError(failure.message); });
    });
    return () => { active = false; };
  }, [initialRunId, readRun]);
  useEffect(() => {
    if (!run || run.reverted || !["queued", "running"].includes(run.status) && !reconciliationNeeded(run)) return;
    let reading = false;
    const timer = setInterval(() => {
      if (lock.current || reading) return;
      reading = true;
      void readRun(run.run_id, "live").catch(failure => { setError(failure.message); setCandidates([]); setAdoptions([]); setQuestions([]); setQuestionDialog(false); })
        .finally(() => { reading = false; });
    }, 3000);
    return () => clearInterval(timer);
  }, [run, readRun]);

  async function read(action: () => Promise<unknown>, clearRun = false) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError("");
    if (clearRun) { generation.current++; setRun(null); setCandidates([]); setAdoptions([]); setQuestions([]); setAnswers({}); setQuestionDialog(false); questionIdentity.current = null; }
    try { await action(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "读取暂不可用。"); setCandidates([]); setAdoptions([]); setQuestions([]); setQuestionDialog(false); }
    finally { lock.current = false; setBusy(false); }
  }
  async function send(value: Pending) {
    if (lock.current) return;
    lock.current = true; generation.current++; setBusy(true); setError(""); setNotice("");
    request.current = value; setPending(value);
    setQuestionDialog(false);
    if (value.path === root) { setRun(null); setCandidates([]); setAdoptions([]); setQuestions([]); }
    try {
      const result = await api<{ run_id: string; execution_state?: string }>(value.path, value.body);
      request.current = null; setPending(null); setAnswers({});
      setNotice(result.execution_state === "durable_runtime_unavailable"
        ? "运行已保存，持久执行服务暂不可用，尚未完成模型执行。" : "请求已保存，以下显示服务器的实际运行结果。");
      if (value.path === root) setGoal("");
      setRun(null); setCandidates([]); setAdoptions([]); setQuestions([]);
      await readRun(result.run_id, "live");
      await readHistory();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "请求未完成。"); }
    finally { lock.current = false; setBusy(false); }
  }
  const answerProps = { questions, answers, disabled: busy || !!pending,
    onAnswer: (id: string, value: string) => setAnswers(old => ({ ...old, [id]: value })),
    onSubmit: () => { if (run && !pending) void send({ path: `${root}/${run.run_id}/answers`, body: { answers, idempotency_key: crypto.randomUUID() } }); },
  };
  return <section ref={panel} className="space-y-4" aria-label="个人小 Pai">
    <div className="panel space-y-4">
      <h2 className="flex items-center gap-2 font-semibold"><Sparkle aria-hidden size={20} />个人小 Pai · 建立新品类</h2>
      <p className="text-sm text-muted-foreground">描述品类用途，让小 Pai 准备公开研究与初始材料。执行需要已配置的模型和运行授权；缺少配置时会显示实际错误。建立品类仍需你逐组核对并确认。</p>
      <form className="space-y-3" onSubmit={event => { event.preventDefault(); if (!pending && goal.trim().length >= 3) void send({ path: root, body: { goal, idempotency_key: crypto.randomUUID(), sources: [] } }); }}>
        <label className="block">要研究和建立什么品类？<textarea required minLength={3} maxLength={8000} value={goal}
          disabled={busy || !!pending} onChange={event => setGoal(event.target.value)} placeholder="说明产品用途、市场范围和希望核对的问题。请勿输入客户或个人识别信息。" /></label>
        <Button disabled={busy || !!pending || goal.trim().length < 3}>保存并启动个人任务</Button>
      </form>
      {notice && <p role="status" className="text-sm">{notice}</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {pending && <Button variant="outline" disabled={busy} onClick={() => { if (request.current) void send(request.current); }}>重试同一请求</Button>}
      <details><summary className="cursor-pointer text-sm">个人任务记录</summary>
        <div className="mt-3 space-y-2">{history.items.map(item => <Button key={item.run_id} variant="outline" className="h-auto w-full justify-start whitespace-normal text-left" disabled={busy || !!pending}
          onClick={() => void read(() => readRun(item.run_id), true)}>{item.goal} · {reconciliationNeeded(item) ? "原调用结果待核对" : labels[item.status] ?? item.status}</Button>)}
          {!history.items.length && <p className="text-sm text-muted-foreground">暂无可见的个人任务。</p>}
          <Button variant="ghost" disabled={busy} onClick={() => void read(() => readHistory())}>刷新记录</Button>
          {history.next_cursor && <Button variant="ghost" disabled={busy} onClick={() => void read(() => readHistory(history.next_cursor!))}>更多记录</Button>}
        </div>
      </details>
    </div>
    {run && <div className="panel space-y-3">
      <h3 className="font-medium">{reconciliationNeeded(run) ? "原调用结果待核对" : labels[run.status] ?? run.status}{run.reverted ? " · 已撤回" : ""}</h3>
      {run.error_code && <p role="alert" className="text-sm">执行未完成：{run.error_code}。请检查模型配置、权限或执行服务后再继续。</p>}
      {run.process && <RunProcess key={`process:${run.run_id}`} value={run.process} api={api} root={root} />}
      <RunFeedback key={`feedback:${run.run_id}`} api={api} root={root} runId={run.run_id} />
      <RunReconciliation key={run.run_id} api={api} root={root} run={run} onSettled={() => readRun(run.run_id)} />
      {run.result?.summary && <p className="whitespace-pre-wrap text-sm">{run.result.summary}</p>}
      <ResearchResult value={run.result?.result?.research} />
      {run.result?.unfinished?.map((item, index) => <p key={index} className="text-sm text-muted-foreground">待完成：{item}</p>)}
      <Button variant="outline" disabled={busy} onClick={() => void read(() => readRun(run.run_id))}>刷新实际结果</Button>
      {!run.reverted && ["queued", "running", "waiting_input"].includes(run.status) && <Button variant="ghost" disabled={busy || !!pending}
        onClick={() => void send({ path: `${root}/${run.run_id}/cancel`, body: {} })}>取消后续执行</Button>}
      {questions.length > 0 && <div ref={answerAnchor} tabIndex={-1}><ClarificationForm {...answerProps} prefix="inline" /></div>}
      {!candidates.length && !adoptions.length && <p className="text-sm text-muted-foreground">此运行尚无可采用的品类候选。</p>}
    </div>}
    {run && adoptions.map(({ proof, category }) => <section key={proof.receipt_id} className="panel space-y-3">
      <h3 className="font-medium">已采用 · {category.name}</h3>
      <p role="status" className="text-sm">品类创建已完成，原候选已采用。</p>
      <p className="break-all text-sm">创建回执：{proof.receipt_id}</p>
      <details className="text-sm text-muted-foreground"><summary className="cursor-pointer">原采用记录</summary>
        <p className="break-all">个人运行：{proof.run_id}</p><p className="break-all">候选摘要：{proof.candidate_digest}</p>
        <p className="break-all">采用输入：{proof.input_ref}</p>
      </details>
      <Button onClick={() => onCreated(category)}>进入已创建品类</Button>
    </section>)}
    {run && candidates.map(candidate => <CategoryCreateForm key={`${run.run_id}:${candidate.candidate_digest}`} candidate={candidate} runId={run.run_id} api={api} onCreated={onCreated}
      draft={confirmationDrafts[`${run.run_id}:${candidate.candidate_digest}`]} onDraftChange={draft => setConfirmationDrafts(old => {
        const key = `${run.run_id}:${candidate.candidate_digest}`;
        if (draft) return { ...old, [key]: draft };
        const next = { ...old }; delete next[key]; return next;
      })}
      disabled={busy || !!pending || run.reverted || candidate.cancel_epoch !== run.cancel_epoch || !["queued", "running", "waiting_input", "completed", "partial"].includes(run.status)} />)}
    {run && questions.length > 0 && <ClarificationDialog {...answerProps} open={questionDialog} onClose={() => setQuestionDialog(false)}
      onReturnFocus={() => answerAnchor.current?.focus()} />}
  </section>;
}
