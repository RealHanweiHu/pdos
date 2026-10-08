"use client";

import { useId } from "react";
import type { EventTime } from "./contracts";

export type EventTimeDraft = { occurredAt: string; timezone: string; originalId: string; sourceRevision: string; locator: string };
export function blankEventTime(): EventTimeDraft { return { occurredAt: "", timezone: "", originalId: "", sourceRevision: "", locator: "" }; }
export function eventTimeFromDraft(value: EventTimeDraft): EventTime { return { occurredAt: value.occurredAt, originalTimezone: value.timezone, source: { originalId: value.originalId, revision: Number(value.sourceRevision), kind: "original", locator: value.locator } }; }

export function EventTimeFields({ title, value, onChange }: { title: string; value: EventTimeDraft; onChange: (value: EventTimeDraft) => void }) {
  const prefix = useId();
  const fields: Record<keyof EventTimeDraft, string> = { occurredAt: "真实发生时间（含 UTC 或偏移）", timezone: "原始 IANA 时区", originalId: "记录原件 ID", sourceRevision: "原件版本", locator: "精确来源位置" };
  return <fieldset className="grid min-w-0 gap-3 border-t border-border pt-3 sm:grid-cols-2"><legend className="mb-2 text-sm font-medium">{title}</legend>{Object.entries(fields).map(([field, label]) => <label key={field} className="space-y-1 text-sm" htmlFor={`${prefix}-${field}`}><span>{label}</span><input id={`${prefix}-${field}`} className="w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring" required maxLength={2000} value={value[field as keyof EventTimeDraft]} placeholder={field === "occurredAt" ? "2026-10-02T09:00:00+08:00" : field === "timezone" ? "Asia/Shanghai" : undefined} onChange={event => onChange({ ...value, [field]: event.target.value })}/></label>)}</fieldset>;
}
