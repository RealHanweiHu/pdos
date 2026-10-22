"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle, LockKey, ShareNetwork, WarningCircle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { ProposalSourceInspector } from "@/components/preproject/proposal-source-inspector";
import type { ProposalViewDocument } from "@/components/preproject/proposal-view-contracts";

type Operation = "proposal.share" | "evidence.claim.withdraw";
type Command = { command_id: string; idempotency_key: string; category_id: string; product_id: null; operation: Operation; expected_revision: number; source_read_set: never[]; payload: Record<string, unknown> };
type Hit = { kind: string; value: string; claim_id?: string };
type Checks = { hits: Hit[]; overlap_warnings?: { source_index: number; characters: number; quote: string }[] };
type ClaimPreview = { id: string; version: number; content: unknown; quote: string | null; statement: string | null; checks: Checks };
type Claim = { id: string; version: number; proposal_id: string | null; product_id: string | null; status: string; privacy: string; content: unknown; statement: string | null };
type Proposal = { id: string; category_id: string; owner_id: string; revision: number; visibility: string; private_source_count: number; document_identity: ProposalViewDocument };
type Person = { id: string; name: string };
type Target = { type: string; id: string; version: number };
type Prepared = { command: Command; expires_at: string | null; review: { operation: Operation; payload: Record<string, unknown>; effect: string; proposal_revision?: number; claim_revision?: number; checks?: { claims: ClaimPreview[]; hits: Hit[] }; watermark?: { sources: Record<string, unknown>[]; counts: unknown[]; links: string[]; audiences: { id: string; access_epoch: number; expires_at: string | null }[] }; affected_targets?: Target[]; links?: string[] } };
export type ProposalShareReceipt = { id: string; category_id: string; product_id: string | null; operation: Operation; subject_id: string; subject_revision: number; result: Record<string, unknown> };
type Props = { categoryId: string; proposalId: string; principalId: string; onChanged?: (receipt: ProposalShareReceipt) => void | Promise<void> };
type Pending = { stage: "preview" | "apply"; command: Command; failed: boolean; uncertain: boolean; reprepare?: boolean; terminal?: boolean };
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, child]) => `${JSON.stringify(key)}:${canonical(child)}`).join(",")}}`;
  return JSON.stringify(value);
}
type Journal = { outcome: "unknown" | "confirmation_rejected" | "version_rejected" | "terminal_rejected"; version: 1; actor_id: string; category_id: string; proposal_id: string; command: Command };
const canReprepare = (outcome: unknown) => outcome === "confirmation_rejected" || outcome === "version_rejected";
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const exactKeys = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && Object.keys(value).every(key => keys.includes(key));
function journalCommand(value: unknown, actor: string, category: string, proposal: string): Command {
  if (!record(value) || !exactKeys(value, ["outcome", "version", "actor_id", "category_id", "proposal_id", "command"]) || !["unknown", "confirmation_rejected", "version_rejected", "terminal_rejected"].includes(String(value.outcome)) || value.version !== 1 || value.actor_id !== actor || value.category_id !== category || value.proposal_id !== proposal || !record(value.command)) throw new Error("原请求恢复记录不完整，请保留记录并核对。");
  const command = value.command, payload = command.payload;
  if (!exactKeys(command, ["command_id", "idempotency_key", "category_id", "product_id", "operation", "expected_revision", "source_read_set", "payload"]) || typeof command.command_id !== "string" || !command.command_id || typeof command.idempotency_key !== "string" || command.idempotency_key.length < 8 || command.category_id !== category || command.product_id !== null || !Number.isSafeInteger(command.expected_revision) || Number(command.expected_revision) < 1 || !Array.isArray(command.source_read_set) || command.source_read_set.length || !record(payload) || typeof payload.confirmation_token !== "string" || payload.confirmation_token.length < 20) throw new Error("原请求恢复记录不完整，请保留记录并核对。");
  if (command.operation === "proposal.share") {
    if (!exactKeys(payload, ["proposal_id", "expected_revision", "visibility", "audience_ids", "deidentified_confirmed", "confirmation_token"]) || payload.proposal_id !== proposal || payload.expected_revision !== command.expected_revision || !["category", "audience"].includes(String(payload.visibility)) || !Array.isArray(payload.audience_ids) || payload.audience_ids.some(id => typeof id !== "string") || payload.deidentified_confirmed !== true) throw new Error("原共享请求的范围或确认材料不完整。");
  } else if (command.operation === "evidence.claim.withdraw") {
    if (!exactKeys(payload, ["claim_id", "expected_version", "reason", "confirmation_token"]) || typeof payload.claim_id !== "string" || !payload.claim_id || !Number.isSafeInteger(payload.expected_version) || Number(payload.expected_version) < 1 || typeof payload.reason !== "string" || !payload.reason.trim()) throw new Error("原撤回请求的范围或确认材料不完整。");
  } else throw new Error("恢复记录不是本入口的共享或撤回请求。");
  return command as Command;
}
const print = (value: unknown) => typeof value === "string" ? value : JSON.stringify(value, null, 2);
const hitLabels: Record<string, string> = { identity: "客户身份", filename: "原件文件名", private_ref: "私有引用", url: "来源地址" };
class RequestFailure extends Error {
  constructor(message: string, readonly uncertain: boolean, readonly detail?: { hits?: Hit[]; reason?: string }, readonly status?: number, readonly code?: string) { super(message); }
}
async function request<T>(path: string, signal: AbortSignal, body?: Command): Promise<T> {
  const response = await fetch(`/api/v1/${path}`, { method: body ? "POST" : "GET", signal, cache: "no-store", headers: { "Content-Type": "application/json" }, ...(body ? { body: JSON.stringify(body) } : {}) });
  const value = await response.json();
  if (!response.ok) throw new RequestFailure(value.message ?? "请求未完成，请重试原请求。", response.status >= 500, value.detail, response.status, value.code);
  return value;
}
function Hits({ hits }: { hits: Hit[] }) {
  return hits.length ? <ul className="space-y-2 text-sm">{hits.map((hit, index) => <li key={index} className="break-words [overflow-wrap:anywhere]">{hitLabels[hit.kind] ?? hit.kind}：{hit.value}{hit.claim_id && <span className="block text-xs text-muted-foreground">事实编号：{hit.claim_id}</span>}</li>)}</ul> : <p className="text-sm">本次服务器检查未命中身份信息。</p>;
}
export function ProposalShare(props: Props) {
  return <ScopedProposalShare key={`${props.categoryId}:${props.proposalId}:${props.principalId}`} {...props} />;
}
function ScopedProposalShare({ categoryId, proposalId, principalId, onChanged }: Props) {
  const root = `categories/${categoryId}`;
  const journalKey = `pdos:proposal-share:v1:${encodeURIComponent(principalId)}:${encodeURIComponent(categoryId)}:${encodeURIComponent(proposalId)}`;
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [visibility, setVisibility] = useState<"" | "category" | "audience">("");
  const [audience, setAudience] = useState<string[]>([]);
  const [deidentified, setDeidentified] = useState(false);
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [recoveryBlocked, setRecoveryBlocked] = useState(false);
  const journal = useRef<Command | null>(null), blocked = useRef(false), rejected = useRef(false);
  const [selectedClaim, setSelectedClaim] = useState<Claim | null>(null);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [claimsLoaded, setClaimsLoaded] = useState(false);
  const [cursor, setCursor] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errorHits, setErrorHits] = useState<Hit[]>([]);
  const [receipt, setReceipt] = useState<ProposalShareReceipt | null>(null);
  const live = useRef(false), active = useRef(false), controllers = useRef(new Set<AbortController>());
  const generation = useRef(0);
  const valid = (sequence: number) => live.current && sequence === generation.current;
  const controller = () => { const value = new AbortController(); controllers.current.add(value); return value; };
  const clearPreview = () => { setPrepared(null); setPending(null); setDeidentified(false); };

  function clearPrivateDisplay() {
    setProposal(null); setPeople([]); setClaims([]); setClaimsLoaded(false); setCursor(null);
    setSelectedClaim(null); setPrepared(null); setErrorHits([]); setReason(""); setVisibility(""); setAudience([]); setDeidentified(false);
    // The sealed submitted request remains in pending/journal, never as rendered content.
  }
  function displayFailure(failure: unknown) {
    setError((failure as Error).message);
    if (failure instanceof RequestFailure && (failure.status === 401 || failure.status === 403)) clearPrivateDisplay();
  }
  function writeJournal(command: Command, outcome: Journal["outcome"]) {
    const saved: Journal = { outcome, version: 1, actor_id: principalId, category_id: categoryId, proposal_id: proposalId, command };
    journalCommand(saved, principalId, categoryId, proposalId);
    const serialized = JSON.stringify(saved);
    window.sessionStorage.setItem(journalKey, serialized);
    if (window.sessionStorage.getItem(journalKey) !== serialized) throw new Error("无法保存原请求，尚未发送；请恢复会话存储后重试。");
    journal.current = command; rejected.current = canReprepare(outcome);
  }
  function preserveApply(command: Command) {
    const existing = window.sessionStorage.getItem(journalKey);
    if (existing) {
      const saved = JSON.parse(existing), original = journalCommand(saved, principalId, categoryId, proposalId);
      if (canonical(original) !== canonical(command) && !(canReprepare(saved.outcome) && original.command_id === command.command_id && original.idempotency_key === command.idempotency_key && original.operation === command.operation)) throw new Error("尚有原请求待核对，未发送新请求。");
    }
    writeJournal(command, "unknown");
  }
  function clearMatchedJournal(command: Command) {
    const existing = window.sessionStorage.getItem(journalKey);
    if (existing && canonical(journalCommand(JSON.parse(existing), principalId, categoryId, proposalId)) !== canonical(command)) throw new Error("另有待核对请求，已保留恢复记录。");
    window.sessionStorage.removeItem(journalKey);
    if (window.sessionStorage.getItem(journalKey) !== null) throw new Error("成功回执已取得，但原请求恢复记录暂未清理。");
    journal.current = null; rejected.current = false;
  }

  async function readDocument(sequence: number, signal: AbortSignal) {
    setProposal(null); setPeople([]); setClaims([]); setClaimsLoaded(false); setCursor(null);
    const [document, members] = await Promise.all([
      request<Proposal>(`${root}/proposals/${proposalId}`, signal),
      request<{ items: Person[] }>(`${root}/proposals/${proposalId}/participants`, signal),
    ]);
    if (!valid(sequence)) return;
    if (document.id !== proposalId || document.category_id !== categoryId || document.document_identity?.proposal_id !== proposalId || !Number.isSafeInteger(document.revision) || document.revision < 1 || typeof document.document_identity.document_digest !== "string" || !document.document_identity.document_digest) throw new Error("返回文档与当前提案不一致，请重新读取。");
    setProposal(document); setPeople(members.items);
    return document;
  }
  async function reload(preservePending = false) {
    if (active.current || (!preservePending && (journal.current || blocked.current))) return;
    active.current = true; setBusy(true); if (!preservePending) clearPreview(); setSelectedClaim(null); if (!preservePending) setError(""); setErrorHits([]);
    const sequence = ++generation.current, abort = controller();
    try { await readDocument(sequence, abort.signal); }
    catch (failure) { if (valid(sequence)) displayFailure(failure); }
    finally { controllers.current.delete(abort); if (valid(sequence)) { active.current = false; setBusy(false); } }
  }
  useEffect(() => {
    live.current = true;
    try {
      const stored = window.sessionStorage.getItem(journalKey);
      if (stored) {
        const saved = JSON.parse(stored), command = journalCommand(saved, principalId, categoryId, proposalId);
        journal.current = command; rejected.current = canReprepare(saved.outcome);
        setPending({ stage: "apply", command, failed: true, uncertain: !rejected.current && saved.outcome !== "terminal_rejected", reprepare: rejected.current, terminal: saved.outcome === "terminal_rejected" });
        setError(saved.outcome === "terminal_rejected" ? "原撤回操作已被服务器永久拒绝。可明确结束本次操作；不会自动发送。" : "找到待核对的原请求。请本人重试原请求取得实际回执；不会自动发送。");
      }
    } catch {
      blocked.current = true; setRecoveryBlocked(true); setError("无法读取有效的原请求恢复记录。已暂停新请求，请恢复会话存储或核对原记录。");
    }
    void reload(true);
    const running = controllers.current, epoch = generation;
    return () => { live.current = false; epoch.current++; active.current = false; running.forEach(item => item.abort()); running.clear(); };
    // The keyed instance owns exactly one category, proposal and signed-in person.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadClaims(next: string | null = null) {
    if (active.current || journal.current || blocked.current || pending || prepared || !proposal) return;
    active.current = true; setBusy(true); setError(""); setErrorHits([]);
    const sequence = generation.current, abort = controller();
    const query = new URLSearchParams({ proposal_id: proposalId, status: "active", page_size: "50" });
    if (next) query.set("cursor", next);
    try {
      const page = await request<{ items: Claim[]; next_cursor: string | null }>(`${root}/claims?${query}`, abort.signal);
      if (!valid(sequence)) return;
      if (page.items.some(claim => claim.proposal_id !== proposalId)) throw new Error("事实列表与当前提案不一致。");
      setClaims(previous => next ? [...previous, ...page.items.filter(claim => !previous.some(item => item.id === claim.id))] : page.items); setCursor(page.next_cursor); setClaimsLoaded(true);
    } catch (failure) { if (valid(sequence)) displayFailure(failure); }
    finally { controllers.current.delete(abort); if (valid(sequence)) { active.current = false; setBusy(false); } }
  }
  async function selectClaim(id: string) {
    if (active.current || journal.current || blocked.current || pending?.stage === "apply") return;
    active.current = true; setBusy(true); clearPreview(); setSelectedClaim(null); setReason(""); setError(""); setErrorHits([]);
    const sequence = generation.current, abort = controller();
    try {
      const claim = await request<Claim>(`${root}/claims/${id}`, abort.signal);
      if (!valid(sequence)) return;
      if (claim.id !== id || claim.proposal_id !== proposalId || claim.product_id !== null || claim.status !== "active") throw new Error("此事实不属于当前可办理的提案范围，或已失效；请重新读取。");
      setSelectedClaim(claim);
    } catch (failure) { if (valid(sequence)) displayFailure(failure); }
    finally { controllers.current.delete(abort); if (valid(sequence)) { active.current = false; setBusy(false); } }
  }
  function command(operation: Operation, payload: Record<string, unknown>): Command {
    return { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), category_id: categoryId, product_id: null, operation, expected_revision: proposal!.revision, source_read_set: [], payload };
  }
  async function execute(job: Pending) {
    if (active.current || blocked.current || (job.stage === "preview" && journal.current && !job.reprepare)) return;
    active.current = true; setBusy(true); setPending(job); setError(""); setErrorHits([]);
    const sequence = generation.current, abort = controller();
    try {
      if (job.stage === "preview") {
        const result = await request<Prepared>(`${root}/commands/preview`, abort.signal, job.command);
        if (!valid(sequence)) return;
        const { confirmation_token, ...semantic } = result.command.payload;
        const returned = { ...result.command, payload: semantic };
        if (typeof confirmation_token !== "string" || confirmation_token.length < 20 || canonical(returned) !== canonical(job.command)
          || result.command.command_id !== job.command.command_id || result.command.idempotency_key !== job.command.idempotency_key
          || result.command.category_id !== categoryId || result.command.product_id !== null || result.command.operation !== job.command.operation
          || result.command.expected_revision !== job.command.expected_revision || result.command.source_read_set.length !== 0
          || result.review.operation !== job.command.operation) throw new Error("返回预览与原请求不一致，请重试原请求。");
        if (job.command.operation === "proposal.share" && (!result.review.checks || !result.review.watermark || result.review.proposal_revision !== job.command.payload.expected_revision)) throw new Error("共享检查材料不完整，请重试原请求。");
        if (job.command.operation === "evidence.claim.withdraw" && (!result.review.affected_targets || result.review.claim_revision !== job.command.payload.expected_version)) throw new Error("撤回影响材料不完整，请重试原请求。");
        setPrepared(result); setPending(null);
      } else {
        // Persist only this exact sealed command, before the first network attempt.
        preserveApply(job.command);
        const result = await request<ProposalShareReceipt>(`${root}/commands`, abort.signal, job.command);
        if (!valid(sequence)) return;
        const subject = job.command.payload.proposal_id ?? job.command.payload.claim_id;
        if (!result.id || result.category_id !== categoryId || result.product_id !== null || result.operation !== job.command.operation || result.subject_id !== subject) throw new Error("回执与原请求不一致，请重试原请求核对结果。");
        setReceipt(result); clearPreview(); setSelectedClaim(null); setReason("");
        // Notify immediately; parent invalidation must not wait for our GETs.
        let parentRefresh: Promise<void>;
        try { parentRefresh = Promise.resolve(onChanged?.(result)); }
        catch { parentRefresh = Promise.reject(new Error("parent_refresh_failed")); }
        const parentFinished = parentRefresh.catch(() => { if (valid(sequence)) setError("操作已成功；提案页面刷新失败，请重新读取文档与视图。"); });
        try { clearMatchedJournal(job.command); }
        catch { if (valid(sequence)) { setPending({ ...job, failed: true, uncertain: true }); setError("操作已成功；原请求恢复记录暂未清理，可重试原请求核对回执。"); } }
        // The receipt remains success even when either read or parent refresh fails.
        if (valid(sequence)) {
          try { await readDocument(sequence, abort.signal); }
          catch (failure) { if (valid(sequence)) { displayFailure(failure); setError(`操作已成功；重新读取提案失败：${(failure as Error).message}`); } }
        }
        await parentFinished;
      }
    } catch (failure) {
      if (valid(sequence)) { setPending({ ...job, failed: true, uncertain: !(failure instanceof RequestFailure) || failure.uncertain }); setError((failure as Error).message); setErrorHits(failure instanceof RequestFailure ? failure.detail?.hits ?? [] : []);
        // The category host checks both receipt indexes again under its gate before
        // owner validation. Only these exact 409 reasons prove a rejected effect.
        if (failure instanceof RequestFailure && failure.status === 409) {
          const reason = failure.detail?.reason;
          const terminal = job.command.operation === "evidence.claim.withdraw" && failure.code === "UNDO_BLOCKED_BY_DEPENDENCY" && reason === "consumed_by_decision";
          const retryable = job.stage === "apply" && (
            (failure.code === "CONFIRMATION_REQUIRED" && ["CONFIRMATION_REQUIRED", "CONFIRMATION_SCOPE_CHANGED"].includes(reason ?? ""))
            || (job.command.operation === "proposal.share" && failure.code === "VERSION_CONFLICT" && reason === "evidence_version_moved")
          );
          if (terminal || retryable) {
            try {
              if (terminal) {
                const original = journal.current ?? job.command;
                clearPrivateDisplay();
                if (journal.current) writeJournal(original, "terminal_rejected");
                setPending({ ...job, command: original, failed: true, uncertain: false, reprepare: false, terminal: true });
              } else {
                writeJournal(job.command, failure.code === "VERSION_CONFLICT" ? "version_rejected" : "confirmation_rejected");
                setPending({ ...job, failed: true, uncertain: false, reprepare: true });
              }
            } catch { setError("恢复状态暂未保存，请保留原请求并核对。"); }
          }
        }
        displayFailure(failure);
      }
    } finally { controllers.current.delete(abort); if (valid(sequence)) { active.current = false; setBusy(false); } }
  }
  async function reprepareRejected() {
    if (active.current || !journal.current || !rejected.current || blocked.current) return;
    const original = journal.current, sequence = ++generation.current, abort = controller();
    active.current = true; setBusy(true); setPrepared(null); setError(""); setErrorHits([]);
    let next: Command | null = null;
    try {
      const current = await readDocument(sequence, abort.signal);
      if (!valid(sequence) || !current) return;
      const payload = { ...original.payload }; delete payload.confirmation_token;
      if (original.operation === "proposal.share") payload.expected_revision = current.revision;
      else {
        const claim = await request<Claim>(`${root}/claims/${payload.claim_id}`, abort.signal);
        if (!valid(sequence)) return;
        if (claim.id !== payload.claim_id || claim.proposal_id !== proposalId || claim.product_id !== null || claim.status !== "active") throw new Error("原撤回目标已改变，请保留原请求并核对当前事实。");
        payload.expected_version = claim.version;
      }
      next = { ...original, expected_revision: current.revision, payload };
    } catch (failure) { if (valid(sequence)) displayFailure(failure); }
    finally { controllers.current.delete(abort); if (valid(sequence)) { active.current = false; setBusy(false); } }
    if (valid(sequence) && next) await execute({ stage: "preview", command: next, failed: false, uncertain: false, reprepare: true });
  }
  function endTerminalRejection() {
    if (active.current || !pending?.terminal) return;
    try {
      const existing = window.sessionStorage.getItem(journalKey);
      if (journal.current || existing) {
        if (!existing) throw new Error("拒绝记录已变化，请保留原请求并重新核对。");
        const saved = JSON.parse(existing), original = journalCommand(saved, principalId, categoryId, proposalId);
        if (saved.outcome !== "terminal_rejected" || canonical(original) !== canonical(pending.command)) throw new Error("原请求尚未证明被永久拒绝，不能结束恢复。");
        window.sessionStorage.removeItem(journalKey);
        if (window.sessionStorage.getItem(journalKey) !== null) throw new Error("拒绝记录暂未清理，请重试结束本次操作。");
      }
      journal.current = null; rejected.current = false;
      clearPrivateDisplay(); clearPreview(); setReceipt(null);
      void reload();
    } catch (failure) { displayFailure(failure); }
  }
  function cancelPreview() {
    clearPreview();
    if (journal.current) setPending({ stage: "apply", command: journal.current, failed: true, uncertain: !rejected.current, reprepare: rejected.current });
  }
  const owner = proposal?.owner_id === principalId;
  const locked = busy || recoveryBlocked || !!pending || !!prepared;
  const shareReview = prepared?.command.operation === "proposal.share" ? prepared.review : null;
  const ambiguousApply = pending?.stage === "apply";
  return <section aria-label="提案共享与事实撤回" className="space-y-4 rounded-lg border p-4 sm:p-5">
    <h2 className="flex items-center gap-2 text-lg font-semibold"><ShareNetwork className="text-primary" />共享与事实撤回</h2>
    <p className="text-sm text-muted-foreground">仅由提案负责人本人办理。预览不会共享或撤回；请核对后再确认。</p>
    {receipt && <div role="status" className="space-y-1 rounded-lg border p-3"><p className="flex items-center gap-2"><CheckCircle className="text-primary" />{receipt.operation === "proposal.share" ? "共享成功" : "事实已撤回，引用条目值保留"}</p><p className="break-all text-xs text-muted-foreground">回执：{receipt.id}</p></div>}
    {busy && <p role="status">正在核对当前材料…</p>}
    {error && <div role="alert" className="space-y-2"><p className="flex items-start gap-2"><WarningCircle className="shrink-0" />{error}</p>{errorHits.length > 0 && <Hits hits={errorHits} />}</div>}
    <Button type="button" variant="outline" disabled={busy || recoveryBlocked || !!pending || !!prepared} onClick={() => void reload()}>重新读取提案</Button>
    {proposal && <p className="break-words text-xs text-muted-foreground [overflow-wrap:anywhere]">当前提案第 {proposal.revision} 版 · 阅读文档第 {proposal.document_identity.revision} 版 · 文档摘要：{proposal.document_identity.document_digest}<br />当前可见范围：{({ private: "私有", category: "品类成员", audience: "指定成员" } as Record<string, string>)[proposal.visibility] ?? proposal.visibility} · 私有来源 {proposal.private_source_count} 项</p>}
    {proposal && !owner && <p className="flex items-center gap-2 text-sm"><LockKey />仅提案负责人可办理共享与本提案私有事实撤回。</p>}
    {owner && <>
      {!selectedClaim && !prepared && <form className="space-y-3" onSubmit={event => { event.preventDefault(); if (!locked && visibility && deidentified && (visibility !== "audience" || audience.length)) void execute({ stage: "preview", command: command("proposal.share", { proposal_id: proposalId, expected_revision: proposal.revision, visibility, audience_ids: visibility === "audience" ? audience : [], deidentified_confirmed: deidentified }), failed: false, uncertain: false }); }}>
        <fieldset disabled={locked} className="space-y-3"><legend className="mb-2 font-medium">选择共享范围</legend>
          <label className="flex items-center gap-2"><input type="radio" name="share-scope" checked={visibility === "category"} onChange={() => { setVisibility("category"); setAudience([]); setDeidentified(false); }} />品类内有效成员</label>
          <label className="flex items-center gap-2"><input type="radio" name="share-scope" checked={visibility === "audience"} onChange={() => { setVisibility("audience"); setDeidentified(false); }} />指定品类成员</label>
          {visibility === "audience" && <div className="space-y-2 pl-5">{people.filter(person => person.id !== principalId).map(person => <label key={person.id} className="flex items-center gap-2"><input type="checkbox" checked={audience.includes(person.id)} onChange={event => { setAudience(current => event.target.checked ? [...current, person.id] : current.filter(id => id !== person.id)); setDeidentified(false); }} />{person.name}</label>)}</div>}
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={deidentified} onChange={event => setDeidentified(event.target.checked)} />我确认拟共享内容已去除客户身份；将逐项核对服务器预览。</label>
          <Button disabled={!visibility || !deidentified || (visibility === "audience" && !audience.length)}>预览共享影响</Button>
        </fieldset>
      </form>}
      {!prepared && !selectedClaim && <div className="space-y-3"><Button type="button" variant="outline" disabled={locked} onClick={() => void loadClaims()}>读取可撤回事实</Button>{claimsLoaded && claims.length === 0 && <p className="text-sm">未读到本提案的有效事实。</p>}{claims.map(claim => <div key={claim.id} className="space-y-2 rounded-lg border p-3"><p className="break-all text-xs">事实编号：{claim.id} · 第 {claim.version} 版</p><p className="whitespace-pre-wrap break-words text-sm">{claim.statement ?? print(claim.content)}</p>{claim.product_id !== null ? <p className="text-sm text-muted-foreground">此事实属于型号范围，当前入口暂不办理。</p> : <Button type="button" variant="outline" disabled={locked} onClick={() => void selectClaim(claim.id)}>准备撤回此事实</Button>}</div>)}{cursor && <Button type="button" variant="outline" disabled={locked} onClick={() => void loadClaims(cursor)}>读取下一页</Button>}</div>}
      {selectedClaim && !prepared && <form className="space-y-3" onSubmit={event => { event.preventDefault(); if (!locked && reason.trim()) void execute({ stage: "preview", command: command("evidence.claim.withdraw", { claim_id: selectedClaim.id, expected_version: selectedClaim.version, reason: reason.trim() }), failed: false, uncertain: false }); }}><p className="break-all text-sm">撤回事实：{selectedClaim.id} · 第 {selectedClaim.version} 版</p><p className="whitespace-pre-wrap break-words text-sm">{selectedClaim.statement ?? print(selectedClaim.content)}</p><label className="block text-sm">撤回原因<textarea required disabled={locked} value={reason} onChange={event => setReason(event.target.value)} className="mt-1 block w-full rounded-lg border bg-background p-2" /></label><Button disabled={locked || !reason.trim()}>预览撤回影响</Button><Button type="button" variant="ghost" disabled={locked} onClick={() => setSelectedClaim(null)}>取消撤回准备</Button></form>}
    </>}
    {prepared && <section aria-label="确认预览" className="space-y-3 rounded-lg border p-4">
      <h3 className="font-semibold">{shareReview ? "共享前核对" : "撤回前核对"}</h3><p className="text-sm">{prepared.review.effect}</p><p className="text-xs text-muted-foreground">确认有效期：{prepared.expires_at ?? "服务器未提供"}</p>
      {shareReview && <><p className="text-sm">共享范围：{prepared.command.payload.visibility === "category" ? "品类内有效成员" : "指定品类成员"}。现任评审人的阅读权限仍保留。</p><p className="text-sm">指定受众：{shareReview.watermark!.audiences.map(person => people.find(item => item.id === person.id)?.name ?? person.id).join("、") || "按上述品类范围办理"}</p><p className="text-sm">本人已确认去除客户身份。</p><Hits hits={shareReview.checks!.hits} />
        <h4 className="font-medium">将随共享可见的私有上下文事实 · {shareReview.checks!.claims.length} 条</h4>
        {shareReview.checks!.claims.map(claim => <div key={claim.id} className="space-y-2 rounded-lg border p-3"><p className="break-all text-xs">私有事实编号：{claim.id} · 第 {claim.version} 版</p><p className="whitespace-pre-wrap break-words text-sm">{print(claim.content)}</p>{claim.statement && <p className="whitespace-pre-wrap text-sm">陈述：{claim.statement}</p>}{claim.quote && <blockquote className="whitespace-pre-wrap border-l-2 pl-3 text-sm">{claim.quote}</blockquote>}<Hits hits={claim.checks.hits} />{claim.checks.overlap_warnings?.map((warning, index) => <p key={index} className="whitespace-pre-wrap text-sm">与原件文字重叠 {warning.characters} 字（请本人判断）：{warning.quote}</p>)}<Button type="button" variant="outline" disabled={busy || !!pending} onClick={() => void selectClaim(claim.id)}>改为准备撤回此事实</Button></div>)}
        <details className="space-y-2 text-sm"><summary className="cursor-pointer">本次核对水印（来源、版本和受众权限）</summary><ProposalSourceInspector sources={shareReview.watermark!.sources} /><p>来源引用计数：{print(shareReview.watermark!.counts)}</p><p className="break-all">证据关联编号：{shareReview.watermark!.links.join("、") || "无"}</p>{shareReview.watermark!.audiences.map(person => <p key={person.id} className="break-all">{people.find(item => item.id === person.id)?.name ?? person.id} · 权限版本 {person.access_epoch} · 到期：{person.expires_at ?? "未设到期时间"}</p>)}</details></>}
      {!shareReview && <><p className="break-all text-sm">事实编号：{prepared.command.payload.claim_id as string} · 第 {prepared.review.claim_revision} 版</p><p className="whitespace-pre-wrap text-sm">撤回原因：{prepared.command.payload.reason as string}</p><h4 className="font-medium">受影响条目</h4><ul className="space-y-1 text-sm">{prepared.review.affected_targets!.map((target, index) => <li key={index} className="break-all">{({ proposal: "提案", proposal_item: "提案条目", knowledge_entry: "品类知识", definition_spec: "定义规格" } as Record<string, string>)[target.type] ?? target.type}：{target.id} · 第 {target.version} 版</li>)}</ul><p className="text-sm">已签署决定或封存定义消费的事实由服务器拒绝撤回。</p></>}
      <Button type="button" disabled={busy || !!pending || !!shareReview?.checks?.hits.length} onClick={() => void execute({ stage: "apply", command: prepared.command, failed: false, uncertain: false })}>{shareReview ? "本人确认共享" : "本人确认撤回"}</Button>
      <Button type="button" variant="ghost" disabled={busy || !!pending} onClick={cancelPreview}>取消本次预览</Button>
    </section>}
    {pending?.failed && <div className="space-y-2"><p className="text-sm">{pending.terminal ? "事实已被签署决定或封存定义消费，本次撤回永久拒绝；可结束本次操作。" : pending.reprepare ? "服务器已明确拒绝本次确认或版本。可重新读取并预览原操作，再由本人确认。" : ambiguousApply ? "保留已提交的原请求。请重试原请求核对回执；不要重新创建请求。" : "保留原请求，可重试；重新准备前请放弃本次预览并刷新材料。"}</p>{!pending.terminal && <Button type="button" disabled={busy} onClick={() => void execute({ ...pending, failed: false })}>重试原请求</Button>}{pending.terminal && <Button type="button" variant="outline" disabled={busy} onClick={endTerminalRejection}>结束这项已拒绝操作</Button>}{pending.reprepare && <Button type="button" variant="outline" disabled={busy} onClick={() => void reprepareRejected()}>重新读取并预览原操作</Button>}{!ambiguousApply && !pending.reprepare && !pending.terminal && <Button type="button" variant="outline" disabled={busy} onClick={() => void reload()}>放弃本次预览并刷新</Button>}</div>}
  </section>;
}
