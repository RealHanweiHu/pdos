"use client";

import { RunFeedback } from "@/components/pai/run-feedback";
import { RunContinuation } from "@/components/pai/run-continuation";
import { RunProcess } from "@/components/pai/run-process";
import type { RunProcessData } from "@/lib/run-process";
import { RunReconciliation } from "@/components/pai/run-reconciliation";
import { reconciliationNeeded } from "@/lib/run-reconciliation";
import { ResearchResult } from "@/components/pai/research-result";
import { loadedSkillFacts, PaiCarry, PaiMessage, PaiPolicy, PaiScope } from "@/components/pai-conversation";
import type { LoadedSkill } from "@/components/pai-conversation";
import { SessionHistory } from "@/components/pai/session-history";
import styles from "../pai-conversation.module.css";

import { useCallback, useEffect, useRef, useState } from "react";
import { PaperPlaneTilt, Plus, Sparkle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { CategoryCreateForm } from "./category-create-form";
import { ClarificationDialog, ClarificationForm, panelVisible } from "./clarification";
import type { Question } from "./clarification";
import { adoptedCategory, asCandidate, personalApi } from "./contracts";
import type { Api, CategoryAdopted, CategoryCandidate, CategoryConfirmationDraft, CreatedCategory } from "./contracts";

type Run = { session_id: string; goal?: string; conversation?: {previous_run_id:string|null;next_run_id:string|null}; process?: RunProcessData; reconciliation?: unknown; run_id: string; status: string; cancel_epoch: number; reverted: boolean; error_code?: string; result?: { summary?: string; unfinished?: string[]; result?: Record<string, unknown> } };
type Event = { sequence: number; event: { type: string; key?: string; version?: string; questions?: Question[] } };
type Pending = { path: string; body: unknown };
const root = "v1/personal/agent-runs";
const labels: Record<string, string> = { queued: "已保存，等待执行", running: "正在执行", waiting_input: "等待你的答复", completed: "已完成", partial: "已有部分结果", cancelled: "已取消", failed: "执行未完成" };

/** Opening or refreshing this panel only reads durable runs and events. */
type Props = { api?: Api; principalId?: string; onCreated: (category: CreatedCategory) => void; initialRunId?: string; onBackground?: () => void };
export function PersonalXiaopai(props: Props) {
  const api = props.api ?? personalApi;
  const [binding, setBinding] = useState({ api, revision: 0 });
  if (binding.api !== api) { setBinding({ api, revision: binding.revision + 1 }); return null; }
  return <PersonalIdentity key={`${binding.revision}:${props.principalId ?? "resolve"}`} {...props} api={api} />;
}
function PersonalIdentity(props: Props & { api: Api }) {
  const { api, principalId: knownPrincipalId } = props;
  const [identity, setIdentity] = useState<{ principalId?: string; error?: string }>({});
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (knownPrincipalId) return;
    let active = true;
    void api<{ principal_id: string }>("v1/session").then(value => {
      if (typeof value.principal_id !== "string" || !value.principal_id) throw new Error("当前身份无法核对。");
      if (active) setIdentity({ principalId: value.principal_id });
    }).catch(failure => { if (active) setIdentity({ error: failure instanceof Error ? failure.message : "当前身份读取暂不可用。" }); });
    return () => { active = false; };
  }, [api, knownPrincipalId, attempt]);
  const principalId = props.principalId ?? identity.principalId;
  if (!principalId) return <section className={styles.workspace} aria-label="个人小 Pai"><p role={identity.error ? "alert" : "status"}>{identity.error || "正在核对当前身份…"}</p><p>执行需要已配置的模型和运行授权。</p>{identity.error && <Button variant="outline" onClick={() => { setIdentity({}); setAttempt(value => value + 1); }}>重新核对身份</Button>}</section>;
  return <ScopedPersonalXiaopai key={principalId} {...props} principalId={principalId} />;
}
function ScopedPersonalXiaopai({ api, principalId, onCreated, initialRunId, onBackground }: Props & { api: Api; principalId: string }) {
  const [goal, setGoal] = useState("");
  const [historyVersion, setHistoryVersion] = useState(0);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [skills, setSkills] = useState<LoadedSkill[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [backgroundRun, setBackgroundRun] = useState<string | null>(null);
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
  const mounted = useRef(true);
  const lock = useRef(false);
  const request = useRef<Pending | null>(null);
  const panel = useRef<HTMLElement | null>(null);
  const composer = useRef<HTMLTextAreaElement | null>(null);
  const answerAnchor = useRef<HTMLDivElement | null>(null);
  const questionIdentity = useRef<string | null>(null);
  const seenInterrupts = useRef(new Set<string>());
  const background = useRef<string | null>(null);

  const selectedSession = useRef<string | null>(null);
  const current = useRef<string | null>(null);
  const clearSelection = useCallback(() => {
    generation.current++; current.current = null; selectedSession.current = null;
    background.current = null; setBackgroundRun(null); setSelectedRunId(null); setSessionId(null);
    setRun(null); setSkills([]); setCandidates([]); setAdoptions([]); setQuestions([]); setAnswers({});
    setQuestionDialog(false); questionIdentity.current = null;
  }, []);
  useEffect(() => { const alive = mounted, counter = generation; alive.current = true; return () => { alive.current = false; counter.current++; }; }, []);

  const readRun = useCallback(async (id: string, mode: "restore" | "live" = "restore", expectedSessionId?: string) => {
    const expected = expectedSessionId ?? selectedSession.current;
    if (current.current !== id) { setRun(null); setSkills([]); setCandidates([]); setAdoptions([]); setQuestions([]); setAnswers({}); setQuestionDialog(false); questionIdentity.current = null; }
    current.current = id; setSelectedRunId(id);
    const own = ++generation.current;
    try {
      const value = await api<Run>(`${root}/${id}`);
      if (generation.current !== own) return;
      if (value.run_id !== id || typeof value.session_id !== "string" || !value.session_id || expected && value.session_id !== expected) throw new Error("读取结果与所选个人会话或运行不一致，请重新选择。");
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
      selectedSession.current = value.session_id; setSessionId(value.session_id);
      setRun(value);
      setSkills(loadedSkillFacts(events));
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
        setQuestionDialog(!!identity && mode === "live" && background.current !== id && !seenInterrupts.current.has(identity) && panelVisible(panel.current));
        questionIdentity.current = identity;
      }
      if (identity) seenInterrupts.current.add(identity);
      else setQuestionDialog(false);
      if (mode === "restore") for (const event of events) {
        if (event.event.type === "needs_input") seenInterrupts.current.add(`${id}:${event.sequence}`);
      }
      setQuestions(currentQuestions);
    } catch (failure) { if (generation.current === own) { setRun(null); setSkills([]); setCandidates([]); setAdoptions([]); setQuestions([]); setAnswers({}); setQuestionDialog(false); questionIdentity.current = null; throw failure; } }
  }, [api]);

  useEffect(() => {
    const hide = () => { if (document.visibilityState !== "visible") setQuestionDialog(false); };
    document.addEventListener("visibilitychange", hide);
    return () => document.removeEventListener("visibilitychange", hide);
  }, []);
  useEffect(() => {
    if (!initialRunId) return;
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      clearSelection();
      return readRun(initialRunId).catch(failure => { if (active) setError(failure.message); });
    });
    return () => { active = false; };
  }, [initialRunId, readRun, clearSelection]);
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
    if (clearRun) { clearSelection(); setHistoryOpen(false); }
    try { await action(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "读取暂不可用。"); setCandidates([]); setAdoptions([]); setQuestions([]); setQuestionDialog(false); }
    finally { lock.current = false; setBusy(false); }
  }
  async function send(value: Pending) {
    if (lock.current) return;
    lock.current = true; generation.current++; setBusy(true); setError(""); setNotice("");
    request.current = value; setPending(value);
    setQuestionDialog(false);
    if (value.path === root) { clearSelection(); setHistoryOpen(false); }
    try {
      const result = await api<{ run_id: string; execution_state?: string }>(value.path, value.body);
      if (!mounted.current) return;
      request.current = null; setPending(null); setAnswers({});
      setNotice(result.execution_state === "durable_runtime_unavailable"
        ? "运行已保存，持久执行服务暂不可用，尚未完成模型执行。" : "请求已保存，以下显示服务器的实际运行结果。");
      if (value.path === root) setGoal("");
      setRun(null); setCandidates([]); setAdoptions([]); setQuestions([]);
      await readRun(result.run_id, "live");
      setHistoryVersion(value => value + 1);
    } catch (failure) { if (mounted.current) setError(failure instanceof Error ? failure.message : "请求未完成。"); }
    finally { lock.current = false; setBusy(false); }
  }
  const answerProps = { questions, answers, disabled: busy || !!pending,
    onAnswer: (id: string, value: string) => setAnswers(old => ({ ...old, [id]: value })),
    onSubmit: () => { if (run && !pending) void send({ path: `${root}/${run.run_id}/answers`, body: { answers, idempotency_key: crypto.randomUUID() } }); },
  };
  const runGoal = run?.goal;
  const active = !!run && !run.reverted && ["queued", "running"].includes(run.status);
  return <section ref={panel} className={styles.workspace} data-history-open={historyOpen} aria-label="个人小 Pai">
    <PaiScope scope="个人工作 · 建立新品类" skills={skills} hasRun={!!run} historyOpen={historyOpen} onHistoryToggle={() => setHistoryOpen(value => !value)} />
    <div className={styles.layout}>
      <aside className={styles.history} aria-label="个人工作记录">
        <Button className={styles.newWork} disabled={busy || !!pending} onClick={() => { clearSelection(); setHistoryOpen(false); composer.current?.focus(); }}><Plus size={14} aria-hidden="true" />新工作</Button>
        <SessionHistory api={api} scope={{ categoryId: null }} principalId={principalId} currentSessionId={sessionId} currentRunId={selectedRunId} refreshVersion={historyVersion} disabled={busy || !!pending} onClearSelection={clearSelection} onSelectRun={(id, sid) => { clearSelection(); selectedSession.current = sid; setSessionId(sid); setHistoryOpen(false); void read(() => readRun(id, "restore", sid)); }} />
      </aside>
      <div className={styles.conversation}>
        <div className={styles.thread} aria-label="小Pai 对话线程">
          {notice && <p role="status" className="text-xs">{notice}</p>}{error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          {pending && <Button variant="outline" disabled={busy} onClick={() => { if (request.current) void send(request.current); }}>重试同一请求</Button>}
          {!run && selectedRunId && <Button variant="outline" disabled={busy || !!pending} onClick={() => void read(() => readRun(selectedRunId))}>刷新实际结果</Button>}
          {!run && <div className={styles.empty}><Sparkle size={24} aria-hidden="true" /><p>从一个新品类目标开始</p><p>说明产品用途、市场范围和希望核对的问题。</p><p className={styles.threadIntro}>执行需要已配置的模型和运行授权；研究依据、问题、候选与采用回执保存在实际工作中。</p></div>}
          {run && backgroundRun === run.run_id && <div className="rounded-lg border p-3 text-sm"><p>工作已保留 · {labels[run.status] ?? "状态待核对"}</p><p className={styles.runId}>运行 {run.run_id}</p><Button className="mt-2" size="sm" variant="outline" onClick={() => { background.current = null; setBackgroundRun(null); }}>返回当前工作</Button></div>}
    {run && backgroundRun !== run.run_id && <>
      {runGoal && <PaiMessage from="user"><p className="whitespace-pre-wrap break-words text-sm">{runGoal}</p></PaiMessage>}
      <PaiMessage from="pai">
      <h3 className="text-xs font-semibold">{reconciliationNeeded(run) ? "原调用结果待核对" : labels[run.status] ?? "状态待核对"}{run.reverted ? " · 已撤回" : ""}</h3>
      <p className={styles.runId}>运行 {run.run_id}</p>
      {active && <div className="flex flex-wrap items-center gap-2"><Button size="sm" variant="outline" disabled={busy || !!pending} onClick={() => void send({ path: `${root}/${run.run_id}/cancel`, body: {} })}>停止后续执行</Button><Button size="sm" variant="ghost" disabled={busy || !!pending} onClick={() => { if (onBackground) onBackground(); else { background.current = run.run_id; setBackgroundRun(run.run_id); } setQuestionDialog(false); setNotice("已转后台继续，仍是同一次运行；可从工作记录找回。"); }}>转后台继续</Button></div>}
      {run.error_code && <p role="alert" className="text-sm">执行未完成：{run.error_code}。请检查模型配置、权限或执行服务后再继续。</p>}
      {run.process && <RunProcess key={`process:${run.run_id}`} value={run.process} api={api} root={root} />}
      <RunFeedback key={`feedback:${run.run_id}`} api={api} root={root} runId={run.run_id} />
      <RunReconciliation key={run.run_id} api={api} root={root} run={run} onSettled={() => readRun(run.run_id)} />
      {run.result?.summary && <p className={styles.bubble}>{run.result.summary}</p>}
      <ResearchResult value={run.result?.result?.research} />
      {run.result?.unfinished?.map((item, index) => <p key={index} className="text-sm text-muted-foreground">待完成：{item}</p>)}
      <Button variant="outline" disabled={busy} onClick={() => void read(() => readRun(run.run_id))}>刷新实际结果</Button>
      {!run.reverted && ["queued", "running", "waiting_input"].includes(run.status) && <Button variant="ghost" disabled={busy || !!pending}
        onClick={() => void send({ path: `${root}/${run.run_id}/cancel`, body: {} })}>取消后续执行</Button>}
      {questions.length > 0 && <div ref={answerAnchor} tabIndex={-1}><ClarificationForm {...answerProps} prefix="inline" /></div>}
      {!candidates.length && !adoptions.length && <p className="text-sm text-muted-foreground">此运行尚无可采用的品类候选。</p>}
      </PaiMessage>
    </>}
    {run && backgroundRun !== run.run_id && adoptions.map(({ proof, category }) => <section key={proof.receipt_id} className="panel space-y-3">
      <h3 className="font-medium">已采用 · {category.name}</h3>
      <p role="status" className="text-sm">品类创建已完成，原候选已采用。</p>
      <p className="break-all text-sm">创建回执：{proof.receipt_id}</p>
      <details className="text-sm text-muted-foreground"><summary className="cursor-pointer">原采用记录</summary>
        <p className="break-all">个人运行：{proof.run_id}</p><p className="break-all">候选摘要：{proof.candidate_digest}</p>
        <p className="break-all">采用输入：{proof.input_ref}</p>
      </details>
      <Button onClick={() => onCreated(category)}>进入已创建品类</Button>
    </section>)}
    {run && backgroundRun !== run.run_id && candidates.map(candidate => <CategoryCreateForm key={`${run.run_id}:${candidate.candidate_digest}`} candidate={candidate} runId={run.run_id} api={api} onCreated={onCreated}
      draft={confirmationDrafts[`${run.run_id}:${candidate.candidate_digest}`]} onDraftChange={draft => setConfirmationDrafts(old => {
        const key = `${run.run_id}:${candidate.candidate_digest}`;
        if (draft) return { ...old, [key]: draft };
        const next = { ...old }; delete next[key]; return next;
      })}
      disabled={busy || !!pending || run.reverted || candidate.cancel_epoch !== run.cancel_epoch || !["queued", "running", "waiting_input", "completed", "partial"].includes(run.status)} />)}
    {run && backgroundRun !== run.run_id && questions.length > 0 && <ClarificationDialog {...answerProps} open={questionDialog} onClose={() => setQuestionDialog(false)}
      onReturnFocus={() => answerAnchor.current?.focus()} />}
        </div>
        <div className={styles.composer}>
          {run && <div className={styles.continuation}><RunContinuation key={`continue:${run.run_id}`} api={api} root={root} run={run} onOpen={async id => { await readRun(id); setHistoryVersion(value => value + 1); }} /></div>}
          <form onSubmit={event => { event.preventDefault(); if (!pending && goal.trim().length >= 3) void send({ path: root, body: { goal, idempotency_key: crypto.randomUUID(), sources: [] } }); }}>
            <div className={styles.composerBox}>
              <div className={styles.composerTools}><span className={styles.skillLabel}>新工作 · 建立新品类</span><PaiCarry scope="个人工作 · 建立新品类" objects={[]} /></div>
              <div className={styles.inputRow}>
                <textarea ref={composer} aria-label="要研究和建立什么品类？" required minLength={3} maxLength={8000} rows={2} value={goal} disabled={busy || !!pending} onChange={event => setGoal(event.target.value)} placeholder="说明品类用途、市场范围和希望核对的问题" />
                <Button className={styles.send} aria-label="保存并启动个人任务" disabled={busy || !!pending || goal.trim().length < 3}><PaperPlaneTilt size={17} aria-hidden="true" /><span className="sr-only">保存并启动个人任务</span></Button>
              </div>
            </div>
            <div className={styles.composerFooter}><PaiPolicy /></div>
          </form>
        </div>
      </div>
    </div>
  </section>;
}
