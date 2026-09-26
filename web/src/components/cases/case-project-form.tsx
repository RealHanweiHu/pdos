"use client";

import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";

import { CaseProjectTemplatePicker, type CreationTemplate } from "./case-project-template-picker";

import type { DevelopmentCase } from "./case-types";

export type CaseProjectValues = {
  code: string;
  name: string;
  description: string | null;
  start_date: string | null;
  target_date: string | null;
  product_template?: CreationTemplate;
};

export type CaseProjectResult = { ok: true } | { ok: false; message: string };

const controlClass =
  "mt-1 min-h-11 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 disabled:opacity-60";

export function CaseProjectForm({
  busy,
  developmentCase,
  onSubmit,
}: {
  busy: boolean;
  developmentCase: DevelopmentCase;
  onSubmit: (values: CaseProjectValues) => Promise<CaseProjectResult>;
}) {
  const [productTemplate, setProductTemplate] = useState<CreationTemplate | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const data = new FormData(event.currentTarget);
    const description = String(data.get("description") ?? "").trim();
    const startDate = String(data.get("start_date") ?? "");
    const targetDate = String(data.get("target_date") ?? "");
    const result = await onSubmit({
      code: String(data.get("code") ?? "").trim(),
      name: String(data.get("name") ?? "").trim(),
      description: description || null,
      start_date: startDate || null,
      target_date: targetDate || null,
      ...(productTemplate ? { product_template: productTemplate } : {}),
    });
    if (!result.ok) setError(result.message);
  }
  return (
    <form className="mt-4 space-y-3 border-t pt-4" onSubmit={submit}>
      <div>
        <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-primary">Project action</p>
        <h3 className="mt-1 text-sm font-semibold">从已批准 Case 创建项目</h3>
        <p className="mt-1 text-xs text-muted-foreground">创建项目、专属阶段及审批入口，并保存所选产品流程版本。</p>
      </div>
      {error ? <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</p> : null}
      <label className="block text-xs font-medium" htmlFor="case-project-code">项目编号<input className={controlClass} disabled={busy} id="case-project-code" maxLength={64} name="code" required /></label>
      <label className="block text-xs font-medium" htmlFor="case-project-name">项目名称<input className={controlClass} defaultValue={developmentCase.title} disabled={busy} id="case-project-name" maxLength={256} name="name" required /></label>
      <label className="block text-xs font-medium" htmlFor="case-project-description">描述<textarea className={`${controlClass} min-h-20 resize-y`} defaultValue={developmentCase.summary ?? ""} disabled={busy} id="case-project-description" maxLength={20_000} name="description" /></label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-xs font-medium" htmlFor="case-project-start">开始日期<input className={controlClass} disabled={busy} id="case-project-start" name="start_date" type="date" /></label>
        <label className="text-xs font-medium" htmlFor="case-project-target">目标日期<input className={controlClass} disabled={busy} id="case-project-target" name="target_date" type="date" /></label>
      </div>
      <CaseProjectTemplatePicker busy={busy} value={productTemplate} onChange={setProductTemplate} />
      <Button className="h-11 w-full sm:h-8" disabled={busy} type="submit">{busy ? "正在创建…" : "创建项目"}</Button>
    </form>
  );
}
