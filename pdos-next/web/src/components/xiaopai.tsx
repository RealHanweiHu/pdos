"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { At, PaperPlaneTilt, Plus, Sparkle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import { proofClockCurrent } from "@/lib/proof-clock";
import { RunFeedback } from "@/components/pai/run-feedback";
import { RunContinuation } from "@/components/pai/run-continuation";
import { RunProcess } from "@/components/pai/run-process";
import type { RunProcessData } from "@/lib/run-process";
import { RunReconciliation } from "@/components/pai/run-reconciliation";
import { reconciliationNeeded } from "@/lib/run-reconciliation";
import { RunCandidates } from "@/components/pai/run-candidates";
import { ResearchResult } from "@/components/pai/research-result";
import { restoreRunStart } from "@/lib/run-start-intent";
import { loadedSkillFacts, PaiCarry, PaiMessage, PaiPolicy, PaiScope } from "@/components/pai-conversation";
import type { LoadedSkill } from "@/components/pai-conversation";
import { SessionHistory } from "@/components/pai/session-history";
import { FileUpload } from "@/components/pai/file-upload";
import { RunSourceBindings, SourcePicker, sourcePickerScope } from "@/components/pai/source-picker";
import type { SourceSelection } from "@/components/pai/source-picker";
import styles from "./pai-conversation.module.css";

type Source = { id: string; title: string; revision: number; status: string };
type Question = { id: string; question: string; why: string; options: { value: string; label: string }[]; allow_free_text: boolean };
type Run = { session_id: string; goal?: string; conversation?: {previous_run_id:string|null;next_run_id:string|null}; process?: RunProcessData; reconciliation?: unknown; run_id: string; product_id: string | null; project_id?: string | null; proposal_id?: string | null; cancel_epoch: number; status: string; error_code: string | null; reverted: boolean; result: { summary?: string; unfinished?: string[]; result?: Record<string, unknown> } };
type Candidate = { command: Record<string, unknown> & { payload: { statement: string; quote: string; prepared_event_id: string } }; event_id: string };
type Event = { id?: string; sequence: number; event: { type: string; key?: string; version?: string; questions?: Question[]; status?: string; command?: Candidate["command"]; prepared_event_id?: string } };
type Pending = { path: string; body: unknown };
const labels: Record<string, string> = { queued: "已保存，等待执行", running: "正在执行", waiting_input: "等待你的答复", completed: "已完成", partial: "已形成部分结果", cancelled: "已取消后续执行", failed: "执行未完成" };

