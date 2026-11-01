"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ArrowClockwise, CheckCircle, WarningCircle, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { CandidateForm } from "./candidate-form";
import { snapshot } from "./ui-contract";
import type { CandidateFormPayload } from "./candidate-form-contract";
import {
  blankCandidateLocal, candidateBasisChanged, candidateCanPrepare, candidateFailureOutcome, candidateErrorStatus,
  candidateHostBasis, candidateIdentity, candidateInputsCommand, candidatePrepared, candidateReceipt,
  candidateSaved, newCandidateCommand, restoreCandidateLocal,
  type CandidateCommand, type CandidateHost, type CandidateLocal, type CandidatePending,
  type CandidatePrepared, type CandidateReceipt,
} from "./candidate-workflow-state";

export type CandidateWorkflowProps = {
  host: CandidateHost;
  api: <T>(path: string, body?: unknown) => Promise<T>;
  /** Root connects the real read-only input owner/route; never an assumed HTTP path. */
  inputs: (command: CandidateCommand) => Promise<unknown>;
  /** Complete business reading of this operation's actual 13-field material, never a raw JSON editor. */
  renderReview: (review: CandidatePrepared["review"], command: CandidateCommand) => { content: ReactNode; complete: boolean } | null;
  onSaved: (receipt: CandidateReceipt) => Promise<void>;
  onRefresh: () => Promise<void>;
  /** Parent locks scope/choice controls whenever a same-key request is unresolved. */
  onPendingChange?: (locked: boolean) => void;
  onAccessRejected?: (saved?: boolean) => void;
  /** Explicit read failure gate. Never changes server capability or unlocks UNKNOWN. */
  blocked?: boolean;
  /** Only an actual GET 401/403 or mismatched scope can set this signal. */
  hostAccessRejected?: boolean;
  /** Advances only after a fresh, validated GET in this same scope. */
  hostAccessEpoch?: number;
};
const wrap = "min-w-0 [overflow-wrap:anywhere]";
const contentPresent = (value: ReactNode): boolean => Array.isArray(value) ? value.some(contentPresent) :
  value !== null && value !== undefined && value !== false && value !== true && value !== "";

