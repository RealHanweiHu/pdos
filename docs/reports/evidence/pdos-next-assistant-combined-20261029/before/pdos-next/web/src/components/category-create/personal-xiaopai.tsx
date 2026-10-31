"use client";

import { RunFeedback } from "@/components/pai/run-feedback";
import { RunContinuation } from "@/components/pai/run-continuation";
import { RunProcess } from "@/components/pai/run-process";
import type { RunProcessData } from "@/lib/run-process";
import { RunReconciliation } from "@/components/pai/run-reconciliation";
import { reconciliationNeeded } from "@/lib/run-reconciliation";
import { ResearchResult } from "@/components/pai/research-result";
import { usePaiScroll, loadedSkillFacts, PaiCarry, PaiMessage, PaiUnfinished, PaiResponse, PaiReplyDetails, PaiDocumentCard, PaiGoal, PaiScope, PaiContextBar, PaiMobileWorkspaceSwitch } from "@/components/pai-conversation";
import { PersonalPreferenceWelcome } from "@/components/personal-preference-welcome";
import type { LoadedSkill } from "@/components/pai-conversation";
import { ConversationHistory } from "@/components/pai/conversation-history";
import { SessionHistory } from "@/components/pai/session-history";
import { SkillPicker } from "@/components/pai/skill-picker";
import type { AgentSkill } from "@/lib/agent-skills";
import { skillTitle } from "@/lib/agent-skills";
import type { RequestedSkill } from "@/lib/run-start-intent";
import styles from "../pai-conversation.module.css";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Plus } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { PaiComposer } from "@/components/pai/composer";
import { clearPaiComposerDrafts, useSessionDraft } from "@/components/pai/use-session-draft";
import { CategoryMetadataEditor } from "../category-metadata-editor";
import { CategoryCreateForm } from "./category-create-form";
import { ClarificationDialog, ClarificationForm, panelVisible } from "./clarification";
import type { Question } from "./clarification";
import { adoptedCategory, asCandidate, personalApi } from "./contracts";
import { PersonalRunMaterials } from "./personal-run-materials";
import { WorkProductActions } from "@/components/pai/work-product-actions";
import { WorkProductEditor } from "@/components/pai/work-product-editor";
import { useWorkProducts } from "@/components/pai/use-work-products";
import type { Api, CategoryAdopted, CategoryCandidate, CategoryConfirmationDraft, CreatedCategory } from "./contracts";

type Run = { session_id: string; goal?: string; conversation?: {previous_run_id:string|null;next_run_id:string|null}; process?: RunProcessData; reconciliation?: unknown; run_id: string; status: string; cancel_epoch: number; reverted: boolean; error_code?: string; result?: { summary?: string; unfinished?: string[]; result?: Record<string, unknown> } };
type Event = { sequence: number; event: { type: string; key?: string; version?: string; questions?: Question[] } };
type Pending = { path: string; body: unknown };
const root = "v1/personal/agent-runs";
const labels: Record<string, string> = { queued: "已保存，等待执行", running: "正在执行", waiting_input: "等待你的答复", completed: "已完成", partial: "已有部分结果", cancelled: "已取消", failed: "执行未完成" };

