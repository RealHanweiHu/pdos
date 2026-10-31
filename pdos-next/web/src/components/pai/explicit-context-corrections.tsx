"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { contextOptionsPath, correctionSaved, explicitCorrection, type ContextOption, type ExplicitCorrectionKind, type ExplicitCorrectionRequest, type ExplicitWorkState } from "@/lib/explicit-context-corrections";
import type { CorrectionContext } from "@/lib/answer-corrections";
import type { ContinuationRequest } from "@/lib/run-continuation";
import type { WorkspaceTransport } from "@/lib/workspace-api";

export function ExplicitContextCorrections({ api, context, disabled, onContinue, onState, onUnavailable }: {
  api: WorkspaceTransport; context: CorrectionContext; disabled?: boolean;
  onContinue: (request: ContinuationRequest) => Promise<void>;
  onState: (state: ExplicitWorkState) => void; onUnavailable?: () => void;
}) {
  const [query, setQuery] = useState(""), [options, setOptions] = useState<ContextOption[]>([]), [selected, setSelected] = useState<string[]>([]);
  const [pending, setPending] = useState<ExplicitCorrectionRequest | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const lock = useRef(false), generation = useRef(0);
  useEffect(() => { const counter = generation; return () => { counter.current++; }; }, []);
  const key = (row: ContextOption) => `${row.source_type}:${row.source_id}`;
  async function read(objectId?: string) {
    if (disabled || lock.current) return;
    lock.current = true; setBusy(true); setError(""); const own = generation.current;
    try {
      const result = await api<{ items: ContextOption[]; has_more: boolean }>(contextOptionsPath(context, query, objectId));
      if (own !== generation.current) return;
      setOptions(result.items); setSelected(result.items.length === 1 ? [key(result.items[0])] : []);
      setNotice(result.has_more ? "请补充名称，缩小选择范围。" : result.items.length ? "" : "没有找到当前可选的记录。");
    } catch (failure) { if (own === generation.current) { setOptions([]); setSelected([]); if ([401, 403].includes((failure as { status?: number }).status ?? 0)) onUnavailable?.(); setError(failure instanceof Error ? failure.message : "资料暂未读回。"); } }
    finally { if (own === generation.current) { lock.current = false; setBusy(false); } }
  }
  async function send(request: ExplicitCorrectionRequest) {
    if (disabled || lock.current) return;
    lock.current = true; setBusy(true); setPending(request); setError(""); const own = generation.current;
    try {
      const result = await api<ExplicitWorkState>(request.path, request.body);
      if (own !== generation.current) return;
      if (!correctionSaved(request, result, context)) throw new Error("纠正结果待读回，请重试原操作。");
      const latest = await api<ExplicitWorkState>(request.path);
      if (own !== generation.current) return;
      onState(latest);
      if (!correctionSaved(request, latest, context)) throw Object.assign(new Error("资料条件已变化，请按最新选择继续。"), { status: 409 });
      await onContinue({ ...request.continuation, context_revision: latest.revision });
      if (own === generation.current) setPending(null);
    } catch (failure) {
      if (own !== generation.current) return;
      const status = (failure as { status?: number }).status;
      if ([401, 403].includes(status ?? 0)) { setOptions([]); setSelected([]); setPending(null); onUnavailable?.(); }
      else if ([404, 409, 422].includes(status ?? 0)) setPending(null);
      setError(failure instanceof Error ? failure.message : "操作结果待读回，请重试原操作。");
    } finally { if (own === generation.current) { lock.current = false; setBusy(false); } }
  }
  function choose(kind: ExplicitCorrectionKind) {
    try { void send(explicitCorrection(context, kind, ["current_only", "clear"].includes(kind) ? [] : options.filter(row => selected.includes(key(row))), crypto.randomUUID(), crypto.randomUUID())); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "请明确选择。"); }
  }
  const blocked = disabled || busy || !!pending;
  return <details className="min-w-0 space-y-2 text-sm [overflow-wrap:anywhere]">
    <summary className="cursor-pointer">换对象、版本或资料</summary>
    <div className="space-y-2 pt-2">
      <form className="flex min-w-0 flex-wrap gap-2" onSubmit={event => { event.preventDefault(); if (query.trim()) void read(); }}><label className="min-w-0 flex-1">对象或资料名称<input className="block w-full min-w-0" value={query} maxLength={120} disabled={blocked} onChange={event => setQuery(event.target.value)}/></label><Button type="submit" variant="outline" size="sm" disabled={blocked || !query.trim()}>查找</Button></form>
      {options.map(row => <div key={key(row)} className="flex min-w-0 flex-wrap gap-2"><label className="min-w-0"><input type="checkbox" checked={selected.includes(key(row))} disabled={blocked} onChange={event => setSelected(prior => event.target.checked ? [...prior, key(row)] : prior.filter(value => value !== key(row)))}/> {row.title} · v{row.source_revision}{!row.is_current ? " · 历史版本" : ""}</label><Button type="button" variant="ghost" size="sm" disabled={blocked} onClick={() => void read(row.object_id)}>查看可读版本</Button></div>)}
      <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" size="sm" disabled={blocked || selected.length !== 1} onClick={() => choose("replace_focus")}>换为这个对象并重查</Button><Button type="button" variant="outline" size="sm" disabled={blocked || !selected.length} onClick={() => choose("fixed_versions")}>只看所选版本</Button><Button type="button" variant="outline" size="sm" disabled={blocked || !selected.length} onClick={() => choose("limit_sources")}>只用所选资料</Button><Button type="button" variant="ghost" size="sm" disabled={blocked} onClick={() => choose("current_only")}>只看当前有效资料</Button><Button type="button" variant="ghost" size="sm" disabled={blocked} onClick={() => choose("clear")}>解除资料条件并重查</Button></div>
      <p className="text-xs text-muted-foreground">仅选择当前范围可读的版本。更换项目或型号，可从范围导航打开对应会话。</p>
      {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
      {pending && !busy && <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => void send(pending)}>重试原纠正</Button>}
    </div>
  </details>;
}
