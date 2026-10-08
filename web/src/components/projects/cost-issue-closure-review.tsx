"use client";

import { isRecord } from "@/components/workspace-api";
import type { CostClosureReference } from "./project-work-item-types";

type Item = { case_id: string; title: string; closure: { ready: boolean; reasons: string[]; reference: CostClosureReference | null; comparison?: Record<string, unknown>; currency?: string } };
export type CostClosureContext = { required: boolean; ready: boolean; items: Item[]; access_denied?: boolean; reason?: string };

function reference(value: unknown): value is CostClosureReference {
  return isRecord(value) && ["case_id", "observation_id", "source_digest"].every(key => typeof value[key] === "string" && !!value[key]);
}

export function costClosureContext(value: unknown): CostClosureContext | null {
  if (!isRecord(value) || typeof value.required !== "boolean" || typeof value.ready !== "boolean" || !Array.isArray(value.items)) return null;
  const items: Item[] = [];
  for (const item of value.items) {
    if (!isRecord(item) || typeof item.case_id !== "string" || typeof item.title !== "string" || !isRecord(item.closure)) return null;
    const closure = item.closure;
    if (typeof closure.ready !== "boolean" || !Array.isArray(closure.reasons) || !closure.reasons.every(v => typeof v === "string")) return null;
    if (closure.reference !== null && (!reference(closure.reference) || closure.reference.case_id !== item.case_id)) return null;
    if (closure.ready && !reference(closure.reference)) return null;
    items.push({ case_id: item.case_id, title: item.title, closure: { ...closure, ready: closure.ready, reasons: closure.reasons, reference: closure.reference as CostClosureReference | null } });
  }
  if (value.access_denied === true && value.required && !value.ready && !items.length) return { required: true, ready: false, items, access_denied: true, reason: typeof value.reason === "string" ? value.reason : "当前无权查看成本恢复依据" };
  if (new Set(items.map(v => v.case_id)).size !== items.length || value.required !== (items.length > 0)) return null;
  return { required: value.required, ready: value.ready, items };
}

export function costSelectionReady(context: CostClosureContext | null, selected: CostClosureReference[] | null) {
  if (!context) return false;
  if (!context.required) return true;
  return context.ready && selected?.length === context.items.length && context.items.every(item => item.closure.ready && item.closure.reference && selected.some(value => value.case_id === item.case_id && value.observation_id === item.closure.reference!.observation_id && value.source_digest === item.closure.reference!.source_digest));
}

export function CostIssueClosureReview({ context, selected, onSelect, disabled }: { context: CostClosureContext | null; selected: CostClosureReference[] | null; onSelect: (value: CostClosureReference[] | null) => void; disabled: boolean }) {
  if (!context) return <p className="text-sm text-destructive">尚未取得当前成本关闭依据，请刷新后核对。</p>;
  if (!context.required) return null;
  const ready = context.ready && context.items.length > 0 && context.items.every(v => v.closure.ready && v.closure.reference);
  return <section className="space-y-2 rounded-md border p-3" aria-label="成本恢复关闭依据">
    <p className="text-sm font-medium">核对原成本差异的当前恢复</p>
    {context.reason && <p className="text-sm text-destructive">{context.reason}</p>}
    {context.items.map(item => <div key={item.case_id} className="space-y-1 text-xs"><p className="font-medium">{item.title} · {item.closure.ready ? "当前同口径成本已回到目标内" : "尚不满足关闭条件"}</p>{item.closure.comparison && <p>目标 {String(isRecord(item.closure.comparison.target) ? item.closure.comparison.target.value : "未知")} · 成本 {String(item.closure.comparison.total ?? "未知")} · 差额 {String(item.closure.comparison.gap ?? "未知")} {item.closure.currency}</p>}{item.closure.reasons.map(reason => <p key={reason} className="text-destructive">{reason}</p>)}</div>)}
    <p className="text-xs text-muted-foreground">引用最新观察及原件版本；成本恢复不代替工程变更批准与实际验证。</p>
    <label className="flex min-h-11 items-start gap-2 text-sm"><input className="mt-1" type="checkbox" checked={costSelectionReady(context, selected)} disabled={disabled || !ready} onChange={event => onSelect(event.target.checked ? context.items.map(v => ({ ...v.closure.reference! })) : null)}/><span>我已核对全部成本来源，引用本次恢复记录</span></label>
  </section>;
}
