"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { FactWorkflow } from "./fact-workflow";
import { factReceipt, restoreFactLocal } from "./fact-workflow-state";
import { factCandidateSelectionMatches, factIdentity, factPendingCandidate, readFactBusinessReview, validFactHost, type FactHost } from "./fact-workflow-contract";
import type { MaterialRef } from "./ui-contract";
import type { CandidatePanelProps } from "./candidate-panel";

function clearFactStorage(productId: string, principalId: string, issueId: string): boolean {
  let saved = false;
  try {
    const remove: string[] = [], prefix = "pdos-next:capa-facts:";
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key?.startsWith(prefix)) continue;
      try {
        const identity = key.slice(prefix.length), scope: unknown = JSON.parse(identity);
        if (!Array.isArray(scope) || scope.length !== 6 || scope[1] !== productId || scope[3] !== principalId || scope[4] !== issueId) continue;
        remove.push(key);
        try { saved ||= restoreFactLocal(JSON.parse(localStorage.getItem(key) ?? "null"), identity)?.outcome === "saved"; } catch {}
      } catch {}
    }
    for (const key of remove) localStorage.removeItem(key);
  } catch { /* Never create a private fallback for denied access. */ }
  return saved;
}

export function FactPanel(props: CandidatePanelProps) {
  if (!props.issueId) return null;
  return <ScopedFactPanel key={JSON.stringify([props.product.id, props.principalId, props.issueId])} {...props} issueId={props.issueId}/>;
}

