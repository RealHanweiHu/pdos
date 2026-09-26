"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { SourcePicker, type SourceSelection } from "./source-picker";
import type { MemoryDraftInput, MemoryRecord } from "./memory-types";
import { KnowledgeKindSelect, knowledgeKindLabel, parseKnowledgeKind } from "./knowledge-kind";

async function request(path: string, body?: object): Promise<unknown> {
  const response = await fetch(`/api/${path}`, { method: body ? "POST" : "GET", cache: "no-store",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) {
    throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "知识纠错暂不可用，刷新可核对结果");
  }
  return value;
}
function text(value: unknown): string {
  if (typeof value !== "string") throw new Error("纠错记录不完整");
  return value;
}
function id(value: unknown): string {
  const result = text(value);
  if (!/^[0-9a-f-]{36}$/.test(result)) throw new Error("纠错来源无效");
  return result;
}
function draft(value: unknown): MemoryDraftInput {
  if (!isRecord(value) || !Array.isArray(value.tags) || !value.tags.every(tag => typeof tag === "string")) throw new Error("修正内容不完整");
  return { title: text(value.title), content: text(value.content), applicability: value.applicability === null ? null : text(value.applicability), tags: value.tags, knowledge_kind: parseKnowledgeKind(value.knowledge_kind) };
}
function sourceRefs(value: unknown): { kind: string; reference: string; version: string; title: string }[] {
  if (!Array.isArray(value)) throw new Error("候选来源记录不完整");
  return value.map(ref => {
    if (!isRecord(ref)) throw new Error("候选来源记录不完整");
    return { kind: text(ref.kind), reference: text(ref.reference), title: typeof ref.title === "string" ? ref.title : text(ref.reference),
      version: typeof ref.digest === "string" ? ref.digest : typeof ref.content_sha256 === "string" ? ref.content_sha256 : typeof ref.version === "number" ? String(ref.version) : "历史出处" };
  });
}
function correction(value: unknown) {
  if (!isRecord(value) || !["pending", "published", "rejected"].includes(String(value.status))) throw new Error("纠错状态不完整");
  return { id: id(value.id), projectId: id(value.project_id), sourceId: id(value.source_memory_id),
    proposerId: id(value.proposer_user_id), source: draft(value.source_snapshot), proposal: draft(value.proposal),
    sourceHash: text(value.source_content_sha256), proposalHash: text(value.proposal_sha256),
    originalRefs: sourceRefs(isRecord(value.source_snapshot) ? value.source_snapshot.source_refs : null),
    replacementRefs: value.proposed_source_refs === null ? null : sourceRefs(value.proposed_source_refs),
    reason: text(value.reason), status: value.status as "pending" | "published" | "rejected",
    replacementId: value.replacement_memory_id === null ? null : id(value.replacement_memory_id),
    reviewReason: value.review_reason === null ? null : text(value.review_reason),
    sourceCurrent: value.source_current_status === "verified" && value.source_current_sha256 === value.source_content_sha256,
  };
}
type Correction = ReturnType<typeof correction>;