/** Only the exact host scope is mounted. No GET, qualification, clock, or failure-pair construction. */
export function CandidateWorkflow(props: CandidateWorkflowProps) {
  const identity = candidateIdentity(props.host);
  if (!identity) return <section className="panel space-y-3" aria-label="复验候选办理">
    <h3 className="font-semibold">复验候选办理</h3>
    <p className="text-sm">当前固定问题、整改或访问范围尚不能核对，请先读取当前事实。</p>
  </section>;
  return <CandidateFlow key={identity} {...props} identity={identity} />;
}
function CandidateFlow({ host, api, inputs, renderReview, onSaved, onRefresh, onPendingChange,
  onAccessRejected, blocked = false, hostAccessRejected = false, hostAccessEpoch = 0,
  identity }: CandidateWorkflowProps & { identity: string }) {
  const [local, setLocal] = useState<CandidateLocal>(() => blankCandidateLocal(identity));
  const [preview, setPreview] = useState<CandidatePrepared | null>(null);
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [ready, setReady] = useState(false), [readRequired, setReadRequired] = useState(false);
  const [rejected, setRejected] = useState(false), [formEpoch, setFormEpoch] = useState(0);
  const current = useRef(local), live = useRef<{ basis: string | null; host: CandidateHost }>({ basis: null, host });
  const mounted = useRef(false), locked = useRef(false), restored = useRef(false), dialog = useRef<HTMLDialogElement>(null);
  const privacyRejected = useRef(false), rejectedEpoch = useRef<string | null>(null);
  const initialBasis = useRef<string | null | undefined>(undefined);
  const storageKey = `pdos-next:capa-candidate:${identity}`;
  const basis = candidateHostBasis(host);
  const save = useCallback((next: CandidateLocal) => {
    current.current = snapshot(next);
    try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* In-memory exact recovery remains available. */ }
    if (mounted.current) setLocal(current.current);
  }, [storageKey]);
  const clearPrivate = useCallback((saved: boolean) => {
    privacyRejected.current = true; rejectedEpoch.current = `${live.current.host.accessEpoch}:${hostAccessEpoch}`;
    const next = { ...blankCandidateLocal(identity), outcome: saved ? "saved" as const : "none" as const };
    current.current = next;
    try { localStorage.removeItem(storageKey); } catch { /* Never retain fallback after access rejection. */ }
    if (mounted.current) { setLocal(next); setPreview(null); setRejected(true); setFormEpoch(epoch => epoch + 1); }
    if (mounted.current) onAccessRejected?.(saved);
  }, [identity, storageKey, onAccessRejected, hostAccessEpoch]);
  useLayoutEffect(() => {
    live.current = { basis, host };
    // Only an explicitly new host-confirmed read epoch can reopen a rejected view.
    // Actual action permissions are still evaluated independently below.
    if (!hostAccessRejected && privacyRejected.current && basis !== null && rejectedEpoch.current !== `${host.accessEpoch}:${hostAccessEpoch}`) {
      privacyRejected.current = false; setRejected(false); setReadRequired(false);
    }
    if (hostAccessRejected && !privacyRejected.current) {
      const saved = current.current.outcome === "saved" || current.current.savedReceipt !== null;
      clearPrivate(saved);
      setNotice(saved ? "已取得保存结果；当前访问不可用，私有材料已清除。不能重发已保存操作。" : "当前读取已失去原范围，私有材料与预览已清除，请重新核对访问范围。");
    }
    if (initialBasis.current !== undefined && initialBasis.current !== basis) {
      save(candidateBasisChanged(current.current)); setPreview(null); setFormEpoch(epoch => epoch + 1);
    }
    initialBasis.current = basis;
    return () => { live.current = { basis: null, host }; };
  }, [basis, host, save, hostAccessRejected, hostAccessEpoch, clearPrivate]);
  useEffect(() => {
    mounted.current = true;
    void Promise.resolve().then(() => {
      if (!mounted.current) return;
      if (!restored.current) {
        restored.current = true;
        try { const stored = restoreCandidateLocal(JSON.parse(localStorage.getItem(storageKey) ?? "null"), identity);
          if (stored) { current.current = stored; setLocal(stored); if (stored.outcome === "saved") { setReadRequired(true); setNotice("已取得保存回执，请只刷新读取，不重复提交。"); } }
        } catch { /* Invalid, different-scope or legacy drafts never become commands. */ }
      }
      setReady(true);
    });
    return () => {
      mounted.current = false;
      // Scope disposal never retains an editable private draft or unused proof.
      // An execute may already have committed, so its exact recovery request survives.
      if (restored.current && !privacyRejected.current) save(candidateBasisChanged(current.current));
    };
  }, [storageKey, identity, save]);
  useEffect(() => { if (ready) onPendingChange?.(local.pending !== null); }, [ready, local.pending, onPendingChange]);
  useEffect(() => { if (preview && !rejected) dialog.current?.showModal(); else dialog.current?.close(); }, [preview, rejected]);

  const rememberDraft = useCallback((draft: CandidateFormPayload | null) => {
    // Clearing editable material must never clear a prepared or UNKNOWN request.
    if (restored.current && !privacyRejected.current && !current.current.pending && !locked.current) save({ ...current.current, draft });
  }, [save]);
  async function perform(waiting: CandidatePending, preparedBasis: string | null) {
    if (locked.current || rejected || hostAccessRejected) return;
    locked.current = true; setBusy(true); setNotice(""); let stage = waiting;
    save({ ...current.current, pending: waiting, outcome: waiting.stage === "execute" ? "unknown" : "none" });
    try {
      if (stage.stage === "inputs") {
        const result = await inputs(stage.command);
        if (privacyRejected.current) return;
        const command = candidateInputsCommand(result, stage.command);
        if (!mounted.current) return;
        if (!command) { save({ ...current.current, pending: null }); setNotice("服务器返回当前缺项，候选尚未提交。请核对当前资料与职责。"); return; }
        if (preparedBasis !== live.current.basis) { save(candidateBasisChanged(current.current)); setNotice("当前范围或材料已变化，请重新选择并核对；尚未提交候选。"); return; }
        stage = { stage: "preview", command }; save({ ...current.current, pending: stage });
      }
      if (stage.stage === "preview") {
        const result = await api<unknown>("v1/commands/preview", stage.command);
        if (privacyRejected.current) return;
        const prepared = candidatePrepared(result, stage.command);
        if (!prepared) throw new Error("尚未取得与原命令、完整来源和选定材料一致的实质预览。");
        if (!mounted.current) return;
        if (preparedBasis !== live.current.basis) { save(candidateBasisChanged(current.current)); setNotice("当前事实已变化，旧预览已废弃；请重新核对实际材料。"); return; }
        setPreview(prepared); return;
      }
      const result = await api<unknown>("v1/commands", stage.command);
      if (!candidateReceipt(result)) throw new Error("尚未取得本候选明确保存回执，请保留原请求恢复。");
      if (privacyRejected.current) {
        clearPrivate(true);
        if (mounted.current) setNotice("已取得保存结果；当前访问不可用，私有材料已清除。不能重发已保存操作。");
        return;
      }
      save(candidateSaved(current.current, result));
      if (!mounted.current) return;
      setPreview(null); setFormEpoch(epoch => epoch + 1); setReadRequired(true);
      setNotice("候选已保存或读取原回执；适用性、独立核验和观察完整性仍待核对，未决定有效性或关闭。");
      await onSaved(result);
      if (mounted.current) setReadRequired(false);
    } catch (failure) {
      const outcome = candidateFailureOutcome(current.current, candidateErrorStatus(failure));
      if (outcome.clearPrivate) clearPrivate(outcome.saved);
      if (!mounted.current) return;
      if (outcome.saved) setNotice(outcome.clearPrivate ? "已取得保存结果；当前访问不可用，私有材料已清除。不能重发已保存操作。" : "已取得保存回执；随后刷新失败，请只重试读取，不能重复提交。");
      else if (outcome.clearPrivate) setNotice("当前访问范围或资格已不可用，私有材料和原预览已清除，请重新核对权限。");
      else if (stage.stage === "execute") { setPreview(null); setNotice("尚未取得确定保存回执，完整原请求与原标识已保留。只能按原请求恢复，不能另造候选或重新确认。"); }
      else setNotice("本次来源核对或完整预览尚未完成，请按原请求恢复；尚未提交候选。");
    } finally { locked.current = false; if (mounted.current) setBusy(false); }
  }
  function submit(payload: CandidateFormPayload) {
    if (locked.current || rejected || hostAccessRejected || blocked || readRequired || current.current.pending || !candidateCanPrepare(live.current.host)) return;
    try { const command = newCandidateCommand(live.current.host, payload, crypto.randomUUID(), crypto.randomUUID());
      void perform({ stage: "inputs", command }, live.current.basis);
    } catch (failure) { setNotice(failure instanceof Error ? failure.message : "请重新核对固定材料。"); }
  }
  function cancel() {
    if (locked.current || current.current.pending?.stage === "execute") return;
    save({ ...current.current, pending: null }); setPreview(null);
  }
  async function refresh() {
    if (locked.current) return; locked.current = true; setBusy(true);
    try { await onRefresh(); if (mounted.current) { setReadRequired(false); setNotice(current.current.outcome === "saved" ? "已保存的候选已请求重新读取，请以服务器当前事实为准。" : "已请求重新读取当前事实；读取不发起业务操作。"); } }
    catch (failure) { const outcome = candidateFailureOutcome(current.current, candidateErrorStatus(failure)); if (outcome.clearPrivate) clearPrivate(outcome.saved);
      if (mounted.current) setNotice(outcome.saved ? "已取得保存结果，当前事实仍读取失败；不能重复提交。" : "当前事实读取失败，本次读取尚未发起候选操作。"); }
    finally { locked.current = false; if (mounted.current) setBusy(false); }
  }
  const review = preview && !rejected && !hostAccessRejected ? renderReview(preview.review, preview.command) : null;
  const completeReview = review?.complete === true && contentPresent(review.content);
  const canConfirm = !busy && !rejected && !hostAccessRejected && !blocked && !readRequired && completeReview && candidateCanPrepare(host) && preview !== null &&
    candidatePrepared(preview, local.pending?.command ?? preview.command) !== null;
  if (!ready) return <section className="panel space-y-3" aria-busy="true"><h3 className="font-semibold">复验候选办理</h3><p className="text-sm">正在读取本机原请求，尚未发起操作。</p></section>;
  if (rejected || hostAccessRejected) return <section className="panel space-y-3" aria-label="复验候选办理">
    <h3 className="font-semibold">复验候选办理</h3><p role="status" className="text-sm">{notice}</p>
    <p className="subtle">当前访问不可用，已隐藏资料与所有办理材料。</p>
    <Button variant="outline" disabled={busy} onClick={() => void refresh()}><ArrowClockwise/>重试读取当前事实</Button>
  </section>;
  return <div className={`space-y-4 ${wrap}`} aria-busy={busy}>
    {host.authority.synthetic && <p className="rounded-lg border border-primary p-3 text-sm">本地合成演练：当前资格与候选用于核验流程，不代表生产资格或措施已有效。</p>}
    {notice && <p role="status" aria-live="polite" className={`flex items-start gap-2 rounded-lg border p-3 text-sm ${wrap}`}>
      {local.outcome === "saved" ? <CheckCircle className="mt-0.5 size-4 shrink-0 text-primary"/> : <WarningCircle className="mt-0.5 size-4 shrink-0"/>}<span>{notice}</span></p>}
    <section className="panel space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">复验候选办理</h3>
        <Button variant="outline" disabled={busy} onClick={() => void refresh()}><ArrowClockwise/>重试读取当前事实</Button></div>
      <p className="text-sm">{host.current_evaluation === "not_evaluated_historical" ? "历史固定版本，当前资格未评估，只读保留。" :
        host.authority.qualified === null ? "当前专业资格尚不能核对。" : host.authority.qualified ? "服务器已返回本操作当前资格核对。" : "当前专业资格不满足，不能办理。"}</p>
      {host.missing.length > 0 && <ul className="list-disc space-y-1 pl-5 text-sm">{host.missing.map((item, index) => <li key={`${item.code}:${index}`}>{item.detail}</li>)}</ul>}
      {local.pending && <div className="space-y-3 rounded-lg border border-primary p-3 text-sm">
        <p>{local.pending.stage === "execute" ? "原提交回执尚待核对" : "原操作核对尚未完成"}</p>
        <p>同一命令、完整材料和原标识已保留。当前输入锁定，不另造一次操作。</p>
        <Button disabled={busy} onClick={() => void perform(local.pending!, live.current.basis)}><ArrowClockwise/>按原请求恢复</Button>
        {local.pending.stage !== "execute" && <Button variant="outline" disabled={busy} onClick={cancel}>取消未提交的核对</Button>}
      </div>}
      {local.savedReceipt && <p className="text-sm">已取得第 {local.savedReceipt.subject_revision} 版候选回执。固定候选不等于措施有效、问题关闭或成品放行。</p>}
    </section>
    <CandidateForm key={formEpoch} scope={host.scope} materials={host.materials}
      disabled={blocked || rejected || hostAccessRejected || readRequired || !candidateCanPrepare(host) || local.pending !== null || preview !== null}
      busy={busy} allowProductVisibility={host.allowProductVisibility}
      disabledReason="当前范围、资格或原请求尚待核对，请先完成原请求恢复或刷新当前事实。"
      onChange={rememberDraft} onSubmit={submit}/>
    <dialog ref={dialog} onCancel={event => { event.preventDefault(); cancel(); }}
      className="m-auto max-h-[85dvh] w-[calc(100%-2rem)] max-w-3xl overflow-y-auto rounded-lg border border-border bg-background p-5 text-foreground backdrop:bg-black/50">
      {preview && <div className={`space-y-4 ${wrap}`}>
        <div className="flex items-start justify-between gap-3"><h3 className="font-semibold">核对本次复验候选（一次确认）</h3>
          <Button variant="ghost" size="icon" disabled={busy} aria-label="返回核对候选材料" onClick={cancel}><X/></Button></div>
        <p className="text-sm">保存本次固定复验候选。适用性、独立核验和观察完整性仍保持未知，不作有效性或关闭决定。</p>
        {completeReview ? review!.content : <p role="alert" className="text-sm">候选完整范围与原失败对应尚未显示，不能确认保存。请由宿主补齐实际核对内容。</p>}
        <p className="subtle">发生时间和原值来自固定材料；保存时由服务器记录的接收时间不补成实际事件。候选保存后仍待独立核验。</p>
        <p className="subtle">本次确认有效至 {preview.expires_at}。提交回执未知时仅恢复同一原请求。</p>
        <div className="flex flex-wrap gap-3"><Button disabled={!canConfirm} onClick={() => {
          if (!canConfirm || !preview || !local.pending) return;
          void perform({ stage: "execute", command: preview.command }, live.current.basis);
        }}><CheckCircle/>一次确认保存本次候选</Button><Button variant="outline" disabled={busy} onClick={cancel}>返回核对</Button></div>
      </div>}
    </dialog>
  </div>;
}
