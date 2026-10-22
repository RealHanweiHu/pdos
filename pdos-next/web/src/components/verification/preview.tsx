"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { previewProblem, sourceText, type ConfirmationReceipt, type PreparedVerificationAction, type VerificationCallbacks, type VerificationIntent } from "./contracts";

export function useVerificationAction(contextKey: string, ready: boolean, callbacks: VerificationCallbacks) {
  const [preview, setPreview] = useState<PreparedVerificationAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [unknown, setUnknown] = useState(false);
  const [now, setNow] = useState(0);
  const lock = useRef(false);
  const attempted = useRef(new Set<string>());
  const alive = useRef(true);
  const current = useRef({ contextKey, ready });
  useEffect(() => { current.current = { contextKey, ready }; }, [contextKey, ready]);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  useEffect(() => {
    if (!preview) return;
    const timer = setTimeout(() => setNow(Date.now()), Math.max(1, Math.min(2_147_483_647, Date.parse(preview.expiresAt) - Date.now() + 1)));
    return () => clearTimeout(timer);
  }, [preview]);
  const problem = preview ? previewProblem(preview, preview.intent, contextKey, now || Date.parse(preview.expiresAt) - 1) : null;

  async function prepare(intent: VerificationIntent) {
    if (lock.current || unknown || !ready) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    const snapshotKey = contextKey;
    try {
      const value = await callbacks.onPreview(intent, snapshotKey);
      if (!alive.current) return;
      if (snapshotKey !== current.current.contextKey || !current.current.ready) throw new Error("准备期间范围或接口已变化，请重新核对。");
      // Blocked previews remain visible with their concrete missing items.
      const malformed = previewProblem({ ...value, allowed: true, missing: value.missing.filter(item => !item.blocking) }, intent, snapshotKey, Date.now());
      if (malformed) throw new Error(malformed);
      setNow(Date.now()); setPreview(value);
    } catch (failure) { if (alive.current) setError(failure instanceof Error ? failure.message : "核对失败，输入已保留。"); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }

  async function receipt(value: ConfirmationReceipt) {
    if (value.outcome === "unknown") { setUnknown(true); setError(value.message || "保存结果未知，请先核对原动作回执。"); return; }
    if (value.outcome === "rejected") { setUnknown(false); setPreview(null); setError(value.message || "服务器拒绝办理，请重新核对。"); return; }
    if (!value.receiptId || !value.message) { setUnknown(true); setError("服务器尚未返回完整回执，请核对原动作。"); return; }
    setUnknown(false); setPreview(null); setNotice(`${value.message} 回执：${value.receiptId}`);
    try { await callbacks.onCommitted?.(value); }
    catch { if (alive.current) setError("办理已确认；最新资料读取失败，请刷新主线入口。"); }
  }

  async function confirm() {
    if (!preview || lock.current || unknown || !ready || attempted.current.has(preview.token)) return;
    const invalid = previewProblem(preview, preview.intent, contextKey, Date.now());
    if (invalid) { setError(invalid); return; }
    attempted.current.add(preview.token);
    lock.current = true; setBusy(true); setError("");
    try { const value = await callbacks.onConfirm(preview); if (alive.current) await receipt(value); }
    catch (failure) { if (alive.current) { setUnknown(true); setError(`保存结果未知，请核对原动作回执。${failure instanceof Error ? failure.message : ""}`); } }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }

  async function resolve() {
    if (!preview || !callbacks.onResolve || lock.current || !unknown) return;
    lock.current = true; setBusy(true); setError("");
    try { const value = await callbacks.onResolve(preview); if (alive.current) await receipt(value); }
    catch (failure) { if (alive.current) setError(failure instanceof Error ? failure.message : "回执仍未确认。"); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }

  function cancel() { if (!busy && !unknown) { setPreview(null); setError(""); } }
  return { preview, busy, error, notice, unknown, problem, prepare, confirm, resolve, cancel, setError, locked: busy || !!preview || unknown, canResolve: !!callbacks.onResolve };
}

export type VerificationAction = ReturnType<typeof useVerificationAction>;

export function VerificationActionReview({ action, ready }: { action: VerificationAction; ready: boolean }) {
  const { preview } = action;
  return <div className="space-y-3">
    {action.error && <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">{action.error}</p>}
    {action.notice && <p role="status" className="rounded-lg border border-border p-3 text-sm">{action.notice}</p>}
    {preview && <section className="min-w-0 rounded-lg border border-primary p-4 text-sm" aria-label="服务器实质预览" aria-busy={action.busy}>
      <h3 className="flex items-center gap-2 font-semibold"><CheckCircle aria-hidden/>确认本次明确范围</h3>
      <p className="mt-2 whitespace-pre-wrap break-words">{preview.summary}</p>
      <dl className="mt-3 grid gap-x-3 gap-y-2 sm:grid-cols-[auto_minmax(0,1fr)]"><dt className="opacity-70">请求版本</dt><dd className="break-words">{preview.scope.request.id} · v{preview.scope.request.revision}</dd><dt className="opacity-70">测试项范围</dt><dd className="break-words">{preview.scope.coverage.testItemIds.join("、") || "无"}</dd><dt className="opacity-70">逐件对应覆盖</dt><dd className="break-words">{preview.scope.coverage.pairs.map(pair => `${pair.sampleId} / ${pair.testItemId}`).join("；") || "无"}</dd><dt className="opacity-70">到期时点</dt><dd className="break-words">{preview.expiresAt}</dd><dt className="opacity-70">预览摘要</dt><dd className="break-all font-mono text-xs">{preview.digest}</dd></dl>
      <ul className="mt-3 space-y-2">{preview.scope.samples.map(sample => <li key={sample.id} className="border-t border-border pt-2"><span className="font-medium">{sample.label}</span><span className="block break-words opacity-70">实际配置 {sample.actualConfiguration.id} · v{sample.actualConfiguration.revision}；模穴 {sample.cavity ?? "未记录"}；{sourceText(sample.source)}</span></li>)}</ul>
      {preview.missing.length > 0 && <ul className="mt-3 space-y-2">{preview.missing.map((item, index) => <li key={`${item.kind}:${index}`} className="flex gap-2"><WarningCircle className="mt-0.5 shrink-0" aria-hidden/><span>{item.blocking ? "阻塞：" : "范围外缺项："}{item.description}</span></li>)}</ul>}
      {action.problem && <p role="status" className="mt-3 text-destructive">{action.problem}</p>}
      {action.unknown && <p className="mt-3">原动作结果未确认，须读取回执后才能继续办理。</p>}
      <div className="mt-4 flex flex-wrap gap-2"><Button type="button" disabled={!ready || action.busy || action.unknown || !!action.problem} onClick={() => void action.confirm()}>一次确认此范围</Button><Button type="button" variant="outline" disabled={action.busy || action.unknown} onClick={action.cancel}>取消预览并修改</Button>{action.unknown && <Button type="button" variant="outline" disabled={action.busy || !action.canResolve} onClick={() => void action.resolve()}>核对原动作回执</Button>}</div>
    </section>}
  </div>;
}