export function CorrectionForm({ memory, onSubmitted }: { memory: MemoryRecord; onSubmitted?: () => void }) {
  const [open, setOpen] = useState(false);
  const [replaceSources, setReplaceSources] = useState(false);
  const [sourceSelections, setSourceSelections] = useState<SourceSelection[]>([]);
  const [proposal, setProposal] = useState<MemoryDraftInput>({ title: memory.title, content: memory.content, applicability: memory.applicability, tags: memory.tags, knowledge_kind: memory.knowledge_kind ?? null });
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState<string | null>(null);
  const lastRequest = useRef<{ body: string; id: string } | null>(null);
  async function submit() {
    setBusy(true); setError(null);
    const body = { ...proposal, reason, expected_content_sha256: memory.content_sha256, source_selections: replaceSources ? sourceSelections : null };
    const signature = JSON.stringify(body);
    if (lastRequest.current?.body !== signature) lastRequest.current = { body: signature, id: crypto.randomUUID() };
    try {
      const result = correction(await request(`projects/${memory.project_id}/memories/${memory.id}/corrections`, { ...body, request_id: lastRequest.current.id }));
      setSubmitted(result.id); onSubmitted?.();
    } catch (error) { setError(error instanceof Error ? error.message : "修正尚未提交"); }
    finally { setBusy(false); }
  }
  return <div className="mt-2 space-y-2">
    {!submitted && <Button size="sm" variant="outline" onClick={() => setOpen(!open)}>{open ? "收起修正" : "提出知识修正"}</Button>}
    {submitted && <p role="status" className="text-sm">修正候选已提交，等待另一位成员审核。<a className="ml-1 text-primary underline" href={`/knowledge?project=${memory.project_id}&correction=${submitted}`}>查看审核记录</a></p>}
    {open && !submitted && <div className="space-y-3 rounded-lg border bg-background p-3">
      <p className="text-xs text-muted-foreground">原版 {memory.content_sha256.slice(0, 12)}；提交后原经验继续有效，审核发布才会替换。</p>
      <KnowledgeKindSelect value={proposal.knowledge_kind} onChange={knowledge_kind => setProposal({ ...proposal, knowledge_kind })} />
      <label className="block text-xs">修正标题<input className="mt-1 block w-full rounded-md border bg-background p-2 text-sm" maxLength={512} value={proposal.title} onChange={event => setProposal({ ...proposal, title: event.target.value })} /></label>
      <label className="block text-xs">修正后全文<textarea className="mt-1 block min-h-32 w-full rounded-md border bg-background p-2 text-sm" maxLength={20000} value={proposal.content} onChange={event => setProposal({ ...proposal, content: event.target.value })} /></label>
      <label className="block text-xs">适用条件<textarea className="mt-1 block min-h-20 w-full rounded-md border bg-background p-2 text-sm" maxLength={5000} value={proposal.applicability ?? ""} onChange={event => setProposal({ ...proposal, applicability: event.target.value || null })} /></label>
      <label className="block text-xs">标签（逗号分隔）<input className="mt-1 block w-full rounded-md border bg-background p-2 text-sm" value={proposal.tags.join(", ")} onChange={event => setProposal({ ...proposal, tags: event.target.value.split(",").map(tag => tag.trim()).filter(Boolean) })} /></label>
      <label className="block text-xs">修正理由与依据<textarea className="mt-1 block min-h-20 w-full rounded-md border bg-background p-2 text-sm" maxLength={5000} value={reason} onChange={event => setReason(event.target.value)} /></label>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={replaceSources} onChange={event => setReplaceSources(event.target.checked)} />重新选择适用依据（原出处保留在修正历史）</label>
      {replaceSources && <SourcePicker projectId={memory.project_id} value={sourceSelections} onChange={setSourceSelections} />}
      <Button size="sm" disabled={busy || !proposal.knowledge_kind || !reason.trim() || !proposal.title.trim() || !proposal.content.trim() || (replaceSources && !sourceSelections.length)} onClick={submit}>{busy ? "正在提交…" : "提交待审核修正"}</Button>
    </div>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </div>;
}

function CorrectionReview({ item, canReview, userId, onChanged }: { item: Correction; canReview: boolean; userId: string; onChanged: () => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function review(action: "publish" | "reject") {
    setBusy(true); setError(null);
    try {
      correction(await request(`projects/${item.projectId}/knowledge-corrections/${item.id}/${action}`, { reason, expected_proposal_sha256: item.proposalHash }));
      onChanged();
    } catch (error) { setError(error instanceof Error ? error.message : "审核尚未完成"); }
    finally { setBusy(false); }
  }
  return <li id={`correction-${item.id}`} className="space-y-3 rounded-lg border bg-background p-4">
    <div className="flex flex-wrap justify-between gap-2"><h3 className="font-medium">{item.proposal.title}</h3><span className="text-sm">{({ pending: "待审核", published: "已发布替换", rejected: "已退回" })[item.status]}</span></div>
    <p className="whitespace-pre-wrap text-sm">修正理由：{item.reason}</p>
    <div className="space-y-2 rounded-lg border p-3 text-xs"><p>{item.replacementRefs === null ? "沿用原适用依据" : "重新选择当前依据，原出处保留在历史"}</p>
      <p className="font-medium">原出处</p><ul>{item.originalRefs.map((ref, index) => <li className="break-all" key={index}>{ref.title} · {ref.kind} · {ref.version}</li>)}</ul>
      {item.replacementRefs !== null && <><p className="font-medium">建议适用依据</p><ul>{item.replacementRefs.map((ref, index) => <li className="break-all" key={index}>{ref.title} · {ref.kind} · {ref.version}</li>)}</ul></>}
    </div>
    <details><summary className="cursor-pointer text-sm text-primary">查看原文与修正差异</summary><div className="mt-3 grid gap-3 md:grid-cols-2">
      {[{ label: "原经验", value: item.source, hash: item.sourceHash }, { label: "建议修正版", value: item.proposal, hash: item.proposalHash }].map(({ label, value, hash }) => <section key={label} className="space-y-2 rounded-lg border p-3"><h4 className="text-sm font-medium">{label} · {hash.slice(0, 12)}</h4><p className="text-sm font-medium">{value.title}</p><p className="text-xs">分类：{knowledgeKindLabel(value.knowledge_kind)}</p><p className="whitespace-pre-wrap text-sm">{value.content}</p><p className="whitespace-pre-wrap text-sm">适用条件：{value.applicability ?? "未说明"}</p><p className="text-xs text-muted-foreground">标签：{value.tags.join("、") || "无"}</p></section>)}
    </div></details>
    <a className="text-sm text-primary underline" href={`/knowledge?project=${item.projectId}&memory=${item.sourceId}`}>查看原知识记录</a>
    {item.replacementId && <a className="ml-3 text-sm text-primary underline" href={`/knowledge?project=${item.projectId}&memory=${item.replacementId}`}>查看已发布修正版</a>}
    {item.status === "pending" && !item.proposal.knowledge_kind && <p className="text-sm text-destructive">此候选缺少分类，请退回并补齐分类后重新提出修正。</p>}
    {item.status === "pending" && !item.sourceCurrent && <p className="text-sm text-destructive">原经验已变化，不能发布此候选；可退回后基于当前版本重新提出修正。</p>}
    {item.status === "pending" && canReview && item.proposerId !== userId && <div className="space-y-2"><label className="block text-xs">审核理由<textarea className="mt-1 block min-h-20 w-full rounded-md border bg-background p-2 text-sm" maxLength={5000} value={reason} onChange={event => setReason(event.target.value)} /></label><div className="flex flex-wrap gap-2"><Button size="sm" disabled={busy || !reason.trim() || !item.sourceCurrent || !item.proposal.knowledge_kind} onClick={() => review("publish")}>发布修正版并归档原版</Button><Button size="sm" variant="outline" disabled={busy || !reason.trim()} onClick={() => review("reject")}>退回修正</Button></div></div>}
    {item.status === "pending" && item.proposerId === userId && <p className="text-xs text-muted-foreground">等待另一位有权限的成员审核。</p>}
    {item.reviewReason && <p className="whitespace-pre-wrap text-sm">审核意见：{item.reviewReason}</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </li>;
}

export function KnowledgeCorrections({ projectId, canReview, userId, onChanged }: { projectId: string; canReview: boolean; userId: string; onChanged: () => void }) {
  const [items, setItems] = useState<Correction[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    request(`projects/${projectId}/knowledge-corrections`).then(value => {
      if (!isRecord(value) || !Array.isArray(value.items)) throw new Error("修正清单不完整");
      const parsed = value.items.map(correction);
      if (active) setItems(parsed);
    }).catch(error => { if (active) setError(error instanceof Error ? error.message : "修正清单暂不可用"); });
    return () => { active = false; };
  }, [projectId, revision]);
  const refresh = () => { setItems(null); setError(null); setRevision(value => value + 1); };
  const focus = typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("correction");
  const sorted = items ? [...items].sort((a, b) => Number(b.id === focus) - Number(a.id === focus)) : null;
  return <section className="mt-5 space-y-3 rounded-lg border bg-card p-4" aria-label="知识修正审核">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">知识修正与审核</h2><Button size="sm" variant="outline" onClick={refresh}>刷新修正清单</Button></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {!items && !error && <p className="text-sm text-muted-foreground">正在读取修正候选…</p>}
    {items?.length === 0 && <p className="text-sm text-muted-foreground">当前没有修正候选。可从已审核经验卡提出修正。</p>}
    {sorted && <ul className="space-y-3">{sorted.map(item => <CorrectionReview key={`${item.id}:${revision}`} item={item} canReview={canReview} userId={userId} onChanged={() => { refresh(); onChanged(); }} />)}</ul>}
  </section>;
}
