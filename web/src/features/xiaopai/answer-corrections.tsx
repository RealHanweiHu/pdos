"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { answerCorrection, canCorrectAnswer, canSearchSameCategory, correctionSources, exclusionApplied, type AnswerCorrection, type CorrectionContext, type CorrectionContinuation, type CorrectionExclusion, type CorrectionWorkState } from "@/lib/answer-corrections";
import type { ContinuationSource } from "@/lib/run-continuation";

type Props = {
  context: CorrectionContext; disabled?: boolean; additionalSources?: ContinuationSource[]; sourceTools?: ReactNode;
  onContinue: (request: CorrectionContinuation) => Promise<void>;
  onExclude: (request: CorrectionExclusion) => Promise<CorrectionWorkState>;
  onCollapsed: (sourceId: string, state: CorrectionWorkState) => void;
  onUnavailable?: () => void;
};
/** The parent supplies its existing transport/journal. No automatic start or persistence on render. */
export function AnswerCorrections(props: Props) {
  if (!canCorrectAnswer(props.context)) return null;
  return <Controls key={`${props.context.run.session_id}:${props.context.run.run_id}`} {...props}/>;
}
function Controls({ context, disabled, additionalSources, sourceTools, onContinue, onExclude, onCollapsed, onUnavailable }: Props) {
  const [editing, setEditing] = useState(false), [text, setText] = useState(""), [sourceId, setSourceId] = useState("");
  const [confirmed, setConfirmed] = useState<CorrectionWorkState | null>(null), [pending, setPending] = useState<AnswerCorrection | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState(""), [denied, setDenied] = useState(false);
  const active = useRef(true), lock = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const current = confirmed && confirmed.revision > context.workState.revision ? { ...context, workState: confirmed } : context;
  const sources = correctionSources(current.workState);
  const selected = sources.some(item => item.id === sourceId) ? sourceId : sources[0]?.id;
  async function execute(request: AnswerCorrection) {
    if (lock.current || disabled || denied) return;
    lock.current = true; setBusy(true); setPending(request); setError(""); setNotice("");
    try {
      if (request.kind === "exclude_source") {
        const state = await onExclude(request);
        if (!active.current) return;
        if (!exclusionApplied(request, state, current)) throw new Error("操作结果待核对，请重试原操作。");
        setConfirmed(state); onCollapsed(request.body.item_id, state); setNotice("已收起这条结果。");
      } else {
        await onContinue(request);
        if (!active.current) return;
        setText(""); setEditing(false);
      }
      setPending(null);
    } catch (failure) {
      if (!active.current) return;
      const status = (failure as { status?: number }).status;
      if (status === 401 || status === 403) { setDenied(true); setPending(null); onUnavailable?.(); }
      else if ([404, 409, 422].includes(status ?? 0)) setPending(null);
      setError(failure instanceof Error ? failure.message : "操作结果待核对，请重试原操作。");
    } finally { lock.current = false; if (active.current) setBusy(false); }
  }
  function choose(action: "supplement" | "same_category" | "exclude_source") {
    try {
      const value = action === "exclude_source" ? { action, sourceId: selected! } : { action, text, ...(additionalSources?.length ? { sources: additionalSources } : {}) };
      void execute(answerCorrection(current, value, crypto.randomUUID()));
    } catch (failure) { setError(failure instanceof Error ? failure.message : "请核对补充条件。"); }
  }
  if (denied) return <p role="alert" className="text-sm">当前回答已不可读，请重新打开。</p>;
  const blocked = disabled || busy || !!pending;
  return <section aria-label="纠正这次回答" className="min-w-0 space-y-2 text-sm [overflow-wrap:anywhere]">
    <div className="flex flex-wrap gap-2">
      <Button type="button" size="sm" variant="ghost" disabled={blocked} onClick={() => setEditing(value => !value)}>补充条件</Button>
      {canSearchSameCategory(current) && <Button type="button" size="sm" variant="ghost" disabled={blocked} onClick={() => choose("same_category")}>同品类补查</Button>}
    </div>
    {sources.length > 0 && <div className="flex min-w-0 flex-wrap items-center gap-2"><label className="min-w-0 max-w-full">不相关的资料<select aria-label="不相关的资料" className="ml-2 max-w-full" value={selected} disabled={blocked} onChange={event => setSourceId(event.target.value)}>{sources.map(source => <option key={source.id} value={source.id}>{source.title} · v{source.revision}</option>)}</select></label><Button type="button" size="sm" variant="ghost" disabled={blocked} onClick={() => choose("exclude_source")}>收起并排除</Button></div>}
    {editing && <form className="space-y-2" onSubmit={event => { event.preventDefault(); if (!blocked && text.trim()) choose("supplement"); }}>
      <label className="block">补充条件<textarea aria-label="补充条件" className="block w-full min-w-0" rows={2} maxLength={8000} value={text} disabled={blocked} onChange={event => setText(event.target.value)}/></label>
      {sourceTools}
      <Button type="submit" size="sm" disabled={blocked || !text.trim()}>发送</Button>
    </form>}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {pending && !busy && <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => void execute(pending)}>重试原操作</Button>}
  </section>;
}
/** Collapse only after the work-state response confirms the source exclusion. */
export function CorrectableAnswerResult({ collapsed, children }: { collapsed: boolean; children: ReactNode }) {
  return collapsed ? <details className="min-w-0 text-sm"><summary>已收起不相关结果</summary><div className="mt-2 min-w-0">{children}</div></details> : <>{children}</>;
}