/** Runs and events are server facts. Reading or reopening this panel never starts inference. */
type Props = {
  api: WorkspaceTransport; productId: string; sources: Source[]; composeOpen: boolean; onComposeChange: (open: boolean) => void;
  initialRunId?: string; proposalId?: string; projectId?: string; projectName?: string;
  categoryId: string; categoryName?: string; proposalTitle?: string; principalId: string; onBackground?: () => void;
};
export function Xiaopai(props: Props) {
  const [binding, setBinding] = useState({ api: props.api, revision: 0 });
  if (binding.api !== props.api) { setBinding({ api: props.api, revision: binding.revision + 1 }); return null; }
  return <ScopedXiaopai key={`${binding.revision}:${props.principalId}:${props.categoryId}:${props.productId}:${props.proposalId ?? ""}:${props.projectId ?? ""}`} {...props} />;
}
function ScopedXiaopai({ api, productId, composeOpen, onComposeChange, initialRunId, categoryId, categoryName, principalId, proposalId, projectId, projectName, proposalTitle, onBackground }: Props) {
  const [goal, setGoal] = useState("");
  const [useProduct, setUseProduct] = useState(false);
  const [selected, setSelected] = useState<SourceSelection | null>(null);
  const [sourceReadVersion, setSourceReadVersion] = useState(0);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [skills, setSkills] = useState<LoadedSkill[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [backgroundRun, setBackgroundRun] = useState<string | null>(null);
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
  const mounted = useRef(true);
  const writeLock = useRef(false);
  const request = useRef<Pending | null>(null);
  const current = useRef<string | null>(null);
  const selectedSession = useRef<string | null>(null);
  const clearSelection = useCallback(() => {
    generation.current++; current.current = null; selectedSession.current = null;
    setSessionId(null); setSelectedRunId(null); setRun(null); setSkills([]); setQuestions([]); setAnswers({});
    setCandidates([]); setAdoption(null); setRevert(null); setEventSequence(0); setBackgroundRun(null);
  }, []);
  const sourceUnavailable = useCallback(() => { setSelected(null); setSourceReadVersion(version => version + 1); clearSelection(); setError("当前来源或运行范围无法核对，已清除旧资料；请重新读取。"); }, [clearSelection]);
  const startStorageKey = `pdos-next:run-start:${principalId}:${categoryId}:${proposalId ?? "category"}${projectId ? `:project:${projectId}` : ""}`;

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      try {
        const original = restoreRunStart(JSON.parse(localStorage.getItem(startStorageKey) ?? "null"), proposalId, projectId);
        if (original) { request.current = original; setPending(original); }
      } catch { /* Optional local recovery; server history remains authoritative. */ }
    });
    return () => { active = false; };
  }, [startStorageKey, proposalId, projectId]);

  useEffect(() => { const alive = mounted, counter = generation; alive.current = true; return () => { alive.current = false; counter.current++; }; }, []);
  const readRun = useCallback(async (id: string, expectedSessionId?: string) => {
    const expected = expectedSessionId ?? selectedSession.current;
    if (current.current !== id) { setRun(null); setSkills([]); setQuestions([]); setAnswers({}); setCandidates([]); setAdoption(null); setRevert(null); setEventSequence(0); }
    const own = ++generation.current;
    current.current = id; setSelectedRunId(id);
    try {
    const value = await api<Run>(`v1/agent-runs/${id}`);
    if (own !== generation.current) return;
    if (value.run_id !== id || typeof value.session_id !== "string" || !value.session_id || expected && value.session_id !== expected) throw new Error("读取结果与所选会话或运行不一致，请重新选择。 ");
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
    selectedSession.current = value.session_id; setSessionId(value.session_id);
    setRun(value);
    setSkills(loadedSkillFacts(events));
    setEventSequence(events.at(-1)?.sequence ?? 0);
    const adopted = new Set(events.filter(item => item.event.type === "claim_candidate_adopted").map(item => item.event.prepared_event_id));
    setCandidates(value.reconciliation ? [] : events.filter(item => item.event.type === "claim_candidate" && item.event.command && !adopted.has(item.event.command.payload.prepared_event_id)).map(item => ({ command: item.event.command!, event_id: item.event.command!.payload.prepared_event_id })));
    setAdoption(null);
    setRevert(null);
    setQuestions(value.status === "waiting_input" && !value.reverted && !reconciliationNeeded(value) ? [...events].reverse().find(item => item.event.type === "needs_input")?.event.questions ?? [] : []);
    } catch (failure) { if (own === generation.current) { setRun(null); setSkills([]); setQuestions([]); setAnswers({}); setCandidates([]); setAdoption(null); setRevert(null); setEventSequence(0); setSelected(null); if ((failure as { status?: number }).status !== 503) setSourceReadVersion(version => version + 1); throw failure; } }
  }, [api, proposalId]);
  useEffect(() => {
    if (!initialRunId) return;
    let active = true;
    void Promise.resolve().then(() => { if (active) { clearSelection(); return readRun(initialRunId).catch(failure => { if (active) setError(failure.message); }); } });
    return () => { active = false; };
  }, [initialRunId, readRun, clearSelection]);
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
    let accepted = false;
    if (value.path === "v1/agent-runs") {
      clearSelection();
      try { localStorage.setItem(startStorageKey, JSON.stringify(value)); } catch { /* In-memory original remains available. */ }
    }
    try {
      const result = await api<{ run_id: string; execution_state?: string; workflow_cancel_pending?: boolean }>(value.path, value.body);
      if (!mounted.current) return;
      if (value.path === "v1/agent-runs" && !result.run_id) throw new Error("运行受理结果尚未核对，请重试原请求。");
      accepted = true;
      request.current = null; setPending(null);
      if (value.path === "v1/agent-runs") { try { localStorage.removeItem(startStorageKey); } catch { /* Optional storage. */ } }
      setNotice(result.execution_state === "durable_runtime_unavailable" ? "运行已保存，持久执行服务暂不可用。恢复后会继续派送。" : result.workflow_cancel_pending ? "取消已记录，正在通知执行服务。" : "请求已保存，可以查看实际运行状态。");
      if (value.path === "v1/agent-runs") { setGoal(""); setSelected(null); setBackgroundRun(null); onComposeChange(false); }
      setAnswers({});
      await readRun(result.run_id ?? current.current!);
      setHistoryVersion(value => value + 1);
    } catch (failure) {
      if (!mounted.current) return;
      const status = (failure as { status?: number }).status;
      if ((value.path !== "v1/agent-runs" || accepted) && (status === 401 || status === 403 || status === 404)) sourceUnavailable();
      if (accepted && value.path === "v1/agent-runs") setNotice("新工作已保存，实际运行资料暂不可读；不会重新提交原委派。");
      if (!accepted && value.path === "v1/agent-runs" && status && status >= 400 && status < 500 && status !== 408 && status !== 429) {
        request.current = null; setPending(null); setSelected(null); setSourceReadVersion(version => version + 1);
        setNotice("原新工作请求已被明确拒绝，请重新核对范围并选择固定来源后再发送。");
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

  const pendingStart = pending?.path === "v1/agent-runs" ? restoreRunStart(pending, proposalId, projectId) : null;
  const sourceScope = { principalId, categoryId, productId: !proposalId && productId && (projectId || useProduct) ? productId : null, proposalId: proposalId ?? null };
  const selectedSources = selected?.scope === sourcePickerScope(sourceScope) ? selected.items : [];
  const categoryScope = categoryName || "当前品类";
  const requestScope = `${categoryScope}${projectId ? ` · ${projectName || "当前项目"}` : ""}${proposalId ? ` · ${proposalTitle || "当前提案"}` : ""}`;
  const runScope = `${categoryScope}${run?.project_id ? ` · 运行绑定项目 ${run.project_id}` : ""}${run?.proposal_id ? ` · ${run.proposal_id === proposalId ? proposalTitle || "当前提案" : "运行绑定提案"}` : ""}${run?.product_id ? " · 运行绑定型号" : ""}`;
  const runGoal = run?.goal;
  const active = !!run && !run.reverted && ["queued", "running"].includes(run.status);

  return <section className={styles.workspace} data-history-open={historyOpen} aria-label="小Pai 运行">
    <PaiScope scope={run ? runScope : requestScope} skills={skills} hasRun={!!run} historyOpen={historyOpen} onHistoryToggle={() => setHistoryOpen(value => !value)} />
    <div className={styles.layout}>
      <aside className={styles.history} aria-label="小Pai 工作记录">
        <Button className={styles.newWork} disabled={busy || !!pending} onClick={() => { clearSelection(); onComposeChange(true); setHistoryOpen(false); }}><Plus size={14} aria-hidden="true" />新工作</Button>
        <SessionHistory api={api} scope={{ categoryId, proposalId, ...(projectId ? { projectId } : {}) }} principalId={principalId} currentSessionId={sessionId} currentRunId={selectedRunId} refreshVersion={historyVersion} disabled={busy || !!pending} onClearSelection={clearSelection} onSelectRun={(id, sid) => { clearSelection(); selectedSession.current = sid; setSessionId(sid); setHistoryOpen(false); void read(() => readRun(id, sid)); }} />
      </aside>
      <div className={styles.conversation}>
        <div className={styles.thread} aria-label="小Pai 对话线程">
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-xs">{notice}</p>}
          {pending && <div className="rounded-lg border p-3 text-sm"><p>原请求仍待核对，输入暂时保留。</p>{pendingStart && <><p className="mt-2 text-xs">原请求携带 {pendingStart.body.sources.length} 份固定来源；以下是原请求范围，不是当前输入框的选择。</p><details className="mt-2 text-xs"><summary>原请求固定范围与来源</summary><p className="break-all">品类：{categoryId}</p><p className="break-all">原绑定型号：{pendingStart.body.product_id ?? "未关联型号"}</p><p className="break-all">原绑定提案：{pendingStart.body.proposal_id ?? "未关联提案"}</p><p className="break-all">原绑定项目：{pendingStart.body.project_id ?? "未关联项目"}</p>{pendingStart.body.sources.map(source => <p className="break-all" key={source.artifact_id}>登记来源 {source.artifact_id} · 固定版本 {source.expected_revision}</p>)}</details></>}<Button variant="outline" className="mt-3" disabled={busy} onClick={() => { if (request.current) void send(request.current); }}>重试原请求</Button></div>}
          {!run && selectedRunId && <Button variant="outline" disabled={busy || !!pending} onClick={() => void read(() => readRun(selectedRunId))}>核对所选运行</Button>}
          {!run && <div className={styles.empty}><Sparkle size={24} aria-hidden="true" /><p>把目标交给小Pai</p><p>说明希望得到的结果，再选择本次携带的依据。</p><p className={styles.threadIntro}>{proposalId ? "在当前提案内委派起草、抽取或查漏。资料范围由服务器核对；G0 仍由具名评审人决定。" : "结果、待答问题和未完成事项会保留，关闭页面后仍可回来查看。"}</p></div>}
          {run && backgroundRun === run.run_id && <div className="rounded-lg border p-3 text-sm"><p>工作已保留 · {labels[run.status] ?? "状态待核对"}</p><p className={styles.runId}>运行 {run.run_id}</p><Button className="mt-2" size="sm" variant="outline" onClick={() => setBackgroundRun(null)}>返回当前工作</Button></div>}
    {run && backgroundRun !== run.run_id && <div className="contents">
      {runGoal && <PaiMessage from="user"><p className="whitespace-pre-wrap break-words text-sm">{runGoal}</p></PaiMessage>}
      <PaiMessage from="pai">
      <div className={styles.runHeader}><h3 className="font-medium">{run.reverted ? "已整次撤回" : reconciliationNeeded(run) ? "原调用结果待核对" : labels[run.status] ?? "状态待核对"}</h3><Button size="sm" variant="outline" disabled={busy} onClick={() => void read(() => readRun(run.run_id))}>核对当前状态</Button></div>
      <p className={styles.runId}>运行 {run.run_id}</p>
      {active && <div className="flex flex-wrap items-center gap-2"><Button size="sm" variant="outline" disabled={busy || !!pending} onClick={() => void send({ path: `v1/agent-runs/${run.run_id}/cancel`, body: {} })}>停止后续执行</Button><Button size="sm" variant="ghost" disabled={busy || !!pending} onClick={() => { if (onBackground) onBackground(); else setBackgroundRun(run.run_id); setNotice("已转后台继续，仍是同一次运行；可从工作记录找回。"); }}>转后台继续</Button></div>}
      <RunSourceBindings api={api} scope={{ principalId, categoryId, productId: run.product_id, proposalId: run.proposal_id ?? null }} runId={run.run_id} sessionId={run.session_id} onUnavailable={sourceUnavailable} />
      {run.result?.summary && <p className={styles.bubble}>{run.result.summary}</p>}
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
      </PaiMessage>
    </div>}
        </div>
        <div className={styles.composer}>
          {run && <div className={styles.continuation}><RunContinuation key={`continue:${run.run_id}`} api={api} root="v1/agent-runs" run={run} onOpen={async id => { await readRun(id); setHistoryVersion(value => value + 1); }} /></div>}
          <details open={composeOpen || !run} onToggle={event => onComposeChange(event.currentTarget.open)}>
            <summary className={styles.composerMode}>发起新工作</summary>
            <form onSubmit={event => {
              event.preventDefault();
              void send({ path: "v1/agent-runs", body: { goal, idempotency_key: crypto.randomUUID(), product_id: sourceScope.productId, ...(proposalId ? { proposal_id: proposalId } : {}), ...(projectId ? { project_id: projectId } : {}), sources: selectedSources.map(({ artifact_id, expected_revision }) => ({ artifact_id, expected_revision })) } });
            }}>
              <fieldset disabled={busy || !!pending}>
                <div className={styles.composerBox}>
                  <div className={styles.composerTools}>
                    {productId && !proposalId && !projectId && <details className={styles.objectPicker}><summary><At size={13} aria-hidden="true" />对象</summary><div className={styles.objectOptions}>
                      <label><input type="checkbox" checked={useProduct} onChange={event => { setUseProduct(event.target.checked); setSelected(null); }} />关联当前型号</label>
                    </div></details>}
                    <FileUpload api={api} scope={sourceScope} disabled={busy || !!pending} />
                    <SourcePicker key={sourceReadVersion} api={api} scope={sourceScope} value={selected} onChange={setSelected} disabled={busy || !!pending} />
                    <PaiCarry scope={requestScope} objects={[
                      ...(projectId ? [`项目 ${projectName || projectId}`] : []),
                      ...(sourceScope.productId ? [`型号 ${sourceScope.productId}`] : []),
                      ...selectedSources.map(source => `${source.title} · 固定版本 ${source.expected_revision}`),
                    ]} />
                  </div>
                  <div className={styles.inputRow}>
                    <textarea aria-label="希望得到什么结果" required minLength={3} maxLength={8000} rows={2} value={goal} onChange={event => setGoal(event.target.value)} placeholder="说明目标、希望形成的结果和需要核对的依据" />
                    <Button className={styles.send} aria-label="保存并开始" disabled={goal.trim().length < 3}><PaperPlaneTilt size={17} aria-hidden="true" /><span className="sr-only">保存并开始</span></Button>
                  </div>
                </div>
                <div className={styles.composerFooter}><PaiPolicy /></div>
              </fieldset>
            </form>
          </details>
        </div>
      </div>
    </div>
  </section>;
}
