"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { withMaterialContext } from "@/lib/pai-material-context";
import { Button } from "@/components/ui/button";
import { ArrowClockwise, Folder } from "@phosphor-icons/react";
import { PaiComposer } from "./composer";
import { WorkStateCarry } from "./work-state-carry";
import { ContinuedSkillPicker } from "./continued-skill-picker";
import { ContextRestart } from "./context-restart";
import { validSkillSelections } from "@/lib/continued-skills";
import type { RequestedSkill } from "@/lib/run-start-intent";
import { AnswerKnowledgeActions } from "../knowledge/answer-knowledge";
import { AnswerFollowupActions } from "./answer-followup-actions";
import type { CorrectionWorkState } from "@/lib/answer-corrections";
import type { AnswerExclusions } from "@/lib/answer-followup";
import { clearPaiComposerDrafts, useSessionDraft } from "./use-session-draft";
import styles from "../pai-conversation.module.css";
import {
  matchesContinuation,
  restoreContinuation,
} from "@/lib/run-continuation";
import type {
  ContinuationReading,
  PendingContinuation,
  ContinuationSource,
  ContinuationRequest,
} from "@/lib/run-continuation";

type Api = <T>(path: string, body?: unknown) => Promise<T>;
type Run = {
  run_id: string;
  session_id: string;
  goal?: string;
  status: string;
  reverted: boolean;
  project_id?: string | null; proposal_id?: string | null;
  conversation?: { previous_run_id: string | null; next_run_id: string | null };
};
export function RunContinuation({
  api,
  root,
  run,
  onOpen,
  contextText = "",
  additionalSources = [],
  sourceTools,
  principalId,
  categoryId,
  onUnavailable,
  onStop,
  presentation = "details",
  contextLabel,
  contextControl,
  disabled = false,
  answerActions = false,
  onAnswerExclusions,
}: {
  answerActions?: boolean;
  onAnswerExclusions?: (value: AnswerExclusions) => void;
  presentation?: "details" | "composer";
  contextLabel?: string;
  contextControl?: ReactNode;
  disabled?: boolean;
  contextText?: string;
  additionalSources?: ContinuationSource[];
  sourceTools?: ReactNode;
  principalId?: string;
  categoryId?: string;
  onUnavailable?: () => void;
  onStop?: () => void;
  api: Api;
  root: string;
  run: Run;
  onOpen: (id: string, sessionId?: string) => Promise<unknown>;
}) {
  const [correctionState, setCorrectionState] = useState<CorrectionWorkState | null>(null);
  const [carryRefresh, setCarryRefresh] = useState(0);
  const [reading, setReading] = useState<ContinuationReading | null>(null);
  const [requestedSkills, setRequestedSkills] = useState<RequestedSkill[]>([]);
  const [excludedSkills, setExcludedSkills] = useState<string[]>([]);
  const [goal, setGoal] = useSessionDraft(principalId, root, run.session_id);
  const [pending, setPending] = useState<PendingContinuation | null>(null),
    [busy, setBusy] = useState(false);
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [denied, setDenied] = useState(false);
  const original = useRef<PendingContinuation | null>(null),
    storage = useRef<string | null>(
      principalId
        ? `pdos:continuation:${principalId}:${root}:${run.run_id}`
        : null,
    ),
    lock = useRef(false),
    generation = useRef(0);
  useEffect(() => {
    const counter = generation;
    return () => {
      counter.current++;
    };
  }, []);
  const remember = (value: PendingContinuation | null) => {
    original.current = value;
    setPending(value);
    if (storage.current)
      try {
        if (value) localStorage.setItem(storage.current, JSON.stringify(value));
        else localStorage.removeItem(storage.current);
      } catch {
        /* Keep exact original in memory. */
      }
  };
  const failure = (value: unknown) => {
    const status = (value as { status?: number }).status;
    setError(value instanceof Error ? value.message : "原工作暂不可读。");
    const reason = (value as { detail?: { reason?: string } }).detail?.reason;
    if (["requested_skill_unavailable", "requested_skill_version_changed", "continued_skill_selection_invalid"].includes(reason ?? "")) {
      remember(null);
      return; // A definite pre-acceptance refusal remains editable in this conversation.
    }
    if (status === 401 || status === 403) {
      if (principalId) clearPaiComposerDrafts(principalId);
      generation.current++;
      original.current = null;
      setPending(null);
      setGoal("");
      setReading(null);
      setNotice("");
      setDenied(true);
      lock.current = false;
      setBusy(false);
      if (storage.current)
        try {
          localStorage.removeItem(storage.current);
        } catch {
          /* Never render or resend inaccessible material. */
        }
      storage.current = null;
      onUnavailable?.();
    }
  };
  const inspect = async () => {
    const value = await api<ContinuationReading>(
      `${root}/${run.run_id}/continuation`,
    );
    if (
      value.run_id !== run.run_id ||
      (reading && reading.owner_id !== value.owner_id) ||
      value.continued_skills !== undefined && !validSkillSelections(value.continued_skills, 2) ||
      value.context_restart != null && (!Number.isSafeInteger(value.context_restart.expected_revision) || value.context_restart.expected_revision < 1)
    )
      throw new Error("后续工作与原运行不一致。");
    return value;
  };
  const load = async () => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    const own = generation.current;
    try {
      const value = await inspect();
      if (own !== generation.current) return;
      storage.current = `pdos:continuation:${value.owner_id}:${root}:${run.run_id}`;
      setReading(value);
      let request = original.current;
      if (!request)
        try {
          request = restoreContinuation(
            JSON.parse(localStorage.getItem(storage.current) ?? "null"),
            root,
            value.owner_id,
            run.run_id,
          );
        } catch {
          /* Original server record remains readable. */
        }
      if (request) {
        remember(request);
        setGoal(request.request.goal);
        setRequestedSkills(request.request.requested_skills ?? []);
        setExcludedSkills(request.request.excluded_continued_skills ?? []);
        if (matchesContinuation(request.request, value)) {
          remember(null);
          setGoal("");
          setNotice("已读回同一后续工作，未再次提交。");
        } else if (value.existing)
          throw new Error("原工作已有其他后续，请打开实际记录核对。");
      }
    } catch (error) {
      if (own === generation.current) failure(error);
    } finally {
      if (own === generation.current) {
        lock.current = false;
        setBusy(false);
      }
    }
  };
  const send = async (supplied?: ContinuationRequest, bubble = false) => {
    if (lock.current || !reading || disabled) { if (bubble) throw new Error("请先核对当前对话状态。"); return; }
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    const own = generation.current;
    try {
      const request = original.current ?? {
        root,
        owner_id: reading.owner_id,
        request: { ...(supplied ?? {
          goal: withMaterialContext(goal, contextText),
          idempotency_key: crypto.randomUUID(),
          continue_from_run_id: run.run_id,
          ...(additionalSources.length ? { sources: additionalSources.map(({ artifact_id, expected_revision }) => ({ artifact_id, expected_revision })) } : {}),
        }),
        ...(requestedSkills.length ? { requested_skills: requestedSkills } : {}),
        ...(excludedSkills.length ? { excluded_continued_skills: excludedSkills } : {}),
        },
      };
      if (!restoreContinuation(request, root, reading.owner_id, run.run_id)) throw new Error("原续接请求无法核对。");
      const latest = await inspect();
      if (own !== generation.current) return;
      if (latest.existing) {
        setReading(latest);
        if (!matchesContinuation(request.request, latest))
          throw new Error("原工作已有其他后续，请打开实际记录核对。");
        remember(null);
        setGoal("");
        setNotice("已读回同一后续工作，未再次提交。");
        return;
      }
      if (!latest.can_continue)
        throw new Error("原运行尚未结束或已撤回，请先核对当前状态。");
      remember(request);
      const result = await api<{
        run_id: string;
        continued_from_id: string | null;
        execution_state?: string;
      }>(root, request.request);
      if (own !== generation.current) return;
      if (result.continued_from_id !== run.run_id || !result.run_id)
        throw new Error("后续受理结果待核对，请保留原请求。");
      remember(null);
      setGoal("");
      setReading({
        ...latest,
        can_continue: false,
        existing: {
          run_id: result.run_id,
          goal: request.request.goal,
          idempotency_key: request.request.idempotency_key,
        },
      });
      setNotice(
        result.execution_state === "durable_runtime_unavailable"
          ? "后续工作已保存，执行服务恢复后继续。"
          : "后续工作已保存，可打开查看实际结果。",
      );
      await onOpen(result.run_id);
    } catch (error) {
      if (own === generation.current) failure(error);
      if (bubble) throw error;
    } finally {
      if (own === generation.current) {
        lock.current = false;
        setBusy(false);
      }
    }
  };
  const terminal = ["completed", "partial", "failed", "cancelled"].includes(run.status);
  const latestLoad = useRef(load);
  useEffect(() => { latestLoad.current = load; });
  useEffect(() => {
    let live = true;
    if (presentation === "composer" && terminal && !run.reverted)
      void Promise.resolve().then(() => { if (live) return latestLoad.current(); });
    return () => { live = false; };
  }, [presentation, run.run_id, terminal, run.reverted]);
  if (denied)
    return (
      <p role="alert">{error || "当前工作不可读，已清除本机续聊材料。"}</p>
    );
  if (presentation === "composer") {
    const canSend = !!reading?.can_continue && !reading.existing && !run.reverted && terminal;
    const canStop = !!onStop && !run.reverted && ["queued", "running"].includes(run.status);
    return <div className={styles.chatContinuation}>
      {error && <p role="alert" className={styles.composerError}>{error}</p>}
      {notice && <p role="status" className={styles.composerHint}>{notice}</p>}
      {answerActions && principalId && ["completed", "partial"].includes(run.status) && !run.reverted && <AnswerKnowledgeActions key={`knowledge:${run.run_id}`} api={api} categoryId={categoryId} principalId={principalId} runId={run.run_id} runRoot={root} disabled={disabled || busy || !!pending}/>}
      {answerActions && correctionState && canSend && !pending && <AnswerFollowupActions key={`answer-actions:${run.run_id}`} api={api} context={{ root, run, workState: correctionState }} disabled={disabled || busy} additionalSources={additionalSources.map(({ artifact_id, expected_revision }) => ({ artifact_id, expected_revision }))} onContinue={body => send(body, true)} onState={state => { setCorrectionState(state); setCarryRefresh(value => value + 1); }} onSnapshot={onAnswerExclusions} onUnavailable={onUnavailable}/> }
      {reading?.context_restart && terminal && !run.reverted && !pending && <ContextRestart api={api} root={root} runId={run.run_id} sessionId={run.session_id} revision={reading.context_restart.expected_revision} existing={reading.context_restart.existing} goal={goal.trim() || run.goal || "继续处理原目标。"} principalId={principalId} requested={requestedSkills} excluded={excludedSkills} disabled={disabled || busy} onOpen={onOpen} onUnavailable={onUnavailable} onBusy={setBusy}/>}
      {pending && !busy && !reading?.existing && <div className={styles.composerRecovery}><p>发送结果待核对，原消息已保留。</p><Button size="sm" variant="outline" disabled={disabled} onClick={() => void send()}>核对并重试原请求</Button></div>}
      {reading?.existing ? <div className={styles.composerRecovery}><p>这段对话已有后续消息。</p><Button size="sm" variant="outline" disabled={busy || disabled} onClick={() => void onOpen(reading.existing!.run_id).catch(failure => setError(failure.message))}>打开已保存的后续工作</Button></div> :
        <PaiComposer value={goal} onChange={setGoal} onSubmit={() => void send()}
          background={<WorkStateCarry background onChange={setCorrectionState} refreshVersion={`${run.run_id}:${terminal ? run.status : "pending"}:${carryRefresh}`} contextControl={contextControl} api={api} root={root} sessionId={run.session_id} disabled={disabled || busy || !terminal} onUnavailable={onUnavailable}/>}
          disabled={disabled} busy={busy} inputDisabled={!!pending || !canSend} sendDisabled={!!pending || !canSend}
          onStop={canStop ? () => onStop?.() : undefined}
          placeholder={run.reverted ? "此对话已撤回，请新建对话" : !terminal ? run.status === "waiting_input" ? "请先回答上方的问题…" : "小Pai正在处理…" : busy ? "正在读取对话…" : reading && !canSend ? "当前对话暂不能继续，请刷新状态或新建对话" : "发消息给小Pai…"}
          hint={canStop ? "小Pai正在处理，你可以先去忙别的" : "Enter 发送 · Shift Enter 换行"}
          tools={<>{sourceTools}<details className={styles.carry}><summary title={contextLabel || "沿用会话上下文"} aria-label="查看会话上下文"><Folder size={15} aria-hidden="true"/></summary><div><p>{contextLabel || "沿用会话上下文"}</p><p>继续本次对话，沿用原范围与来源。</p>{contextText && <p>同时带入当前资料与未保存编辑；保存仍需确认。</p>}{run.conversation?.previous_run_id && <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => void onOpen(run.conversation!.previous_run_id!).catch(failure => setError(failure.message))}>查看前一次工作</Button>}</div></details>
            <ContinuedSkillPicker api={api} resource={root.includes("personal") ? "v1/personal/agent-skills" : "v1/agent-skills"} continued={reading?.continued_skills ?? []} excluded={excludedSkills} onExcludedChange={setExcludedSkills} requested={requestedSkills} onRequestedChange={setRequestedSkills} disabled={disabled || busy || !!pending}/>
            <Button type="button" variant="ghost" size="sm" className={styles.toolbarButton} aria-label="读取后续记录" title="刷新对话状态" disabled={busy || disabled || !terminal || run.reverted} onClick={() => void load()}><ArrowClockwise size={14} aria-hidden="true"/></Button></>} />}
    </div>;
  }
  return (
    <div className="space-y-2 text-sm">
      {run.goal && (
        <p className="break-words font-medium">本次目标：{run.goal}</p>
      )}
      {run.conversation?.previous_run_id && (
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() =>
            void onOpen(run.conversation!.previous_run_id!).catch((failure) =>
              setError(failure.message),
            )
          }
        >
          查看前一次工作
        </Button>
      )}
      {run.conversation?.next_run_id && (
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() =>
            void onOpen(run.conversation!.next_run_id!).catch((failure) =>
              setError(failure.message),
            )
          }
        >
          打开后续工作
        </Button>
      )}
      {terminal && !run.reverted && (
        <details
          className="rounded-lg border p-3"
          onToggle={(event) => {
            if (event.currentTarget.open && !reading && !lock.current)
              void load();
          }}
        >
          <summary className="cursor-pointer font-medium">
            基于这次工作继续
          </summary>
          <div className="mt-3 space-y-3">
            <p className="subtle">
              补充目标或继续追问，沿用本人的原会话、对象与来源。旧结果保留；事实与权限在继续前重新核对。
            </p>
            {error && <p role="alert">{error}</p>}
            {notice && <p role="status">{notice}</p>}
            {reading?.context_restart && !pending && <ContextRestart api={api} root={root} runId={run.run_id} sessionId={run.session_id} revision={reading.context_restart.expected_revision} existing={reading.context_restart.existing} goal={goal.trim() || run.goal || "继续处理原目标。"} principalId={principalId} requested={requestedSkills} excluded={excludedSkills} disabled={disabled || busy} onOpen={onOpen} onUnavailable={onUnavailable} onBusy={setBusy}/>}
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => void load()}
            >
              读取后续记录
            </Button>
            {reading?.existing ? (
              <Button
                disabled={busy}
                onClick={() =>
                  void onOpen(reading.existing!.run_id).catch((failure) =>
                    setError(failure.message),
                  )
                }
              >
                打开已保存的后续工作
              </Button>
            ) : reading?.can_continue ? (
              <form
                className="space-y-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!pending && goal.trim().length >= 1) void send();
                }}
              >
                <label>
                  接下来希望得到什么结果
                  <textarea
                    required
                    minLength={1}
                    maxLength={8000}
                    rows={3}
                    value={goal}
                    disabled={busy || !!pending}
                    onChange={(event) => setGoal(event.target.value)}
                  />
                </label>
                <ContinuedSkillPicker api={api} resource={root.includes("personal") ? "v1/personal/agent-skills" : "v1/agent-skills"} continued={reading.continued_skills ?? []} excluded={excludedSkills} onExcludedChange={setExcludedSkills} requested={requestedSkills} onRequestedChange={setRequestedSkills} disabled={disabled || busy || !!pending}/>
                <Button disabled={busy || !!pending || goal.trim().length < 1}>
                  保存并继续
                </Button>
              </form>
            ) : (
              reading && <p>原工作当前不能继续，请核对运行状态。</p>
            )}
            {pending && !reading?.existing && (
              <div className="space-y-2">
                <p>原受理结果待核对。刷新只读取，不自动重新提交。</p>
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={() => void send()}
                >
                  核对并重试原请求
                </Button>
              </div>
            )}
          </div>
        </details>
      )}
    </div>
  );
}
