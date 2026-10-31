"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { deeperLookupRequest, readExclusionSources, type AnswerExclusions, type FeedbackSource } from "@/lib/answer-followup";
import { exclusionApplied, type CorrectionContext, type CorrectionWorkState } from "@/lib/answer-corrections";
import type { ContinuationRequest, ContinuationSource } from "@/lib/run-continuation";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import { AnswerCorrections } from "./answer-corrections";

type Props = {
  api: WorkspaceTransport; context: CorrectionContext; disabled?: boolean; additionalSources?: ContinuationSource[];
  onContinue: (request: ContinuationRequest) => Promise<void>;
  onState: (value: CorrectionWorkState) => void;
  onSnapshot?: (value: AnswerExclusions) => void;
  onUnavailable?: () => void;
};
export function AnswerFollowupActions({ api, context, disabled, additionalSources, onContinue, onState, onSnapshot, onUnavailable }: Props) {
  const [error, setError] = useState(""), [denied, setDenied] = useState(false);
  const lifetime = useRef(0);
  const callbacks = useRef({ onSnapshot, onUnavailable });
  useEffect(() => { callbacks.current = { onSnapshot, onUnavailable }; }, [onSnapshot, onUnavailable]);
  const { run, root, workState } = context;
  useEffect(() => {
    const counter = lifetime, own = ++counter.current;
    async function refresh() {
      try {
        const feedbacks: FeedbackSource[] = workState.exclusions.length ? await readExclusionSources(api, root, run.run_id) : [];
        if (own === counter.current) callbacks.current.onSnapshot?.({ run_id: run.run_id, state: workState, feedbacks });
      } catch (failure) {
        if (own !== counter.current) return;
        setError("纠正条件暂未读回，请刷新本次携带。");
        if ([401, 403].includes((failure as { status?: number }).status ?? 0)) { setDenied(true); callbacks.current.onUnavailable?.(); }
      }
    }
    void refresh();
    return () => { counter.current++; };
  }, [api, root, run.run_id, workState]);
  async function deepen() {
    if (disabled) return;
    try { await onContinue(deeperLookupRequest(run.run_id, "", crypto.randomUUID(), additionalSources)); }
    catch { /* The existing continuation journal owns transport errors and exact replay. */ }
  }
  if (denied) return <p role="alert" className="text-sm">当前回答已不可读，请重新打开。</p>;
  return <details className="min-w-0 space-y-3 text-sm [overflow-wrap:anywhere]">
    <summary className="cursor-pointer">继续查与纠正</summary>
    <div className="space-y-3 pt-2">
      <div className="space-y-1"><p>查找范围：{workState.search_context?.label || "当前会话范围"}{workState.search_context?.scoped && workState.search_preferences?.scope === "same_category" ? "，不足时补查同品类" : ""}</p><p className="text-muted-foreground">继续核对更多资料和业务记录，通常比快查更久。可离开后从会话返回。</p>{!!additionalSources?.length && <p className="text-muted-foreground">本次新增 {additionalSources.length} 份所选资料。</p>}<Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => void deepen()}>深入查</Button></div>
      <AnswerCorrections context={context} disabled={disabled} additionalSources={additionalSources} onUnavailable={() => { setDenied(true); onUnavailable?.(); }}
        onContinue={request => onContinue(request.body)}
        onExclude={async request => {
          const own = lifetime.current;
          const result = await api<CorrectionWorkState>(request.path, request.body);
          if (own !== lifetime.current) throw new Error("这条回答已退出，请重新打开。");
          if (!exclusionApplied(request, result, context)) return result;
          const state = await api<CorrectionWorkState>(request.path);
          if (own !== lifetime.current) throw new Error("这条回答已退出，请重新打开。");
          if (!exclusionApplied(request, state, context)) {
            callbacks.current.onSnapshot?.({ run_id: run.run_id, state, feedbacks: [] });
            onState(state);
            throw Object.assign(new Error("已读回最新携带，原排除条件已被移除。"), { status: 409 });
          }
          const feedbacks = await readExclusionSources(api, root, run.run_id);
          if (own !== lifetime.current) throw new Error("这条回答已退出，请重新打开。");
          if (!feedbacks.some(item => item.selection_id === request.body.item_id)) throw new Error("排除已保存，结果收起待读回；请重试原操作。");
          callbacks.current.onSnapshot?.({ run_id: run.run_id, state, feedbacks });
          onState(state);
          return state;
        }} onCollapsed={() => { setError(""); }} />
      {error && <p role="alert">{error}</p>}
    </div>
  </details>;
}
