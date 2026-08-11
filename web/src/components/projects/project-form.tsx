"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

import type { Project } from "./project-types";

export type ProjectFormValues = {
  code: string;
  name: string;
  description: string | null;
  start_date: string | null;
  target_date: string | null;
};

export type ProjectSubmissionResult = { ok: true } | { ok: false; message: string };

const controlClass =
  "mt-1 min-h-11 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 disabled:opacity-60";

export function ProjectForm({
  busy,
  onCancel,
  onSubmit,
  project,
}: {
  busy: boolean;
  onCancel: () => void;
  onSubmit: (values: ProjectFormValues) => Promise<ProjectSubmissionResult>;
  project: Project;
}) {
  const codeRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => codeRef.current?.focus(), []);

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
    });
    if (!result.ok) setError(result.message);
  }

  return (
    <form aria-labelledby="project-form-title" className="space-y-4" onSubmit={submit}>
      <div>
        <h2 className="font-semibold" id="project-form-title">编辑项目</h2>
        <p className="mt-1 text-xs text-muted-foreground">内容、状态与阶段分别留下事件和审计。</p>
      </div>
      {error ? <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</p> : null}
      <label className="block text-xs font-medium" htmlFor="project-code">
        项目编号
        <input className={controlClass} defaultValue={project.code} disabled={busy} id="project-code" maxLength={64} name="code" ref={codeRef} required />
      </label>
      <label className="block text-xs font-medium" htmlFor="project-name">
        项目名称
        <input className={controlClass} defaultValue={project.name} disabled={busy} id="project-name" maxLength={256} name="name" required />
      </label>
      <label className="block text-xs font-medium" htmlFor="project-description">
        描述
        <textarea className={`${controlClass} min-h-24 resize-y`} defaultValue={project.description ?? ""} disabled={busy} id="project-description" maxLength={20_000} name="description" />
      </label>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-xs font-medium" htmlFor="project-start-date">
          开始日期
          <input className={controlClass} defaultValue={project.start_date ?? ""} disabled={busy} id="project-start-date" name="start_date" type="date" />
        </label>
        <label className="text-xs font-medium" htmlFor="project-target-date">
          目标日期
          <input className={controlClass} defaultValue={project.target_date ?? ""} disabled={busy} id="project-target-date" name="target_date" type="date" />
        </label>
      </div>
      <div className="flex justify-end gap-2 border-t pt-4">
        <Button className="h-11 sm:h-8" disabled={busy} onClick={onCancel} type="button" variant="outline">取消</Button>
        <Button className="h-11 sm:h-8" disabled={busy} type="submit">{busy ? "正在保存…" : "保存更改"}</Button>
      </div>
    </form>
  );
}
