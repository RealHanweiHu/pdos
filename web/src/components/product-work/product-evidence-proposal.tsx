"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ProductCandidatePreview } from "./product-candidate-preview";
import { productWorkHref } from "./product-work-navigation";
import { Button } from "@/components/ui/button";
import { PlanningForm, type PlanningTarget } from "./product-planning-form";
import { DiscoveryForm, type DiscoveryTarget } from "./product-discovery-form";
import { ObservationForm, type ObservationContent } from "./competitors";
import { Estimates, SegmentForm, type Draft as MarketDraft, type SizingResult } from "./market-segments";
import { ProductRequestError, request, type Evidence, type ProductCatalog, type Workspace } from "./product-work-api";

type Content = Record<string, unknown>;
type Capability = "competitor_analysis" | "market_analysis" | "opportunity_mapping" | "experiment_design" | "product_strategy" | "product_definition";
const fields = { competitor_analysis: "competitor_observations", market_analysis: "market_segments", opportunity_mapping: "opportunities", experiment_design: "experiments", product_strategy: "product_strategies", product_definition: "product_definitions" } as const;
const anchors = { competitor_analysis: "competitor", market_analysis: "segment", opportunity_mapping: "opportunity", experiment_design: "experiment", product_strategy: "strategy", product_definition: "definition" };
const tabs = { competitor_analysis: "competitors", market_analysis: "segments", opportunity_mapping: "opportunities", experiment_design: "experiments", product_strategy: "strategies", product_definition: "definitions" };
type Proposal = { capability: Capability; items: Content[] };
type Finding = { id: string; run_id: string; status: string; proposed_digest: string; accepted_digest: string | null; accepted_payload: { proposal: Proposal } | null; proposed_payload: { assessment: Partial<Record<typeof fields[Capability], Content[]>> }; review_comment: string | null };
type SavedRecord = { id: string; content?: { title?: string }; title?: string; hypothesis?: string; brand?: string; model?: string; variant?: string };
type Candidate = { records?: SavedRecord[]; targets?: (DiscoveryTarget | PlanningTarget)[]; finding: Finding | null; sources_current: boolean; product_line_id: string | null; proposal: Proposal | null; evidence: Evidence[]; calculations: SizingResult[] };
type Editing = { index: number; original: boolean; modify?: boolean };
const states: Record<string, string> = { pending_review: "待核对", accepted: "已接受，尚未登记", rejected: "已拒绝", applied: "已应用，业务记录已保存" };
function content(payload: unknown, capability: Capability): Content {
  const copy = { ...(payload as Content) };
  delete copy.request_id; delete copy.product_line_id; if (!["product_strategy", "product_definition"].includes(capability)) delete copy.supersedes_id;
  return copy;
}

