"use client";
import { WarningCircle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { previewProblem, unresolvedAction, type Callbacks, type Context, type ControlledAction, type QualityIntent } from "./contracts";

export function QualityActionReview({ action, context, intent, callbacks }: { action: ControlledAction; context: Context; intent: QualityIntent | null; callbacks: Callbacks }) {
  const preview = action.preview;
  const problem = preview ? previewProblem(preview, intent, context, action.nowMs) : null;
  const unknown = unresolvedAction(action);
  return <section className="min-w-0 space-y-3" aria-label="办理核对与回执" aria-busy={action.busy}>
    {action.error && <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">{action.error}</p>}
    {action.receipt && <p role={!unknown && (action.receipt.outcome === "committed" || action.receipt.outcome === "replayed") ? "status" : "alert"} className="break-words rounded-lg border border-border p-3 text-sm">{action.receipt.message}{action.receipt.receiptId ? ` 回执：${action.receipt.receiptId}` : " · 回执尚未确认"}</p>}
    {preview && <div className="rounded-lg border border-primary p-4 text-sm">
      <h3 className="font-medium">本次实质范围与差异 · {preview.tier}</h3><p className="mt-2 whitespace-pre-wrap break-words">{preview.summary}</p>
      <ul className="mt-3 list-inside list-disc space-y-2">{preview.differences.map((difference, index) => <li key={index} className="break-words">{difference}</li>)}</ul>
      <p className="mt-3 break-words">保留独立失败：{preview.preservedFailureKeys.join("、") || "服务器尚未提供"}</p><p className="mt-1 break-words opacity-70">到期 {preview.expiresAt} · 摘要 {preview.digest}</p>
      {preview.missing.map((item, index) => <p key={index} className="mt-2 flex items-start gap-2"><WarningCircle aria-hidden className="shrink-0" /><span>{item.blocking ? "阻塞：" : "提示："}{item.description}</span></p>)}
      {problem && <p role="status" className="mt-3 text-destructive">{problem}</p>}
      {unknown && <p role="alert" className="mt-3">原动作结果未知，先核对原回执；不得重提新动作。</p>}
      <div className="mt-4 flex flex-wrap gap-2"><Button type="button" disabled={action.busy || unknown || !!problem || !callbacks.onConfirm} onClick={() => { if (!action.busy && !unknown && callbacks.onConfirm && !previewProblem(preview, intent, context, Math.max(action.nowMs, Date.now()))) void callbacks.onConfirm(preview); }}>{preview.tier === "T2" ? "具名提交此决定" : preview.tier === "T1" ? "一次确认此范围" : "按当前授权办理"}</Button>{unknown && <Button type="button" variant="outline" disabled={action.busy || !callbacks.onResolve} onClick={() => { if (!action.busy && callbacks.onResolve) void callbacks.onResolve(preview); }}>核对原动作回执</Button>}</div>
    </div>}
    {unknown && !preview && <p role="alert" className="text-sm text-destructive">原动作结果未知；须恢复原预览与回执查询入口，当前禁止再次准备。</p>}
  </section>;
}
