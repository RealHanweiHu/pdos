"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { At, FileText, Paperclip, Plus } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { PaiComposer } from "@/components/pai/composer";
import { clearPaiComposerDrafts, useSessionDraft, writePaiComposerDraft } from "@/components/pai/use-session-draft";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import { proofClockCurrent } from "@/lib/proof-clock";
import { RunFeedback } from "@/components/pai/run-feedback";
import { RunContinuation } from "@/components/pai/run-continuation";
import { RunProcess } from "@/components/pai/run-process";
import type { RunProcessData } from "@/lib/run-process";
import { RunReconciliation } from "@/components/pai/run-reconciliation";
import { reconciliationNeeded } from "@/lib/run-reconciliation";
import { RunCandidates } from "@/components/pai/run-candidates";
import { WorkFollowupAction } from "@/components/pai/work-followup-action";
import { VerificationPreparationAction } from "@/components/pai/verification-preparation-action";
import { PersonalSummaryRunResult } from "@/components/pai/personal-summary-result";
import { ResearchResult } from "@/components/pai/research-result";
import { restoreRunStart } from "@/lib/run-start-intent";
import { usePaiScroll, loadedSkillFacts, PaiCarry, PaiMessage, PaiUnfinished, PaiResponse, PaiReplyDetails, PaiGoal, PaiScope, PaiWelcome, PaiContextBar, PaiMobileWorkspaceSwitch, PaiHiddenResponse } from "@/components/pai-conversation";
import { assertHiddenRun, type PaiHiddenRun, type PaiRunStatus } from "@/lib/pai-sessions";
import type { LoadedSkill } from "@/components/pai-conversation";
import { ConversationHistory } from "@/components/pai/conversation-history";
import { SessionHistory } from "@/components/pai/session-history";
import { FileUpload } from "@/components/pai/file-upload";
import { SkillPicker } from "@/components/pai/skill-picker";
import type { RequestedSkill } from "@/lib/run-start-intent";
import { RunSourceBindings, SourcePicker, sourcePickerScope } from "@/components/pai/source-picker";
import { WorkProductActions } from "@/components/pai/work-product-actions";
import { WorkProductEditor } from "@/components/pai/work-product-editor";
import { useWorkProducts } from "@/components/pai/use-work-products";
import { browserApi } from "@/lib/browser-api";
import type { SourceSelection } from "@/components/pai/source-picker";
import styles from "./pai-conversation.module.css";
import { useAnswerResume } from "./pai/use-answer-resume";
import { collapsedAnswerCitations, type AnswerExclusions } from "@/lib/answer-followup";

type Source = { id: string; title: string; revision: number; status: string };
type Question = { id: string; question: string; why: string; options: { value: string; label: string }[]; allow_free_text: boolean };
type ReadableRun = { session_id: string; session_proposal_id?: string | null; goal?: string; conversation?: {previous_run_id:string|null;next_run_id:string|null}; process?: RunProcessData; reconciliation?: unknown; run_id: string; product_id: string | null; project_id?: string | null; proposal_id?: string | null; cancel_epoch: number; status: Exclude<PaiRunStatus, "hidden">; history_hidden?: false; error_code: string | null; reverted: boolean; result: { summary?: string; unfinished?: string[]; result?: Record<string, unknown> } };
type Run = ReadableRun | PaiHiddenRun;
type Candidate = { command: Record<string, unknown> & { payload: { statement: string; quote: string; prepared_event_id: string } }; event_id: string };
type Event = { id?: string; sequence: number; event: { type: string; key?: string; version?: string; questions?: Question[]; status?: string; command?: Candidate["command"]; prepared_event_id?: string } };
type Pending = { path: string; body: unknown };
const labels: Record<string, string> = { queued: "已保存，等待执行", running: "正在执行", waiting_input: "等待你的答复", completed: "已完成", partial: "已形成部分结果", cancelled: "已取消后续执行", failed: "执行未完成" };

/** Runs and events are server facts. Reading or reopening this panel never starts inference. */
import { PaiProposalWorkspace } from "@/components/pai/proposal-workspace";
import { PaiMaterialWorkspace } from "@/components/pai/material-workspace";
import { clearMaterialJournals } from "@/lib/category-materials";
import type { DomainCandidate } from "@/lib/domain-candidate";
import type { MaterialContext } from "./category-material-editor";
import { materialContextText, withMaterialContext } from "@/lib/pai-material-context";
import { defaultSearchPreferences, type SearchPreferences } from "@/lib/search-preferences";
import { SearchScope } from "@/components/pai/search-scope";

