"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

import type { Requirement } from "./requirement-types";

export type RequirementConversionValues = {
  code: string;
  title: string;
  summary: string | null;
  business_case: Record<string, unknown>;
  rationale: string;
};

export type RequirementConversionResult =
  | { ok: true }
  | { ok: false; message: string };

const controlClass =
  "mt-1 min-h-11 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 disabled:cursor-not-allowed disabled:opacity-60";

export function RequirementConversionForm({
  busy,
  onCancel,
  onSubmit,
  requirement,
}: {
  busy: boolean;
  onCancel: () => void;
  onSubmit: (values: RequirementConversionValues) => Promise<RequirementConversionResult>;
  requirement: Requirement;
}) {
  const codeRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    codeRef.current?.focus();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const data = new FormData(event.currentTarget);
    let businessCase: unknown;
    try {
      businessCase = JSON.parse(String(data.get("business_case") ?? "{}"));
    } catch {
      setError("商业论证必须是有效 JSON 对象。");
      return;
    }
    if (businessCase === null || typeof businessCase !== "object" || Array.isArray(businessCase)) {
      setError("商业论证必须是 JSON 对象。");
      return;
    }
    const summary = String(data.get("summary") ?? "").trim();
    const result = await onSubmit({
      code: String(data.get("code") ?? "").trim(),
      title: String(data.get("title") ?? "").trim(),
      summary: summary || null,
      business_case: businessCase as Record<string, unknown>,
      rationale: String(data.get("rationale") ?? "").trim(),
    });
    if (!result.ok) setError(result.message);
  }

  return (
    <form aria-labelledby="conversion-form-title" className="space-y-4" onSubmit={submit}>
      <div>
        <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">Formal action</p>
        <h2 className="mt-1 font-semibold" id="conversion-form-title">转为开发案例</h2>
        <p className="mt-1 text-xs text-muted-foreground">该动作会创建 Case 与 Decision，并锁定来源需求。</p>
      </div>
      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
          {error}
        </div>
      ) : null}
      <label className="block text-xs font-medium" htmlFor="conversion-code">
        案例编号
        <input className={controlClass} disabled={busy} id="conversion-code" maxLength={64} name="code" ref={codeRef} required />
      </label>
      <label className="block text-xs font-medium" htmlFor="conversion-title">
        案例标题
        <input className={controlClass} defaultValue={requirement.title} disabled={busy} id="conversion-title" maxLength={512} name="title" required />
      </label>
      <label className="block text-xs font-medium" htmlFor="conversion-summary">
        摘要
        <textarea className={`${controlClass} min-h-20 resize-y`} defaultValue={requirement.description ?? ""} disabled={busy} id="conversion-summary" maxLength={20_000} name="summary" />
      </label>
      <label className="block text-xs font-medium" htmlFor="conversion-rationale">
        转化理由
        <textarea className={`${controlClass} min-h-20 resize-y`} disabled={busy} id="conversion-rationale" maxLength={20_000} name="rationale" required />
      </label>
      <label className="block text-xs font-medium" htmlFor="conversion-business">
        商业论证（JSON）
        <textarea className={`${controlClass} min-h-24 resize-y font-mono text-xs`} defaultValue="{}" disabled={busy} id="conversion-business" name="business_case" spellCheck={false} />
      </label>
      <div className="flex justify-end gap-2 border-t pt-4">
        <Button className="h-11 sm:h-8" disabled={busy} onClick={onCancel} type="button" variant="outline">取消</Button>
        <Button className="h-11 sm:h-8" disabled={busy} type="submit">{busy ? "正在转化…" : "确认转化"}</Button>
      </div>
    </form>
  );
}