function ScopedFactPanel({ product, principalId, issueId, api, onSaved, onPendingChange, onAccessRejected, blocked = false }: CandidatePanelProps & { issueId: string }) {
  const [host, setHost] = useState<FactHost | null>(null);
  const [selected, setSelected] = useState<MaterialRef | null>(null);
  const [pendingLocked, setPendingLocked] = useState(false), [operationBusy, setOperationBusy] = useState(false);
  const [loading, setLoading] = useState(false), [readFailed, setReadFailed] = useState(true);
  const [rejected, setRejected] = useState(false), [savedHint, setSavedHint] = useState(false), [error, setError] = useState("");
  const sequence = useRef(0), alive = useRef(false), denied = useRef(false);
  const pending = useRef(false), operating = useRef(false);
  const selection = useRef<MaterialRef | null>(null);
  const pendingChanged = useCallback((locked: boolean) => {
    pending.current = locked; if (alive.current) setPendingLocked(locked); onPendingChange?.(locked);
  }, [onPendingChange]);
  const invalidateReads = useCallback(() => { sequence.current++; }, []);
  const clearPrivate = useCallback((knownSaved = false, late = false) => {
    if (late || !alive.current) { onAccessRejected?.(knownSaved, true); return; }
    denied.current = true;
    const saved = clearFactStorage(product.id, principalId, issueId) || knownSaved;
    selection.current = null; setHost(null); setSelected(null); setRejected(true); setReadFailed(true); setSavedHint(old => old || saved);
    pendingChanged(false);
    onAccessRejected?.(saved);
  }, [product.id, principalId, issueId, onAccessRejected, pendingChanged]);
  const read = useCallback(async () => {
    const ticket = ++sequence.current;
    setLoading(true); setReadFailed(true); setError("");
    try {
      let requested = selection.current;
      const fetchSelection = (choice: MaterialRef | null) => api<FactHost>(`v1/products/${product.id}/capa-facts?issue_id=${encodeURIComponent(issueId)}${choice ? `&candidate_id=${encodeURIComponent(choice.id)}` : ""}`);
      const assertSelection = (value: FactHost, choice: MaterialRef | null) => {
        if (!validFactHost(value) || !Array.isArray(value.candidate_options) || value.binding.scope.product_id !== product.id ||
            value.binding.caller_id !== principalId || value.binding.issue_id !== issueId)
          throw Object.assign(new Error("事实返回范围不能核对"), { status: 403 });
        if (!factCandidateSelectionMatches(value, product.id, principalId, issueId, choice))
          throw Object.assign(new Error("所选候选版本已变化，原请求仍保留"), { status: 409, code: "READ_CANDIDATE_MISMATCH" });
      };
      let value = await fetchSelection(requested);
      if (!alive.current || ticket !== sequence.current) throw Object.assign(new Error("旧读取已结束"), { code: "READ_SUPERSEDED" });
      assertSelection(value, requested);
      // Detect an exact restored pending operation before exposing selection controls.
      const identity = factIdentity(value)!;
      let original: ReturnType<typeof restoreFactLocal> = null;
      try { original = restoreFactLocal(JSON.parse(localStorage.getItem(`pdos-next:capa-facts:${identity}`) ?? "null"), identity); } catch {}
      pendingChanged(original?.pending != null || pending.current);
      const restored = original?.pending ? factPendingCandidate(value, original.pending.command) : null;
      if (requested === null && restored !== null) {
        // This is the old request's explicit choice, never a guessed current/latest candidate.
        requested = restored; selection.current = restored; setSelected(restored);
        value = await fetchSelection(restored);
        if (!alive.current || ticket !== sequence.current) throw Object.assign(new Error("旧读取已结束"), { code: "READ_SUPERSEDED" });
        assertSelection(value, restored);
        if (factIdentity(value) !== identity)
          throw Object.assign(new Error("原请求的候选范围不能核对"), { status: 403 });
      }
      denied.current = false; setRejected(false); setHost(value); setReadFailed(false);
    } catch (failure) {
      if (alive.current && ticket === sequence.current) {
        const status = failure && typeof failure === "object" && "status" in failure ? failure.status : undefined;
        if (status === 401 || status === 403) clearPrivate();
        setError(status === 401 || status === 403 ? "当前访问范围已失效，私有资料停止展示与办理。" : "当前事实尚未读回，请重试读取；原保存请求仍保留。");
      }
      throw failure;
    } finally { if (alive.current && ticket === sequence.current) setLoading(false); }
  }, [api, product.id, principalId, issueId, clearPrivate, pendingChanged]);
  useEffect(() => { alive.current = true; if (!denied.current) void Promise.resolve().then(read).catch(() => {});
    return () => { alive.current = false; invalidateReads(); }; }, [read, invalidateReads]);
  const send = useCallback(async (path: string, command: unknown) => {
    sequence.current++; if (alive.current) setLoading(false);
    operating.current = true; if (alive.current) setOperationBusy(true);
    try {
      const result = await api<unknown>(path, command);
      if (denied.current && factReceipt(result)) { if (alive.current) setSavedHint(true); else onAccessRejected?.(true, true); }
      return result;
    } finally { operating.current = false; if (alive.current) setOperationBusy(false); }
  }, [api, onAccessRejected]);
  const afterSaved = useCallback(async () => {
    operating.current = true; if (alive.current) { setSavedHint(true); setOperationBusy(true); }
    try { await onSaved(); await read(); }
    finally { operating.current = false; if (alive.current) setOperationBusy(false); }
  }, [onSaved, read]);
  return <section className="space-y-4" aria-label="实际观察与独立复核" aria-busy={loading}>
    <div className="panel space-y-3"><div className="flex flex-wrap justify-between gap-3"><h3 className="font-semibold">实际观察与独立复核</h3>
      <Button variant="outline" disabled={loading || operationBusy} onClick={() => void read().catch(() => {})}>读取当前规则与事实</Button></div>
      <p className="text-sm">按当前固定规则保存自己的实际观察；独立复核由有权本人分别办理。保存记录不会自动证明有效或关闭问题。</p>
      {loading && <p role="status" className="subtle">正在读取当前规则、原记录及具名权限。</p>}
      {error && <p role="alert" className="text-sm">{error}</p>}
      {savedHint && (readFailed || rejected) && <p role="status" className="text-sm">原操作已取得保存结果；当前读取仍待完成，不能重复保存。</p>}
      {host && !rejected && <label className="block space-y-2 text-sm">本次独立复核的固定候选
        <select aria-label="选择固定复验候选" className="w-full min-w-0 rounded-lg border border-input bg-background p-2"
          value={selected?.id ?? ""} disabled={blocked || loading || readFailed || operationBusy || pendingLocked}
          onChange={event => {
            if (blocked || loading || readFailed || operating.current || pending.current) return;
            const choice = host.candidate_options?.find(c => c.ref.id === event.target.value);
            if (event.target.value && !choice) return;
            const next = choice ? { ...choice.ref } : null;
            invalidateReads(); selection.current = next; setReadFailed(true); setHost(null); setSelected(next);
            void read().catch(() => {});
          }}>
          <option value="">请明确选择候选，不默认采用历史记录</option>
          {host.candidate_options?.map(c => <option key={c.ref.id} value={c.ref.id}>{c.label} · 固定配对 {c.mapping_count} 项 · {c.visibility === "private" ? "私人范围" : "品类共享"}</option>)}
        </select>
        <span className="subtle">候选切换会废弃尚未发送的填写与预览。原请求未完成或回执未知时，只能恢复原请求。</span>
      </label>}
    </div>
    {host && <FactWorkflow host={host} inputs={command => send(`v1/products/${product.id}/capa-facts/inputs`, command)}
      preview={command => send("v1/commands/preview", command)} execute={command => send("v1/commands", command)}
      readHistory={async cursor => {
        const ticket = sequence.current;
        try {
          const value = await api<FactHost>(`v1/products/${product.id}/capa-facts?issue_id=${encodeURIComponent(issueId)}&history_cursor=${encodeURIComponent(cursor)}`);
          if (!alive.current || ticket !== sequence.current) throw new Error("历史读取已结束");
          if (!validFactHost(value) || value.binding.scope.product_id !== product.id || value.binding.caller_id !== principalId || value.binding.issue_id !== issueId)
            throw Object.assign(new Error("历史范围不能核对"), { status: 403 });
          return value;
        } catch (failure) {
          if (alive.current && ticket === sequence.current && failure && typeof failure === "object" && "status" in failure && [401, 403].includes(Number(failure.status))) clearPrivate();
          throw failure;
        }
      }}
      readReview={(review, command) => readFactBusinessReview(host, review, command)} onSaved={afterSaved} onRefresh={read}
      onPendingChange={pendingChanged} blocked={blocked || loading || readFailed}
      hostAccessRejected={rejected} onAccessRejected={clearPrivate}/>} 
  </section>;
}