type Props = { fullPage?: boolean; contextControl?: ReactNode; headerActions?: ReactNode;
  materialContext?: MaterialContext;
  api: WorkspaceTransport; productId: string; sources: Source[]; composeOpen: boolean; onComposeChange: (open: boolean) => void;
  initialRunId?: string; proposalId?: string; projectId?: string; projectName?: string;
  categoryId: string; categoryName?: string; proposalTitle?: string; principalId: string; onBackground?: () => void;
};
export function Xiaopai(props: Props) {
  const [binding, setBinding] = useState({ api: props.api, revision: 0 });
  if (binding.api !== props.api) { setBinding({ api: props.api, revision: binding.revision + 1 }); return null; }
  return <ScopedXiaopai key={`${binding.revision}:${props.principalId}:${props.categoryId}:${props.productId}:${props.proposalId ?? ""}:${props.projectId ?? ""}`} {...props} />;
}
function ScopedXiaopai({ api, productId, onComposeChange, initialRunId, categoryId, categoryName, principalId, proposalId, projectId, projectName, proposalTitle, onBackground, materialContext, fullPage = false, contextControl, headerActions }: Props) {
  const [answerExclusions, setAnswerExclusions] = useState<AnswerExclusions | null>(null);
  const draftScope = `${categoryId}:${productId}:${proposalId ?? ""}:${projectId ?? ""}`;
  const [carryMaterial, setCarryMaterial] = useState(true);
  const [materialDenied, setMaterialDenied] = useState(false);
  const [materialDocuments, setMaterialDocuments] = useState<DomainCandidate[]>([]);
  const [editingMaterial, setEditingMaterial] = useState<string | null>(null);
  const [mobileView, setMobileView] = useState<"chat" | "editor">("chat");
  const [editorContexts, setEditorContexts] = useState<Record<string, MaterialContext | undefined>>({});
  const openMaterial = useCallback((candidate: DomainCandidate) => {
    setMaterialDocuments(old => old.some(doc => doc.event_id === candidate.event_id) ? old : [...old, candidate]);
    setEditingMaterial(candidate.event_id); setMobileView("editor");
  }, []);
  const updateEditorContext = useCallback((id: string, context: MaterialContext | undefined) => setEditorContexts(old => ({ ...old, [id]: context })), []);
  const [materialVersion, setMaterialVersion] = useState(0);
  const currentMaterial = editingMaterial ? editorContexts[editingMaterial] : materialContext;
  const pageMaterial = carryMaterial && !materialDenied ? materialContextText(currentMaterial) : "";
  const [requestedSkills, setRequestedSkills] = useState<RequestedSkill[]>([]);
  const [searchPreferences, setSearchPreferences] = useState<SearchPreferences>({ ...defaultSearchPreferences });
  const [useProduct, setUseProduct] = useState(false);
  const [selected, setSelected] = useState<SourceSelection | null>(null);
  const [sourceReadVersion, setSourceReadVersion] = useState(0);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [goal, setGoal] = useSessionDraft(principalId, draftScope, sessionId);
  const [run, setRun] = useState<Run | null>(null);
  const panel = useRef<HTMLElement | null>(null);
  usePaiScroll(panel, run?.run_id);
  const [skills, setSkills] = useState<LoadedSkill[]>([]);
  const [historyOpen, setHistoryOpen] = useState(() => fullPage && typeof window !== "undefined" && window.innerWidth >= 1000);
  const [backgroundRun, setBackgroundRun] = useState<string | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const { pending: resumingAnswers, accepted: resumeAccepted, observe: observeResume, waiting: resumeWaiting, clear: clearResumes } = useAnswerResume();
  const questionIdentity = useRef<string | null>(null);
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
    setEditingMaterial(null); setMaterialDocuments([]); setEditorContexts({}); setMobileView("chat");
    setSessionId(null); setSelectedRunId(null); setRun(null); setSkills([]); setQuestions([]); setAnswers({}); questionIdentity.current = null;
    setCandidates([]); setAdoption(null); setRevert(null); setEventSequence(0); setBackgroundRun(null);
    setSearchPreferences({ ...defaultSearchPreferences });
  }, []);
  const sourceUnavailable = useCallback(() => { clearResumes(); clearPaiComposerDrafts(principalId); clearMaterialJournals(principalId, categoryId); setGoal(""); setMaterialDenied(true); setEditingMaterial(null); setMaterialDocuments([]); setEditorContexts({}); setSelected(null); setSourceReadVersion(version => version + 1); clearSelection(); setError("当前来源或运行范围无法核对，已清除旧资料；请重新读取。"); }, [clearSelection, clearResumes, principalId, categoryId, setGoal]);
  const workProducts = useWorkProducts(browserApi, sourceUnavailable);
  const { load: loadWorkProducts, clear: clearWorkProducts } = workProducts;
  useEffect(() => {
    if (run?.session_id && run.status !== "hidden") void loadWorkProducts(run.session_id);
  }, [run?.session_id, run?.status, loadWorkProducts]);
  useEffect(() => {
    if (!run || run.status === "hidden") clearWorkProducts();
  }, [run, clearWorkProducts]);
  const materialRequest = useRef("");
  useEffect(() => {
    const request = materialContext?.request;
    if (!request || request.id === materialRequest.current) return;
    materialRequest.current = request.id;
    // A page action opens a fresh composer; no inference starts until Send.
    clearSelection(); writePaiComposerDraft(principalId, draftScope, null, request.prompt); onComposeChange(true);
  }, [materialContext?.request, clearSelection, onComposeChange, principalId, draftScope]);
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
    if (current.current !== id) { questionIdentity.current = null; setRun(null); setSkills([]); setQuestions([]); setAnswers({}); setCandidates([]); setAdoption(null); setRevert(null); setEventSequence(0); }
    const own = ++generation.current;
    current.current = id; setSelectedRunId(id);
    try {
    const value = await api<Run>(`v1/agent-runs/${id}`);
    if (own !== generation.current) return;
    if (value.run_id !== id || typeof value.session_id !== "string" || !value.session_id || expected && value.session_id !== expected) throw new Error("读取结果与所选会话或运行不一致，请重新选择。 ");
    if (proposalId && value.proposal_id !== proposalId && (value.proposal_id !== null || value.session_proposal_id !== proposalId)) throw new Error("运行不属于当前提案，请刷新本提案的运行历史。");
    if (value.status === "hidden") {
      assertHiddenRun(value);
      selectedSession.current = value.session_id; setSessionId(value.session_id); setRun(value);
      setSkills([]); setQuestions([]); setAnswers({}); setCandidates([]); setAdoption(null);
      setRevert(null); setEventSequence(0); questionIdentity.current = null; clearResumes();
      setEditingMaterial(null); setMaterialDocuments([]); setEditorContexts({}); setSelected(null);
      setMaterialDenied(true); setBackgroundRun(null);
      return;
    }
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
    setMaterialDenied(false);
    const latestInput = [...events].reverse().find(item => item.event.type === "needs_input");
    const currentQuestions = value.status === "waiting_input" && !value.reverted && !reconciliationNeeded(value) ? latestInput?.event.questions ?? [] : [];
    const identity = currentQuestions.length && latestInput ? `${id}:${latestInput.sequence}` : null;
    if (identity !== questionIdentity.current) { setAnswers({}); questionIdentity.current = identity; }
    if (resumeWaiting(id)) setError("");
    if (observeResume(id, value.status, value.reverted, identity)) setNotice("");
    setQuestions(currentQuestions);
    } catch (failure) { if (own === generation.current) { if ([401, 403].includes((failure as { status?: number }).status ?? 0)) sourceUnavailable(); setRun(null); setSkills([]); setQuestions([]); setAnswers({}); setCandidates([]); setAdoption(null); setRevert(null); setEventSequence(0); setSelected(null); if ((failure as { status?: number }).status !== 503) setSourceReadVersion(version => version + 1); throw failure; } }
  }, [api, proposalId, sourceUnavailable, observeResume, resumeWaiting, clearResumes]);
  useEffect(() => {
    if (!initialRunId) return;
    let active = true;
    void Promise.resolve().then(() => { if (active) { clearSelection(); return readRun(initialRunId).catch(failure => { if (active) setError(failure.message); }); } });
    return () => { active = false; };
  }, [initialRunId, readRun, clearSelection]);
  const resumingRunId = selectedRunId && resumingAnswers[selectedRunId] ? selectedRunId : null;
  useEffect(() => {
    const id = run?.run_id ?? resumingRunId;
    if (!id || !resumingRunId && (!run || run.reverted || !["queued", "running"].includes(run.status) && !reconciliationNeeded(run))) return;
    let reading = false;
    const timer = setInterval(() => {
      if (writeLock.current || reading) return;
      reading = true;
      void readRun(id).catch(failure => setError(failure.message)).finally(() => { reading = false; });
    }, 3000);
    return () => clearInterval(timer);
  }, [run, resumingRunId, readRun]);

  async function send(value: Pending) {
    const answeredRunId = current.current && value.path === `v1/agent-runs/${current.current}/answers` ? current.current : null;
    const answeredInput = answeredRunId ? questionIdentity.current : null;
    if (writeLock.current || answeredRunId && (!answeredInput || resumeWaiting(answeredRunId))) return;
    writeLock.current = true;
    request.current = value; setPending(value); setBusy(true); setError(""); setNotice("");
    generation.current++;
    let accepted = false;
    if (value.path === "v1/agent-runs") {
      clearSelection();
      try { localStorage.setItem(startStorageKey, JSON.stringify(value)); } catch { /* In-memory original remains available. */ }
    }
    try {
      const result = await api<{ run_id: string; continued_from_id?: string | null; execution_state?: string; workflow_cancel_pending?: boolean; status?: string; answer_ref?: string }>(value.path, value.body);
      if (!mounted.current) return;
      if (value.path === "v1/agent-runs" && !result.run_id) throw new Error("运行受理结果尚未核对，请重试原请求。");
      const started = value.body as { continue_from_run_id?: string; verification_action?: unknown };
      if (value.path === "v1/agent-runs" && started.verification_action && result.continued_from_id !== started.continue_from_run_id) throw new Error("后续受理结果尚未核对，请保留原请求。");
      if (answeredRunId) {
        if (result.run_id !== answeredRunId || result.status !== "resume_requested" || !result.answer_ref) throw new Error("答复受理结果尚未核对，请保留原请求重试。");
        resumeAccepted(answeredRunId, answeredInput!);
      }
      accepted = true;
      request.current = null; setPending(null);
      if (value.path === "v1/agent-runs") { try { localStorage.removeItem(startStorageKey); } catch { /* Optional storage. */ } }
      setNotice(result.execution_state === "durable_runtime_unavailable" ? "运行已保存，持久执行服务暂不可用。恢复后会继续派送。" : result.workflow_cancel_pending ? "取消已记录，正在通知执行服务。" : "");
      if (value.path === "v1/agent-runs") { setGoal(""); setSelected(null); setRequestedSkills([]); setBackgroundRun(null); onComposeChange(false); }
      if (answeredRunId) setNotice("答复已提交，正在等待继续执行；无需重复答复。");
      else setAnswers({});
      await readRun(result.run_id ?? current.current!);
      setHistoryVersion(value => value + 1);
    } catch (failure) {
      if (!mounted.current) return;
      const status = (failure as { status?: number }).status;
      if (status === 401 || status === 403 || (value.path !== "v1/agent-runs" || accepted) && status === 404) sourceUnavailable();
      if (accepted && value.path === "v1/agent-runs") setNotice("新工作已保存，实际运行资料暂不可读；不会重新提交原委派。");
      if (!accepted && value.path === "v1/agent-runs" && status && status >= 400 && status < 500 && status !== 408 && status !== 429) {
        request.current = null; setPending(null); setSelected(null); setRequestedSkills([]); setSourceReadVersion(version => version + 1);
        setNotice("原新工作请求已被明确拒绝，请重新核对范围并选择固定来源和技能后再发送。");
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
  const runSourceScope = run ? { principalId, categoryId, productId: run.product_id, proposalId: run.proposal_id ?? null } : sourceScope;
  const selectedSources = selected?.scope === sourcePickerScope(sourceScope) ? selected.items : [];
  const continuationSources = selected?.scope === sourcePickerScope(runSourceScope) ? selected.items.map(({ artifact_id, expected_revision }) => ({ artifact_id, expected_revision })) : [];
  const categoryScope = categoryName || "当前品类";
  const requestScope = `${categoryScope}${projectId ? ` · ${projectName || "当前项目"}` : ""}${proposalId ? ` · ${proposalTitle || "当前提案"}` : ""}`;
  const runScope = `${categoryScope}${run?.project_id ? ` · ${run.project_id === projectId ? projectName || "当前项目" : "关联项目"}` : ""}${run?.proposal_id ? ` · ${run.proposal_id === proposalId ? proposalTitle || "当前提案" : "运行绑定提案"}` : ""}${run?.product_id ? " · 运行绑定型号" : ""}`;
  const runContextHref = run?.proposal_id ? `/categories/${categoryId}/proposals/${run.proposal_id}` : run?.project_id ? `/?area=cockpit&category=${categoryId}&project=${run.project_id}` : `/?area=category&category=${categoryId}`;
  const runGoal = run?.goal;
  const active = !!run && run.status !== "hidden" && !run.reverted && (["queued", "running"].includes(run.status) || resumingRunId === run.run_id);

  return <section ref={panel} className={styles.workspace} data-history-open={historyOpen} data-full-page={fullPage} data-mobile-view={mobileView} data-editor-open={!!(editingMaterial || workProducts.openProduct)} aria-label="小Pai工作区">
    {!materialDenied && materialDocuments.map(candidate => { const Editor = ["proposal.create", "proposal.item.patch"].includes(candidate.operation ?? "") ? PaiProposalWorkspace : PaiMaterialWorkspace; return <Editor key={candidate.event_id} candidate={candidate} categoryId={categoryId} principalId={principalId} open={editingMaterial === candidate.event_id} onClose={() => { setEditingMaterial(null); setMobileView("chat"); }} onMobileChat={() => setMobileView("chat")} onContextChange={updateEditorContext} onUnavailable={sourceUnavailable} onSaved={() => { setMaterialVersion(value => value + 1); window.dispatchEvent(new CustomEvent("pdos:category-material-saved", { detail: { categoryId } })); }} />; })}
    {workProducts.openProduct && <WorkProductEditor key={workProducts.openProduct.root_id} product={workProducts.openProduct} original={workProducts.original} open onClose={() => { workProducts.close(); setMobileView("chat"); }} onSaved={workProducts.saved} onReload={workProducts.reload} onUnavailable={sourceUnavailable} onMobileChat={() => setMobileView("chat")} />}

    <div className={styles.layout}>
      <aside className={styles.history} aria-label="小Pai会话列表">
        <div className={styles.historyHeading}><strong>会话</strong><button type="button" className={styles.historyBack} onClick={() => setHistoryOpen(false)}>返回对话</button></div>
        <Button variant="ghost" className={styles.newWork} disabled={busy || !!pending} onClick={() => { clearSelection(); onComposeChange(true); setHistoryOpen(fullPage && window.innerWidth >= 1000); }}><Plus size={14} aria-hidden="true" />新对话</Button>
        <SessionHistory api={api} scope={{ categoryId, proposalId, ...(projectId ? { projectId } : {}) }} principalId={principalId} currentSessionId={sessionId} currentRunId={selectedRunId} refreshVersion={historyVersion} disabled={busy || !!pending} onClearSelection={clearSelection} onPermissionDenied={sourceUnavailable} onSelectRun={(id, sid) => { clearSelection(); selectedSession.current = sid; setSessionId(sid); setHistoryOpen(fullPage && window.innerWidth >= 1000); void read(() => readRun(id, sid)); }} />
        <p className={styles.historyPrivacy}>私人会话 · 仅你可见</p>
      </aside>
      <div className={styles.conversation}>
    <PaiScope onBackground={active ? () => { if (onBackground) onBackground(); else setBackgroundRun(run.run_id); setNotice("已在后台继续，可从会话记录返回。"); } : undefined} actions={headerActions} scope={run ? runScope : requestScope} skills={skills} hasRun={!!run && run.status !== "hidden"} title={runGoal} disabled={busy || !!pending} onNewConversation={() => { clearSelection(); setGoal(""); setHistoryOpen(fullPage && window.innerWidth >= 1000); setEditingMaterial(null); onComposeChange(true); }} historyOpen={historyOpen} onHistoryToggle={() => setHistoryOpen(value => !value)} />
        <PaiContextBar scope={requestScope} control={contextControl}/>
        {(editingMaterial || workProducts.openProduct) && <PaiMobileWorkspaceSwitch view="editor" onClick={() => setMobileView("editor")} />}
        <div className={styles.thread} aria-label="小Pai 对话线程">
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-xs">{notice}</p>}
          {!!pendingStart?.body.requested_skills?.length && <p className="text-xs break-words">原请求优先技能：{pendingStart.body.requested_skills.map(skill => `${skill.key} · ${skill.version}`).join("；")}。恢复仍使用这些固定版本。</p>}
          {pending && run?.status !== "hidden" && !busy && <div className="rounded-lg border p-3 text-sm"><p>原请求仍待核对，输入暂时保留。</p>{pendingStart && <><p className="mt-2 text-xs">原请求携带 {(pendingStart.body.sources ?? []).length} 份固定来源；以下是原请求范围，不是当前输入框的选择。</p><details className="mt-2 text-xs"><summary>原请求固定范围与来源</summary><p className="break-all">品类：{categoryId}</p><p className="break-all">原绑定型号：{pendingStart.body.product_id ?? pendingStart.body.verification_action?.selection.product_id ?? "未关联型号"}</p><p className="break-all">原绑定提案：{pendingStart.body.proposal_id ?? "未关联提案"}</p><p className="break-all">原绑定项目：{pendingStart.body.project_id ?? pendingStart.body.verification_action?.selection.project_id ?? "未关联项目"}</p>{(pendingStart.body.sources ?? []).map(source => <p className="break-all" key={source.artifact_id}>登记来源 {source.artifact_id} · 固定版本 {source.expected_revision}</p>)}</details></>}<Button variant="outline" className="mt-3" disabled={busy} onClick={() => { if (request.current) void send(request.current); }}>重试原请求</Button></div>}
          {!run && selectedRunId && <Button variant="outline" disabled={busy || !!pending} onClick={() => void read(() => readRun(selectedRunId))}>核对所选运行</Button>}
          {!run && <PaiWelcome scope={requestScope} onSuggest={value => { setGoal(value); onComposeChange(true); }}/>}
          {run && backgroundRun === run.run_id && <div className="rounded-lg border p-3 text-sm"><p>工作已保留 · {labels[run.status] ?? "状态待核对"}</p><p className={styles.runId}>运行 {run.run_id}</p><Button className="mt-2" size="sm" variant="outline" onClick={() => setBackgroundRun(null)}>返回当前工作</Button></div>}
    {run?.status === "hidden" && <><PaiMessage from="user"><PaiGoal value={run.goal}/></PaiMessage><PaiMessage from="pai"><PaiHiddenResponse run={run}/></PaiMessage></>}
    {run && run.status !== "hidden" && backgroundRun !== run.run_id && <div className="contents">
      <ConversationHistory scope={runScope} contextHref={runContextHref} api={api} root={"v1/agent-runs"} sessionId={run.session_id} previousRunId={run.conversation?.previous_run_id ?? null} renderMaterials={historyRun => <><RunCandidates api={api} categoryName={categoryName} materialContexts={editorContexts} editingMaterial={editingMaterial} categoryId={categoryId} principalId={principalId} runId={historyRun.run_id} eventSequence={materialVersion} disabled={busy || !!pending} onUnavailable={sourceUnavailable} onEditMaterial={openMaterial} /><WorkProductActions run={historyRun} items={workProducts.items} busy={workProducts.busy} onOpen={kind => { void workProducts.openFromRun(historyRun, kind).then(product => { if (product) setMobileView("editor"); }); }} /></>} onUnavailable={sourceUnavailable} onOpen={id => { void read(() => readRun(id)); }} />
      {runGoal && <PaiMessage from="user"><PaiGoal value={runGoal}/></PaiMessage>}
      <PaiMessage from="pai">
      <RunProcess key={`progress:${run.run_id}`} value={run.process} api={api} root="v1/agent-runs" presentation="conversation" onUnavailable={sourceUnavailable} />
      {(!active || !run.process || run.result?.summary) && <PaiResponse run={run} collapsedCitationIds={collapsedAnswerCitations(run.result?.result?.assistant, answerExclusions, run.run_id)} />}
      {!run.reverted && ["completed", "partial"].includes(run.status) && <PersonalSummaryRunResult output={run.result} principalId={principalId}/>}

      <ResearchResult value={run.result?.result?.research} />
      {projectId && run.project_id === projectId && !run.reconciliation && <VerificationPreparationAction key={`verification:${run.run_id}`} api={api} categoryId={categoryId} run={run} disabled={busy || !!pending || !!run.conversation?.next_run_id} additionalSources={continuationSources} initialBuildId={typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("build") ?? undefined : undefined} onUnavailable={sourceUnavailable} onStart={value => { void send(value); }}/>}
      {projectId && run.project_id === projectId && !run.reconciliation && <WorkFollowupAction key={`work-followup:${run.run_id}`} api={api} categoryId={categoryId} principalId={principalId} run={run} disabled={busy || !!pending || !!run.conversation?.next_run_id} additionalSources={continuationSources} onUnavailable={sourceUnavailable} onStart={value => { void send(value); }}/> }
      <WorkProductActions run={run} items={workProducts.items} busy={workProducts.busy} onOpen={kind => { void workProducts.openFromRun(run, kind).then(product => { if (product) setMobileView("editor"); }); }} />
      <RunReconciliation key={run.run_id} api={api} root="v1/agent-runs" run={run} onSettled={() => readRun(run.run_id)} />
      <PaiUnfinished items={run.result?.unfinished} />
      {!run.reverted && run.status !== "cancelled" && candidates.map(candidate => <section key={candidate.event_id} className="rounded-lg border p-3 space-y-3"><h3 className="font-medium">待你确认的来源事实</h3><p>{candidate.command.payload.statement}</p><blockquote className="text-sm text-muted-foreground">{candidate.command.payload.quote}</blockquote><Button variant="outline" disabled={busy || !!pending} onClick={() => void read(async () => { setAdoption(await api("v1/commands/preview", candidate.command)); })}>核对并预览此事实</Button></section>)}
      {adoption && <section className="rounded-lg border p-3 space-y-3"><p>{adoption.review.effect}</p><Button disabled={busy || !!pending || !proofClockCurrent("T1", adoption.expires_at)} onClick={() => void send({ path: "v1/commands", body: adoption.command })}>确认登记此事实</Button></section>}
      {!run.reconciliation && <RunCandidates api={api} categoryName={categoryName} materialContexts={editorContexts} editingMaterial={editingMaterial} categoryId={categoryId} principalId={principalId} runId={run.run_id} eventSequence={eventSequence + materialVersion} disabled={busy || !!pending} onUnavailable={sourceUnavailable} onEditMaterial={openMaterial} />}
      {questions.length > 0 && <form onSubmit={event => { event.preventDefault(); void send({ path: `v1/agent-runs/${run.run_id}/answers`, body: { answers, idempotency_key: crypto.randomUUID() } }); }}><fieldset disabled={busy || !!pending || !!resumingRunId}>
        {questions.map(question => <div key={question.id} className="mb-4"><label htmlFor={`pai-${question.id}`}>{question.question}</label><p className="subtle mb-2">{question.why}</p>{question.allow_free_text ? <><input id={`pai-${question.id}`} list={`pai-options-${question.id}`} required value={answers[question.id] ?? ""} onChange={event => setAnswers(old => ({ ...old, [question.id]: event.target.value }))} /><datalist id={`pai-options-${question.id}`}>{question.options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</datalist></> : <select id={`pai-${question.id}`} required value={answers[question.id] ?? ""} onChange={event => setAnswers(old => ({ ...old, [question.id]: event.target.value }))}><option value="">请选择</option>{question.options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select>}</div>)}
        <Button>提交答复并继续</Button>
      </fieldset></form>}


      <PaiReplyDetails key={`details:${run.run_id}`} scope={runScope} skills={skills} contextHref={runContextHref}><div className={styles.recordDetails}><div className={styles.runHeader}><span>{run.reverted ? "已整次撤回" : reconciliationNeeded(run) ? "原调用结果待核对" : resumingRunId === run.run_id ? "答复已提交，等待继续执行" : labels[run.status] ?? "状态待核对"}</span><Button size="sm" variant="ghost" disabled={busy} onClick={() => void read(() => readRun(run.run_id))}>核对当前状态</Button></div>{run.error_code && <p>错误代码：{run.error_code}</p>}
      {!run.reverted && ["queued", "running", "waiting_input"].includes(run.status) && <details><summary className="cursor-pointer text-sm">取消此次运行</summary><p className="subtle my-3">停止后续动作，已经形成的结果和回执保留。</p><Button variant="outline" disabled={busy || !!pending} onClick={() => void send({ path: `v1/agent-runs/${run.run_id}/cancel`, body: {} })}>确认取消后续执行</Button></details>}
      <details className={styles.runDetails}><summary>引用资料</summary><p className={styles.runId}>运行 {run.run_id}</p><RunSourceBindings api={api} scope={{ principalId, categoryId, productId: run.product_id, proposalId: run.proposal_id ?? null }} runId={run.run_id} sessionId={run.session_id} onUnavailable={sourceUnavailable} /></details>
      {run.process && <RunProcess key={`process:${run.run_id}`} value={run.process} api={api} root="v1/agent-runs" />}
      <RunFeedback key={`feedback:${run.run_id}`} api={api} root="v1/agent-runs" runId={run.run_id} />
      {run.result?.result && Object.keys(run.result.result).length > 0 && <details><summary className="cursor-pointer">查看实际结果与回执</summary><pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words text-sm">{JSON.stringify(run.result.result, null, 2)}</pre></details>}
      {!run.reverted && <details><summary className="cursor-pointer text-sm">整次撤回草稿结果</summary><p className="subtle my-3">先核对全部结果及后续引用，再一次确认撤回。</p><Button variant="outline" disabled={busy || !!pending} onClick={() => void read(async () => {
        setRevert(await api("v1/commands/preview", { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation: "ai.run.revert", product_id: run.product_id, expected_revision: run.cancel_epoch + 1, source_read_set: [], payload: { run_id: run.run_id } }));
      })}>预览整次撤回</Button>{revert && <div className="mt-4 space-y-3"><p>{revert.review.effect}</p><p className="subtle">本次包含 {revert.review.receipts.length} 条结果回执。</p><Button disabled={busy || !!pending || !proofClockCurrent("T1", revert.expires_at)} onClick={() => void send({ path: "v1/commands", body: revert.command })}>确认整次撤回</Button></div>}</details>}
      </div></PaiReplyDetails>
      </PaiMessage>
    </div>}
        </div>
        <div className={styles.composer}>
          {run && run.status !== "hidden" && <div className={styles.continuation}><RunContinuation categoryId={categoryId} onStop={active ? () => { void send({ path: `v1/agent-runs/${run.run_id}/cancel`, body: {} }); } : undefined} presentation="composer" answerActions={!!run.result?.summary && !run.reconciliation} onAnswerExclusions={setAnswerExclusions} contextControl={contextControl} disabled={busy || !!pending} key={`continue:${run.run_id}`} api={api} root="v1/agent-runs" run={run} additionalSources={continuationSources} sourceTools={<details className={styles.attachments}><summary aria-label="添加附件" title="添加附件"><Paperclip size={14} aria-hidden="true"/></summary><div><FileUpload api={api} scope={runSourceScope} disabled={busy || !!pending} /><SourcePicker key={`continuation-sources:${sourceReadVersion}`} api={api} scope={runSourceScope} value={selected} onChange={setSelected} disabled={busy || !!pending} /></div></details>} contextText={pageMaterial} contextLabel={currentMaterial && !materialDenied ? `${currentMaterial.title}${currentMaterial.version ? ` · v${currentMaterial.version}` : ""}` : undefined} principalId={principalId} onUnavailable={sourceUnavailable} onOpen={async (id, sid) => { if (sid) { clearSelection(); selectedSession.current = sid; setSessionId(sid); } await readRun(id, sid); setHistoryVersion(value => value + 1); }} /></div>}
          {!run && <div className={styles.chatContinuation}><PaiComposer value={goal} onChange={setGoal} onSubmit={() => {
              let submittedGoal: string; try { submittedGoal = withMaterialContext(goal, pageMaterial); } catch (failure) { setError((failure as Error).message); return; }
              void send({ path: "v1/agent-runs", body: { goal: submittedGoal, idempotency_key: crypto.randomUUID(), product_id: sourceScope.productId, ...(proposalId ? { proposal_id: proposalId } : {}), ...(projectId ? { project_id: projectId } : {}), ...(requestedSkills.length ? { requested_skills: requestedSkills } : {}), ...(projectId || proposalId ? { search_preferences: searchPreferences } : {}), sources: selectedSources.map(({ artifact_id, expected_revision }) => ({ artifact_id, expected_revision })) } });
            }} disabled={busy || !!pending}
            background={(projectId || proposalId) && <SearchScope label={requestScope} kind={proposalId ? "proposal" : "project"} value={searchPreferences} onChange={setSearchPreferences} disabled={busy || !!pending} control={contextControl}/>}
            tools={<>
              {productId && !proposalId && !projectId && <details className={styles.objectPicker}><summary><At size={13} aria-hidden="true" />对象</summary><div className={styles.objectOptions}><label><input type="checkbox" checked={useProduct} onChange={event => { setUseProduct(event.target.checked); setSelected(null); }} />关联当前型号</label></div></details>}
              <details className={styles.attachments}><summary aria-label="添加附件" title="添加附件"><Paperclip size={14} aria-hidden="true"/></summary><div><FileUpload api={api} scope={sourceScope} disabled={busy || !!pending} /><SourcePicker key={`sources:${sourceReadVersion}`} api={api} scope={sourceScope} value={selected} onChange={setSelected} disabled={busy || !!pending} /></div></details>
              <SkillPicker key={`skills:${sourceReadVersion}`} api={api} value={requestedSkills} onChange={setRequestedSkills} disabled={busy || !!pending}/>
              {currentMaterial && !materialDenied && <details className={styles.materialCarry}><summary title={`页面资料：${currentMaterial.title}`}><FileText size={13}/>当前资料</summary><div><label className="mt-2 flex gap-2"><input type="checkbox" checked={carryMaterial} onChange={event => setCarryMaterial(event.target.checked)}/>携带当前资料与未保存编辑</label><p className="text-muted-foreground">只随你发送的下一条消息提供，固定版本与权限由服务器重新核对。</p></div></details>}
              <PaiCarry scope={requestScope} objects={[...(projectId ? [`项目 ${projectName || projectId}`] : []), ...(sourceScope.productId ? [`型号 ${sourceScope.productId}`] : []), ...selectedSources.map(source => `${source.title} · 固定版本 ${source.expected_revision}`), ...requestedSkills.map(skill => `优先技能 ${skill.key} · ${skill.version}`)]} />
            </>} /></div>}
        </div>
      </div>
    </div>
  </section>;
}