export function ProductEvidenceProposal({ base, runId, disabled, autoLoad = false, onPendingChange, onFailure, onAccessDenied }: { base: string; runId: string; disabled: boolean; autoLoad?: boolean; onPendingChange?: (value: boolean) => void; onFailure?: (message: string) => void; onAccessDenied?: (message: string) => void }) {
  const [record, setRecord] = useState<Candidate | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [catalog, setCatalog] = useState<ProductCatalog | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const live = useRef(true); const autoRead = useRef(false); const prefix = useId();
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  useEffect(() => { if (autoLoad && !autoRead.current) { autoRead.current = true; void load(); } });
  const finding = record?.finding;
  const pending = finding?.status === "pending_review";
  function clear() { setRecord(null); setProposal(null); setWorkspace(null); setCatalog(null); setEvidence([]); setEditing(null); setComment(""); }
  function editorAuthorityLost(message: string) {
    if (!live.current) return;
    clear(); setError(message); setBusy(false);
    onAccessDenied?.(message); onFailure?.(message);
  }
  async function load() {
    setBusy(true); setError(""); clear();
    try {
      const candidate = await request<Candidate>(`${base}/evidence-ai-finding`, "POST", { run_id: runId });
      if (!live.current) return;
      if (candidate.finding) {
        const [space, products] = await Promise.all([request<Workspace>(base), request<ProductCatalog>(`${base}/products`)]);
        if (!live.current) return;
        setWorkspace(space); setCatalog(products); setEvidence(candidate.evidence);
      }
      setRecord(candidate); setProposal(candidate.proposal); setComment(candidate.finding?.review_comment ?? "");
    } catch (failure) {
      if (live.current && failure instanceof ProductRequestError && [401, 403].includes(failure.status)) onAccessDenied?.(failure.message);
      if (live.current) onFailure?.(failure instanceof Error ? failure.message : "读取或办理未确认，请刷新分析和候选状态后继续"); if (live.current) { clear(); setError(failure instanceof Error ? failure.message : "候选暂不可读"); } }
    finally { if (live.current) setBusy(false); }
  }
  async function mutate(action: "accepted" | "rejected" | "apply") {
    if (!finding || !proposal) return;
    setBusy(true); setError(""); onPendingChange?.(true);
    try {
      const result = await request<{ finding: Finding; records?: SavedRecord[]; calculations?: SizingResult[] }>(`${base}/evidence-ai-${action === "apply" ? "apply" : "review"}`, "POST", action === "apply" ? { run_id: runId, finding_id: finding.id, accepted_digest: finding.accepted_digest } : { run_id: runId, finding_id: finding.id, expected_digest: finding.proposed_digest, decision: action, comment: comment.trim(), proposal: action === "accepted" ? proposal : null });
      if (live.current) { setRecord({ ...record!, finding: result.finding, records: result.records ?? record!.records, calculations: result.calculations ?? record!.calculations }); setProposal(result.finding.accepted_payload?.proposal ?? { capability: proposal.capability, items: result.finding.proposed_payload.assessment[fields[proposal.capability]] ?? [] }); }
    } catch (failure) {
      if (live.current && failure instanceof ProductRequestError && [401, 403].includes(failure.status)) onAccessDenied?.(failure.message);
      if (live.current) onFailure?.(failure instanceof Error ? failure.message : "读取或办理未确认，请刷新分析和候选状态后继续"); if (live.current) { clear(); setError(`${failure instanceof Error ? failure.message : "办理结果未确认"}。请重新读取候选状态后继续。`); } }
    finally { if (live.current) setBusy(false); onPendingChange?.(false); }
  }
  function saveItem(value: unknown) {
    if (!proposal || editing === null || editing.original) return;
    setProposal({ ...proposal, items: proposal.items.map((item, i) => i === editing.index ? content(value, proposal.capability) : item) });
    setEditing(null);
  }
  const originalItems = finding ? (proposal ? finding.proposed_payload.assessment[fields[proposal.capability]] ?? [] : []) : [];
  const selected = editing ? (editing.original ? originalItems[editing.index] : proposal?.items[editing.index]) : null;
  const readOnly = !pending || disabled || !record?.sources_current || !!editing?.original;
  return <section className="space-y-3 rounded-md border p-3" aria-label="产品工作候选">
    <h4 className="font-medium">产品工作候选</h4>
    <p className="text-muted-foreground">核对原证据与各项内容后接受，再独立应用整批记录。负责人和归属沿用原分析；数值由规则计算，缺项保持未知；机会保留三方案，实验仅建草稿。</p>
    <Button variant="outline" size="sm" disabled={busy} onClick={() => void load()}>读取 / 刷新业务候选</Button>
    {busy && <p role="status">正在核对或办理…</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
    {record && !finding && <p>没有可办理候选。可检查分析缺项或质量收窄状态。</p>}
    {finding && proposal && <>
      <p>{states[finding.status]} · 共 {proposal.items.length} 项</p>
      {!record.sources_current && <p className="text-primary">原资料已变化，请重新分析后接受或应用；仍可拒绝此候选。</p>}
      {proposal.items.map((item, index) => <div className="flex flex-wrap items-center gap-2 rounded-md border p-2" key={index}><span>{index + 1}. {String(item.title ?? item.hypothesis ?? `${item.brand} · ${item.model} · ${item.variant}`)}</span><Button size="sm" variant="ghost" disabled={busy || editing !== null} onClick={() => setEditing({ index, original: false })}>查看 / 核对第 {index + 1} 项</Button><Button size="sm" variant="ghost" disabled={busy || editing !== null} onClick={() => setEditing({ index, original: true })}>查看原始第 {index + 1} 项</Button></div>)}
      {editing && selected && workspace && catalog && <div className="space-y-2"><p>{editing.original ? "以下为不可修改的 AI 原始候选" : "核对内容；保存此条后回到整批接受"}</p>{!editing.modify ? <ProductCandidatePreview value={selected} base={base} evidence={evidence} onAccessDenied={editorAuthorityLost}/> : <fieldset disabled={busy || readOnly}>
        {proposal.capability === "competitor_analysis" ? <ObservationForm key={`${editing.index}:${editing.original}`} candidate={{ ...selected, product_line_id: record.product_line_id } as ObservationContent} previous={null} initialLine={record.product_line_id ?? ""} workspace={workspace} catalog={catalog} evidence={evidence} busy={busy} onSave={async value => saveItem(value)} onCancel={() => setEditing(null)}/> : proposal.capability === "market_analysis" ? <SegmentForm key={`${editing.index}:${editing.original}`} candidate={{ ...selected, product_line_id: record.product_line_id, supersedes_id: null } as MarketDraft} initial={null} workspace={workspace} catalog={catalog} evidence={evidence} base={base} onAuthorityLost={editorAuthorityLost} onReview={saveItem} onSaved={() => {}} onCancel={() => setEditing(null)}/> : (proposal.capability === "opportunity_mapping" || proposal.capability === "experiment_design") ? <DiscoveryForm key={`${editing.index}:${editing.original}`} capability={proposal.capability} value={selected} targets={(record.targets ?? []).filter((t): t is DiscoveryTarget => t.kind === "segment" || t.kind === "opportunity")} evidence={evidence} workspace={workspace} base={base} onSave={saveItem} onCancel={() => setEditing(null)}/> : <PlanningForm key={`${editing.index}:${editing.original}`} capability={proposal.capability} value={selected} targets={record.targets ?? []} line={record.product_line_id} evidence={evidence} workspace={workspace} catalog={catalog} base={base} onSave={saveItem} onCancel={() => setEditing(null)}/>}
      </fieldset>}{!readOnly && !editing.modify && <Button size="sm" variant="outline" onClick={() => setEditing({ ...editing, modify: true })}>修订此条草案</Button>}<Button size="sm" variant="outline" disabled={busy} onClick={() => setEditing(null)}>返回候选列表</Button></div>}
      {editing === null && <><label className="block" htmlFor={`${prefix}-comment`}>办理说明</label><textarea id={`${prefix}-comment`} className="w-full rounded-md border bg-background p-2" value={comment} maxLength={2048} disabled={busy || disabled || !pending} onChange={event => setComment(event.target.value)}/>
        {pending && <div className="flex flex-wrap gap-2"><Button size="sm" disabled={busy || disabled || !record.sources_current || !comment.trim()} onClick={() => void mutate("accepted")}>接受整批核对内容</Button><Button size="sm" variant="outline" disabled={busy || disabled || !comment.trim()} onClick={() => void mutate("rejected")}>拒绝此候选</Button></div>}
        {record.calculations.length > 0 && finding.status !== "pending_review" && <div className="space-y-2"><h5 className="font-medium">已接受参数的计算结果</h5>{record.calculations.map((result, i) => <Estimates key={i} result={result}/>)}</div>}
        {finding.status === "accepted" && <Button size="sm" disabled={busy || disabled || !record.sources_current} onClick={() => void mutate("apply")}>独立应用整批记录</Button>}
        {finding.status === "applied" && <div className="space-y-2">{(record.records ?? []).map((saved, index) => <a key={saved.id} className="flex min-h-11 items-center text-primary underline" href={`${productWorkHref(base.split("/").at(-1) ?? "", tabs[proposal.capability], record.product_line_id ?? "")}&history=1#${anchors[proposal.capability]}-${encodeURIComponent(saved.id)}`}>打开已保存第 {index + 1} 项：{saved.title ?? saved.content?.title ?? saved.hypothesis ?? [saved.brand, saved.model, saved.variant].filter(Boolean).join(" · ")}</a>)}{!record.records?.length && <><p className="text-muted-foreground">已应用，记录回链暂未返回，可刷新候选或打开业务列表核对。</p><a className="inline-flex min-h-11 items-center text-primary underline" href={productWorkHref(base.split("/").at(-1) ?? "", tabs[proposal.capability], record.product_line_id ?? "")}>打开业务列表</a></>}</div>}
      </>}
    </>}
  </section>;
}
