"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

import type { DevelopmentCase } from "./case-types";

export type CaseFormValues = {
  code: string;
  title: string;
  summary: string | null;
  business_case: Record<string, unknown>;
};

export type CaseSubmissionResult = { ok: true } | { ok: false; message: string };

const controlClass =
  "mt-1 min-h-11 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 disabled:cursor-not-allowed disabled:opacity-60";

export function CaseForm({
  busy,
  developmentCase,
  onCancel,
  onSubmit,
}: {
  busy: boolean;
  developmentCase: DevelopmentCase;
  onCancel: () => void;
  onSubmit: (values: CaseFormValues) => Promise<CaseSubmissionResult>;
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
    });
    if (!result.ok) setError(result.message);
  }

  return (
    <form aria-labelledby="case-form-title" className="space-y-4" onSubmit={submit}>
      <div>
        <h2 className="font-semibold" id="case-form-title">
          编辑开发案例
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">内容编辑与状态迁移分别留痕。</p>
      </div>
      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
          {error}
        </div>
      ) : null}
      <label className="block text-xs font-medium" htmlFor="case-code">
        案例编号
        <input
          className={controlClass}
          defaultValue={developmentCase.code}
          disabled={busy}
          id="case-code"
          maxLength={64}
          name="code"
          ref={codeRef}
          required
        />
      </label>
      <label className="block text-xs font-medium" htmlFor="case-title">
        标题
        <input
          className={controlClass}
          defaultValue={developmentCase.title}
          disabled={busy}
          id="case-title"
          maxLength={512}
          name="title"
          required
        />
      </label>
      <label className="block text-xs font-medium" htmlFor="case-summary">
        摘要
        <textarea
          className={`${controlClass} min-h-24 resize-y`}
          defaultValue={developmentCase.summary ?? ""}
          disabled={busy}
          id="case-summary"
          maxLength={20_000}
          name="summary"
        />
      </label>
      <label className="block text-xs font-medium" htmlFor="case-business">
        商业论证（JSON）
        <textarea
          className={`${controlClass} min-h-32 resize-y font-mono text-xs`}
          defaultValue={JSON.stringify(developmentCase.business_case, null, 2)}
          disabled={busy}
          id="case-business"
          name="business_case"
          spellCheck={false}
        />
      </label>
      <div className="flex justify-end gap-2 border-t pt-4">
        <Button className="h-11 sm:h-8" disabled={busy} onClick={onCancel} type="button" variant="outline">
          取消
        </Button>
        <Button className="h-11 sm:h-8" disabled={busy} type="submit">
          {busy ? "正在保存…" : "保存更改"}
        </Button>
      </div>
    </form>
  );
}