/** Opening or refreshing this panel only reads durable runs and events. */
type Props = { presetSkillKeys?: string[]; fullPage?: boolean; contextControl?: ReactNode; headerActions?: ReactNode; api?: Api; principalId?: string; onCreated: (category: CreatedCategory) => void; initialRunId?: string; onBackground?: () => void };
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
function ScopedPersonalXiaopai({ api, principalId, onCreated, initialRunId, onBackground, presetSkillKeys, fullPage = false, contextControl, headerActions }: Props & { api: Api; principalId: string }) {
  const materialDialog = useRef<HTMLDialogElement>(null);
  const savedDialog = useRef<HTMLDialogElement>(null);
  const [savedCategory, setSavedCategory] = useState<CreatedCategory | null>(null);
  const [mobileView, setMobileView] = useState<"chat" | "editor">("chat");
  const [material, setMaterial] = useState<{ runId: string; candidate: CategoryCandidate; sourceRun: Run } | null>(null);
  const [requestedSkills, setRequestedSkills] = useState<RequestedSkill[]>([]);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [goal, setGoal] = useSessionDraft(principalId, "personal", sessionId);
  const [run, setRun] = useState<Run | null>(null);
  const [skills, setSkills] = useState<LoadedSkill[]>([]);
  const presetKeys = (presetSkillKeys ?? []).join(":");
  const appliedPreset = useRef("");
  useEffect(() => {
    if (!presetKeys || run || initialRunId || requestedSkills.length || appliedPreset.current === presetKeys) return;
    let active = true;
    type SkillChoice = Pick<AgentSkill, "skill_key" | "skill_version" | "skill_digest" | "enabled" | "available">;
    void api<{ items: SkillChoice[] }>("v1/personal/agent-skills").then(reading => {
      if (!active) return;
      appliedPreset.current = presetKeys;
      const keys = presetKeys.split(":");
      const selected = reading.items.filter(item => keys.includes(item.skill_key) && item.enabled === true && item.available
        && item.skill_version && item.skill_digest).map(item => ({ key: item.skill_key, version: item.skill_version!, digest: item.skill_digest! }));
      setRequestedSkills(current => current.length ? current : selected);
    }).catch(() => { /* The catalog remains available through skill.load. */ });
    return () => { active = false; };
  }, [api, presetKeys, run, initialRunId, requestedSkills.length]);

  const materialRunId = material?.runId, activeRunId = run?.run_id, activeSessionId = run?.session_id;
  useEffect(() => {
    if (!materialRunId || !activeRunId || activeRunId === materialRunId) return;
    let live = true;
    void api<Run>(`${root}/${materialRunId}`).then(value => {
      if (value.run_id !== materialRunId || value.session_id !== activeSessionId) throw new Error("编辑资料与会话不一致。");
      if (live) setMaterial(previous => previous?.runId === value.run_id ? { ...previous, sourceRun: value } : previous);
    }).catch(() => { if (live) { setMaterial(null); materialDialog.current?.close(); setSavedCategory(null); savedDialog.current?.close(); } });
    return () => { live = false; };
  }, [api, materialRunId, activeRunId, activeSessionId]);
  const [historyOpen, setHistoryOpen] = useState(() => fullPage && typeof window !== "undefined" && window.innerWidth >= 1000);
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
  usePaiScroll(panel, run?.run_id);
  const composer = useRef<HTMLTextAreaElement | null>(null);
  const answerAnchor = useRef<HTMLDivElement | null>(null);
  const questionIdentity = useRef<string | null>(null);
  const seenInterrupts = useRef(new Set<string>());
  const background = useRef<string | null>(null);

  const selectedSession = useRef<string | null>(null);
  const current = useRef<string | null>(null);
  const clearSelection = useCallback(() => {
    setMobileView("chat"); setMaterial(null); materialDialog.current?.close(); setSavedCategory(null); savedDialog.current?.close();
    generation.current++; current.current = null; selectedSession.current = null;
    background.current = null; setBackgroundRun(null); setSelectedRunId(null); setSessionId(null);
    setRun(null); setSkills([]); setCandidates([]); setAdoptions([]); setQuestions([]); setAnswers({});
    setQuestionDialog(false); questionIdentity.current = null;
  }, []);
  const sourceUnavailable = useCallback(() => {
    clearPaiComposerDrafts(principalId); setGoal(""); request.current = null; setPending(null);
    setConfirmationDrafts({}); clearSelection(); setBusy(false);
    setError("当前来源或运行范围无法核对，已清除旧资料；请重新读取。");
  }, [clearSelection, principalId, setGoal]);
  const workProducts = useWorkProducts(api, sourceUnavailable);
  const { load: loadWorkProducts, clear: clearWorkProducts } = workProducts;
  useEffect(() => {
    if (run?.session_id) void loadWorkProducts(run.session_id);
  }, [run?.session_id, loadWorkProducts]);
  useEffect(() => {
    if (!run) clearWorkProducts();
  }, [run, clearWorkProducts]);
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
      return value;
    } catch (failure) { if (generation.current === own) { if ([401, 403].includes((failure as { status?: number }).status ?? 0)) sourceUnavailable(); setMaterial(null); materialDialog.current?.close(); setSavedCategory(null); savedDialog.current?.close(); setRun(null); setSkills([]); setCandidates([]); setAdoptions([]); setQuestions([]); setAnswers({}); setQuestionDialog(false); questionIdentity.current = null; throw failure; } }
  }, [api, sourceUnavailable]);

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
    if (clearRun) { clearSelection(); setHistoryOpen(fullPage && window.innerWidth >= 1000); }
    try { await action(); }
    catch (failure) { if ([401, 403].includes((failure as { status?: number }).status ?? 0)) sourceUnavailable(); setError(failure instanceof Error ? failure.message : "读取暂不可用。"); setCandidates([]); setAdoptions([]); setQuestions([]); setQuestionDialog(false); }
    finally { lock.current = false; setBusy(false); }
  }
  async function send(value: Pending) {
    if (lock.current) return;
    lock.current = true; generation.current++; setBusy(true); setError(""); setNotice("");
    request.current = value; setPending(value);
    setQuestionDialog(false);
    if (value.path === root) { clearSelection(); setHistoryOpen(fullPage && window.innerWidth >= 1000); }
    try {
      const result = await api<{ run_id: string; execution_state?: string }>(value.path, value.body);
      if (!mounted.current) return;
      request.current = null; setPending(null); setAnswers({});
      setNotice(result.execution_state === "durable_runtime_unavailable"
        ? "运行已保存，持久执行服务暂不可用，尚未完成模型执行。" : "");
      if (value.path === root) { setGoal(""); setRequestedSkills([]); }
      setRun(null); setCandidates([]); setAdoptions([]); setQuestions([]);
      await readRun(result.run_id, "live");
      setHistoryVersion(value => value + 1);
    } catch (failure) { if (mounted.current) { if ([401, 403].includes((failure as { status?: number }).status ?? 0)) sourceUnavailable(); setError(failure instanceof Error ? failure.message : "请求未完成。"); } }
    finally { lock.current = false; setBusy(false); }
  }
  const answerProps = { questions, answers, disabled: busy || !!pending,
    onAnswer: (id: string, value: string) => setAnswers(old => ({ ...old, [id]: value })),
    onSubmit: () => { if (run && !pending) void send({ path: `${root}/${run.run_id}/answers`, body: { answers, idempotency_key: crypto.randomUUID() } }); },
  };
  const runGoal = run?.goal;
  const active = !!run && !run.reverted && ["queued", "running"].includes(run.status);
  return <section ref={panel} className={styles.workspace} data-history-open={historyOpen} data-full-page={fullPage} data-mobile-view={mobileView} data-editor-open={!!(savedCategory || material || workProducts.openProduct)} aria-label="小Pai工作区">
    {workProducts.openProduct && <WorkProductEditor key={workProducts.openProduct.root_id} product={workProducts.openProduct} original={workProducts.original} open onClose={() => { workProducts.close(); setMobileView("chat"); }} onSaved={workProducts.saved} onReload={workProducts.reload} onUnavailable={sourceUnavailable} onMobileChat={() => setMobileView("chat")} api={api} />}

    <div className={styles.layout}>
      <aside className={styles.history} aria-label="小Pai会话列表">
        <div className={styles.historyHeading}><strong>会话</strong><button type="button" className={styles.historyBack} onClick={() => setHistoryOpen(false)}>返回对话</button></div>
        <Button variant="ghost" className={styles.newWork} disabled={busy || !!pending} onClick={() => { clearSelection(); setHistoryOpen(fullPage && window.innerWidth >= 1000); composer.current?.focus(); }}><Plus size={14} aria-hidden="true" />新对话</Button>
        <SessionHistory api={api} scope={{ categoryId: null }} principalId={principalId} currentSessionId={sessionId} currentRunId={selectedRunId} refreshVersion={historyVersion} disabled={busy || !!pending} onClearSelection={clearSelection} onPermissionDenied={sourceUnavailable} onSelectRun={(id, sid) => { clearSelection(); selectedSession.current = sid; setSessionId(sid); setHistoryOpen(fullPage && window.innerWidth >= 1000); void read(() => readRun(id, "restore", sid)); }} />
        <p className={styles.historyPrivacy}>私人会话 · 仅你可见</p>
      </aside>
      <div className={styles.conversation}>
    <PaiScope onBackground={active ? () => { if (onBackground) onBackground(); else { background.current = run.run_id; setBackgroundRun(run.run_id); } setQuestionDialog(false); setNotice("已在后台继续，可从会话记录返回。"); } : undefined} actions={headerActions} scope="个人工作" skills={skills} hasRun={!!run} title={runGoal} disabled={busy || !!pending} onNewConversation={() => { clearSelection(); setGoal(""); setHistoryOpen(fullPage && window.innerWidth >= 1000); composer.current?.focus(); }} historyOpen={historyOpen} onHistoryToggle={() => setHistoryOpen(value => !value)} />
        <PaiContextBar scope={"通用对话"} control={contextControl}/>
        {(savedCategory || material || workProducts.openProduct) && <PaiMobileWorkspaceSwitch view="editor" onClick={() => setMobileView("editor")} />}
        <div className={styles.thread} aria-label="小Pai 对话线程">
          {notice && <p role="status" className="text-xs">{notice}</p>}{error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          {pending && !busy && <Button variant="outline" disabled={busy} onClick={() => { if (request.current) void send(request.current); }}>重试同一请求</Button>}
          {!run && selectedRunId && <Button variant="outline" disabled={busy || !!pending} onClick={() => void read(() => readRun(selectedRunId))}>刷新实际结果</Button>}
          {!run && <PersonalPreferenceWelcome api={api} onSuggest={value => { setGoal(value); composer.current?.focus(); }}/>}
          {run && backgroundRun === run.run_id && <div className="rounded-lg border p-3 text-sm"><p>工作已保留 · {labels[run.status] ?? "状态待核对"}</p><p className={styles.runId}>运行 {run.run_id}</p><Button className="mt-2" size="sm" variant="outline" onClick={() => { background.current = null; setBackgroundRun(null); }}>返回当前工作</Button></div>}
    {run && backgroundRun !== run.run_id && <>
      <ConversationHistory api={api} root={root} sessionId={run.session_id} previousRunId={run.conversation?.previous_run_id ?? null} onUnavailable={sourceUnavailable} onOpen={id => { void read(() => readRun(id)); }} renderMaterials={historyRun => <><PersonalRunMaterials api={api} runId={historyRun.run_id} onUnavailable={sourceUnavailable}
        onOpenCandidate={(runId, candidate) => { void read(async () => { const restored = await readRun(runId); if (!restored) return; setMobileView("editor"); setMaterial({ runId, candidate, sourceRun: restored }); requestAnimationFrame(() => materialDialog.current?.show()); }); }}
        onOpenCategory={(runId, proof, category) => { void read(async () => { const restored = await readRun(runId); if (!restored) return; setMobileView("editor"); setSavedCategory({ ...category, receiptId: proof.receipt_id }); requestAnimationFrame(() => savedDialog.current?.show()); }); }} /><WorkProductActions run={historyRun} items={workProducts.items} busy={workProducts.busy} onOpen={kind => { void workProducts.openFromRun(historyRun, kind).then(product => { if (product) setMobileView("editor"); }); }} /></>} />
      {runGoal && <PaiMessage from="user"><PaiGoal value={runGoal}/></PaiMessage>}
      <PaiMessage from="pai">
      <RunProcess key={`progress:${run.run_id}`} value={run.process} api={api} root={root} presentation="conversation" onUnavailable={sourceUnavailable} />
      {(!active || !run.process || run.result?.summary) && <PaiResponse run={run} />}

      <RunReconciliation key={run.run_id} api={api} root={root} run={run} onSettled={async () => { await readRun(run.run_id); }} />

      <ResearchResult value={run.result?.result?.research} />
      <WorkProductActions run={run} items={workProducts.items} busy={workProducts.busy} onOpen={kind => { void workProducts.openFromRun(run, kind).then(product => { if (product) setMobileView("editor"); }); }} />
      <PaiUnfinished items={run.result?.unfinished} />
      {!run.reverted && run.status === "waiting_input" && <Button variant="ghost" disabled={busy || !!pending}
        onClick={() => void send({ path: `${root}/${run.run_id}/cancel`, body: {} })}>取消后续执行</Button>}
      {questions.length > 0 && <div ref={answerAnchor} tabIndex={-1}><ClarificationForm {...answerProps} prefix="inline" /></div>}
      <PaiReplyDetails key={`details:${run.run_id}`} scope="通用对话" skills={skills}><div className={styles.recordDetails}><h3 className="text-xs font-semibold">{reconciliationNeeded(run) ? "原调用结果待核对" : labels[run.status] ?? "状态待核对"}{run.reverted ? " · 已撤回" : ""}</h3>{run.error_code && <p>错误代码：{run.error_code}</p>}
      <p className={styles.runId}>运行 {run.run_id}</p>
      {run.process && <RunProcess key={`process:${run.run_id}`} value={run.process} api={api} root={root} />}
      <RunFeedback key={`feedback:${run.run_id}`} api={api} root={root} runId={run.run_id} />
      <Button variant="outline" disabled={busy} onClick={() => void read(() => readRun(run.run_id))}>刷新实际结果</Button>
      </div></PaiReplyDetails>
      </PaiMessage>
    </>}
    {run && backgroundRun !== run.run_id && adoptions.map(({ proof, category }) => <PaiDocumentCard key={proof.receipt_id} title={category.name} metadata="品类 · 已保存" action="返回编辑" onOpen={() => { setMobileView("editor"); setSavedCategory(category); requestAnimationFrame(() => savedDialog.current?.show()); }}><details className="px-3 pb-3 text-xs text-muted-foreground"><summary className="cursor-pointer">保存记录</summary><p>品类创建已完成，原候选已采用。</p><p className="break-all">创建回执：{proof.receipt_id}</p><p className="break-all">个人运行：{proof.run_id}</p><p className="break-all">候选摘要：{proof.candidate_digest}</p><p className="break-all">采用输入：{proof.input_ref}</p></details></PaiDocumentCard>)}
    <dialog ref={savedDialog} className="candidate-editor" aria-label="编辑已保存品类">{savedCategory && <><header className="candidate-editor-heading"><h3>{savedCategory.name}</h3><PaiMobileWorkspaceSwitch view="chat" onClick={() => setMobileView("chat")} /><Button size="sm" variant="ghost" onClick={() => { setMobileView("chat"); savedDialog.current?.close(); }}>收起材料</Button></header><div className="candidate-editor-body"><CategoryMetadataEditor key={savedCategory.id} categoryId={savedCategory.id} api={api} embedded/></div></>}</dialog>
    {run && backgroundRun !== run.run_id && candidates.map(candidate => <PaiDocumentCard key={candidate.candidate_digest} title={candidate.input.name} metadata="品类 · 小Pai 起草 · 待确认" action="查看与编辑" onOpen={() => { setMobileView("editor"); setMaterial({ runId: run.run_id, candidate, sourceRun: run }); requestAnimationFrame(() => materialDialog.current?.show()); }} />)}
    <dialog ref={materialDialog} className="candidate-editor" aria-label="品类材料编辑">{material && <><header className="candidate-editor-heading"><h3>{material.candidate.input.name}</h3><PaiMobileWorkspaceSwitch view="chat" onClick={() => setMobileView("chat")} /><Button size="sm" variant="ghost" onClick={() => { setMobileView("chat"); materialDialog.current?.close(); }}>收起材料</Button></header><div className="candidate-editor-body"><CategoryCreateForm key={`${material.runId}:${material.candidate.candidate_digest}`} candidate={material.candidate} runId={material.runId} api={api} onCreated={onCreated}
      draft={confirmationDrafts[`${material.runId}:${material.candidate.candidate_digest}`]} onDraftChange={draft => setConfirmationDrafts(old => {
        const key = `${material.runId}:${material.candidate.candidate_digest}`;
        if (draft) return { ...old, [key]: draft };
        const next = { ...old }; delete next[key]; return next;
      })}
      disabled={busy || !!pending || material.sourceRun.reverted || material.candidate.cancel_epoch !== material.sourceRun.cancel_epoch || !["queued", "running", "waiting_input", "completed", "partial"].includes(material.sourceRun.status)} /></div></>}</dialog>
    {run && backgroundRun !== run.run_id && questions.length > 0 && <ClarificationDialog {...answerProps} open={questionDialog} onClose={() => setQuestionDialog(false)}
      onReturnFocus={() => answerAnchor.current?.focus()} />}
        </div>
        <div className={styles.composer}>
          {run && <div className={styles.continuation}><RunContinuation onStop={active ? () => { void send({ path: `${root}/${run.run_id}/cancel`, body: {} }); } : undefined} presentation="composer" disabled={busy || !!pending} key={`continue:${run.run_id}`} api={api} root={root} run={run} principalId={principalId} onUnavailable={sourceUnavailable} onOpen={async id => { await readRun(id); setHistoryVersion(value => value + 1); }} /></div>}
          {!run && <div className={styles.chatContinuation}><PaiComposer value={goal} onChange={setGoal} onSubmit={() => void send({ path: root, body: { goal, idempotency_key: crypto.randomUUID(), sources: [], ...(requestedSkills.length ? { requested_skills: requestedSkills } : {}) } })}
            disabled={busy || !!pending} inputRef={composer}
            tools={<><SkillPicker api={api} resource="v1/personal/agent-skills" value={requestedSkills} onChange={setRequestedSkills} disabled={busy || !!pending}/><PaiCarry scope="个人工作" objects={requestedSkills.map(skill => `优先技能 ${skillTitle(skill.key)} · ${skill.version}`)} /></>} /></div>}
        </div>
      </div>
    </div>
  </section>;
}
