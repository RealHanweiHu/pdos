"use client";

import { useId, useState, type FormEvent } from "react";
import { MagnifyingGlass } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { Callbacks, Context } from "./contracts";

const input = "w-full rounded-lg border bg-background px-3 py-2 text-sm";
export function ResearchStart({ context, callbacks }: { context: Context; callbacks: Callbacks }) {
  const id = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const available = context.readiness.start && !!callbacks.onStart && !!context.scopeLabel;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!available || busy) return;
    const form = new FormData(event.currentTarget);
    setBusy(true); setError(null);
    try {
      await callbacks.onStart!({ title: String(form.get("title")), mode: form.get("mode") === "oem" ? "oem" : "research",
        questions: String(form.get("questions")).split("\n").filter(value => value.trim()),
        use_cases: String(form.get("use_cases")).split("\n").filter(value => value.trim()) });
    } catch (cause) { setError(cause instanceof Error ? cause.message : "研究保存失败，请重试当前输入。"); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded-lg border p-4" aria-labelledby={`${id}-heading`}>
    <h2 id={`${id}-heading`} className="flex items-center gap-2 font-semibold"><MagnifyingGlass />研究与客户输入</h2>
    <p className="text-sm text-muted-foreground">范围：{context.scopeLabel ?? "尚未绑定研究范围"} · {context.actorLabel}</p>
    <p className="text-sm">研究期间无需项目。OEM 直接核对客户设计包并形成内部定义候选。</p>
    {!available && <p role="status" className="text-sm text-muted-foreground">{context.unavailableReason ?? "待主线接入研究保存与服务器范围绑定"}</p>}
    <form onSubmit={submit} className="space-y-3">
      <label className="block text-sm" htmlFor={`${id}-mode`}>输入路径</label>
      <select id={`${id}-mode`} name="mode" className={input}><option value="research">无项目研究</option><option value="oem">OEM 客户设计包</option></select>
      <label className="block text-sm" htmlFor={`${id}-title`}>研究标题</label>
      <input id={`${id}-title`} name="title" required minLength={2} maxLength={200} className={input} />
      <label className="block text-sm" htmlFor={`${id}-questions`}>本轮核对问题，每行一项</label>
      <textarea id={`${id}-questions`} name="questions" required maxLength={60000} className={input} />
      <label className="block text-sm" htmlFor={`${id}-use`}>使用场景，每行一项</label>
      <textarea id={`${id}-use`} name="use_cases" required maxLength={100000} className={input} />
      <Button type="submit" disabled={!available || busy} className="min-h-11">{busy ? "保存中…" : "保存研究范围"}</Button>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </form>
  </section>;
}
