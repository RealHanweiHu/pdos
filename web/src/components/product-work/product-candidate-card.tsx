"use client";

import { useEffect, useId, useRef, useState } from "react";
import { SparkleIcon } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { ProductCandidatePreview } from "./product-candidate-preview";
import { ProductRequestError, request, type Evidence } from "./product-work-api";

export type ProductItemCandidate = {
  id: string; run_id: string; parent_finding_id: string; item_position: number;
  title: string; status: string; item: Record<string, unknown>; created_at?: string;
};
type Finding = { id: string; status: string; proposed_digest: string; accepted_digest: string | null };
type Readback = { finding: Finding; sources_current: boolean; proposal: { capability: string; items: Record<string, unknown>[] }; evidence: Evidence[] };

/** Every named decision reads the current server receipt; acceptance never applies it. */
export function ProductCandidateCard({ base, candidate, disabled, onRevise, onPendingChange, onChanged, onAuthorityLost }: { base: string; candidate: ProductItemCandidate; disabled?: boolean; onRevise: () => void; onPendingChange?: (value: boolean) => void; onChanged?: () => void; onAuthorityLost?: (message: string) => void }) {
  const [record, setRecord] = useState<Readback | null>(null);
  const [show, setShow] = useState(false), [ignoring, setIgnoring] = useState(false);
  const [reason, setReason] = useState(""), [error, setError] = useState("");
  const [denied, setDenied] = useState(false);
  const [busy, setBusy] = useState(false);
  const working = useRef(false), live = useRef(true), reasonId = useId();
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  const state = record?.finding.status ?? candidate.status;
  const identity = { run_id: candidate.run_id, parent_finding_id: candidate.parent_finding_id, position: candidate.item_position };
  async function operate(action: "read" | "accepted" | "rejected" | "apply") {
    if (working.current || disabled || (action === "rejected" && !reason.trim())) return;
    working.current = true; setBusy(true); setError(""); onPendingChange?.(true);
    try {
      const current = await request<Readback>(`${base}/evidence-ai-item`, "POST", identity);
      if (!live.current) return;
      setDenied(false);
      setRecord(current);
      if (action === "read") { setShow(true); return; }
      const finding = current.finding;
      const review = { run_id: candidate.run_id, finding_id: finding.id, expected_digest: finding.proposed_digest, decision: action, comment: action === "rejected" ? reason.trim() : "接受此条草案，保留原始来源与依据", proposal: action === "accepted" ? current.proposal : null };
      const result = await request<{ finding: Finding }>(`${base}/evidence-ai-item-${action === "apply" ? "apply" : "review"}`, "POST", action === "apply" ? { run_id: candidate.run_id, finding_id: finding.id, accepted_digest: finding.accepted_digest } : { ...identity, review });
      if (live.current) { setRecord({ ...current, finding: result.finding }); setIgnoring(false); onChanged?.(); }
    } catch (failure) {
      if (!live.current) return;
      const message = failure instanceof Error ? failure.message : "办理回执暂不可读";
      if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) { setRecord(null); setShow(false); setIgnoring(false); setReason(""); setDenied(true); onAuthorityLost?.(message); }
      setError(`${message}。请重新核对实际状态。`);
    } finally { working.current = false; if (live.current) setBusy(false); onPendingChange?.(false); }
  }
  if (denied) return <article className="space-y-2 rounded-lg border p-3.5"><p role="alert" className="text-xs text-destructive">候选权限已变化，原内容已收起。{error}</p><Button size="sm" variant="outline" disabled={busy || disabled} onClick={() => void operate("read")}>重新核对候选权限</Button></article>;
  const summary = [candidate.item.brand, candidate.item.model, candidate.item.region, candidate.item.channel].filter(Boolean).join(" · ") || (candidate.item.job_to_be_done as { text?: string } | undefined)?.text || (typeof candidate.item.hypothesis === "string" ? candidate.item.hypothesis : "草案已起草；核对来源、未知项与取舍后裁决。");
  return <article className={`space-y-2 rounded-lg border px-3.5 py-3 ${state === "pending_review" ? "border-dashed border-primary/30 bg-primary/5" : "border-emerald-600/25 bg-emerald-600/5 dark:border-emerald-400/25"}`}>
    <div className="flex items-start gap-2"><h3 className="min-w-0 flex-1 break-words text-[13px] font-semibold">{candidate.title}</h3><span className="inline-flex shrink-0 items-center gap-1 text-[11px] text-primary"><SparkleIcon aria-hidden="true" size={13}/>AI 候选</span></div>
    <p className="break-words text-xs leading-5 text-muted-foreground">{summary}</p>
    {candidate.created_at && <p className="text-[11px] text-muted-foreground">{new Date(candidate.created_at).toLocaleDateString()} · 第 {candidate.item_position} 项</p>}
    {state === "pending_review" ? <div className="flex flex-wrap gap-1.5"><Button size="sm" disabled={busy || disabled || record?.sources_current === false} onClick={() => void operate("accepted")}>接受</Button><Button size="sm" variant="outline" disabled={busy || disabled} onClick={onRevise}>修订后接受</Button><Button size="sm" variant="ghost" disabled={busy || disabled} onClick={() => setIgnoring(!ignoring)}>忽略</Button></div> : <p role="status" className="text-xs text-emerald-700 dark:text-emerald-400">{state === "accepted" ? "已接受 · 待独立应用" : state === "applied" ? "已独立应用 · 正式记录已保存" : "已忽略 · 原草案与原因保留"}</p>}
    {state === "accepted" && <Button size="sm" disabled={busy || disabled || record?.sources_current === false} onClick={() => void operate("apply")}>独立应用此条</Button>}
    {ignoring && <div className="space-y-2"><label htmlFor={reasonId} className="text-xs">忽略原因</label><textarea id={reasonId} maxLength={2048} value={reason} disabled={busy || disabled} onChange={event => setReason(event.target.value)} className="w-full rounded-md border bg-background p-2 text-sm"/><Button size="sm" variant="outline" disabled={busy || disabled || !reason.trim()} onClick={() => void operate("rejected")}>确认忽略此条</Button></div>}
    <Button size="sm" variant="ghost" className="h-8 px-0 text-xs text-muted-foreground" disabled={busy || disabled} onClick={() => show ? setShow(false) : void operate("read")}>{show ? "收起依据" : "查看草案与来源依据"}</Button>
    {record?.sources_current === false && <p className="text-xs text-pending">原来源已有变化，请重新分析；此候选仍可忽略。</p>}
    {show && record && <ProductCandidatePreview value={record.proposal.items[0]} base={base} evidence={record.evidence} onAccessDenied={onAuthorityLost}/>}
    {busy && <p role="status" className="text-xs text-muted-foreground">正在核对最新回执…</p>}{error && <p role="alert" className="text-xs text-destructive">{error}</p>}
  </article>;
}
