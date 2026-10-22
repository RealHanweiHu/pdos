"use client";

import { useId, useState, type FormEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { grouped, rawSpec, selectionRequest, type Callbacks, type Context, type Research } from "./contracts";

export function DefinitionSelection({ research, context, callbacks, parent, confirmationSlot }: {
  research: Research; context: Context; callbacks: Callbacks;
  parent?: { id: string; revision: number };
  /** Place the existing common preview/confirmation component here. */
  confirmationSlot?: ReactNode;
}) {
  const id = useId();
  const groups = grouped(research);
  const [choices, setChoices] = useState<Record<string, { included: boolean; observationId: string | null; reason: string }>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const available = context.readiness.preview && !!callbacks.onPreview && !!context.productLabel;
  const input = "w-full rounded-lg border bg-background px-3 py-2 text-sm";
  function choose(key: string, changes: Partial<{ included: boolean; observationId: string | null; reason: string }>) {
    setChoices(current => ({ ...current, [key]: { included: false, observationId: null, reason: "", ...Object.getOwnPropertyDescriptor(current, key)?.value, ...changes } }));
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!available || busy) return;
    const form = new FormData(event.currentTarget);
    setError(null);
    try {
      // Limit to currently present groups after parent refresh; host still rechecks every version.
      const presentChoices = Object.fromEntries(groups.map(([key]) => [key, Object.getOwnPropertyDescriptor(choices, key)?.value ?? { included: false, observationId: null, reason: "" }]));
      const request = selectionRequest(String(form.get("title")), String(form.get("reason")), String(form.get("partial")), presentChoices);
      if (parent) { request.parent_definition_id = parent.id; request.expected_parent_revision = parent.revision; }
      setBusy(true);
      await callbacks.onPreview!(research.id, research.revision, request);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "候选核对失败，输入已保留。"); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded-lg border p-4" aria-labelledby={`${id}-heading`}>
    <h2 id={`${id}-heading`} className="font-semibold">选择内部定义候选</h2>
    <p className="text-sm text-muted-foreground">办理人：{context.actorLabel} · 型号：{context.productLabel ?? "尚未绑定"} · 用途：{context.purpose ?? "待服务器绑定"}</p>
    <p className="text-sm">每组明确选择或保留冲突。核对后由统一预览入口办理一次确认；此次提交是一个整体定义候选。</p>
    {!available && <p role="status">{context.unavailableReason ?? "定义预览待主线接入，或真实型号尚未绑定"}</p>}
    <form className="space-y-4" onSubmit={submit}>
      <label className="block text-sm" htmlFor={`${id}-title`}>定义标题</label><input id={`${id}-title`} name="title" required minLength={2} maxLength={200} className={input} />
      {groups.map(([key, entries], index) => {
        const choice = Object.getOwnPropertyDescriptor(choices, key)?.value as { included: boolean; observationId: string | null; reason: string } | undefined;
        return <fieldset key={key} className="space-y-2 rounded-lg border p-3">
          <legend className="px-1 text-sm font-medium">{key} · {entries.length} 条并列证据</legend>
          <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" checked={choice?.included ?? false} onChange={event => choose(key, { included: event.target.checked })} />本轮导入此组</label>
          <label className="flex min-h-11 items-center gap-2 text-sm"><input type="radio" name={`${id}-selection-${index}`} checked={!choice?.observationId} onChange={() => choose(key, { observationId: null })} />保留未裁决 / 未知</label>
          {entries.map(entry => <label key={entry.observation.id} className="flex min-h-11 items-start gap-2 rounded-lg bg-muted/40 p-3 text-sm">
            <input className="mt-1" type="radio" name={`${id}-selection-${index}`} checked={choice?.observationId === entry.observation.id} onChange={() => choose(key, { observationId: entry.observation.id })} />
            <span className="min-w-0 break-words">{entry.observation.statement}<span className="block font-mono">{entry.observation.spec ? rawSpec(entry.observation.spec) : entry.observation.kind}</span>
              <span className="block text-muted-foreground">{entry.verification.status === "verified" ? "原字段已核对，仍为候选" : "原值待核对，选择后保留人工候选"}</span>
              <span className="block">条件：{entry.observation.spec?.test_conditions.join("；") || "未知"} · 适用：{entry.observation.spec?.applicability ?? "未知"}</span></span>
          </label>)}
          <label htmlFor={`${id}-choice-${index}`} className="block text-sm">具名选择或保留冲突的原因</label>
          <textarea id={`${id}-choice-${index}`} value={choice?.reason ?? ""} required={choice?.included ?? false} minLength={3} maxLength={2000} className={input} onChange={event => choose(key, { reason: event.target.value })} />
        </fieldset>;
      })}
      <label htmlFor={`${id}-partial`} className="block text-sm">部分导入范围与缺项处理（有缺项或未选组时必填）</label><textarea id={`${id}-partial`} name="partial" maxLength={2000} className={input} />
      <label htmlFor={`${id}-reason`} className="block text-sm">本次定义变更原因</label><textarea id={`${id}-reason`} name="reason" required minLength={3} maxLength={2000} className={input} />
      <Button type="submit" className="min-h-11" disabled={!available || !groups.length || busy}>{busy ? "重核当前来源…" : "核对定义候选"}</Button>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </form>
    {confirmationSlot}
  </section>;
}
