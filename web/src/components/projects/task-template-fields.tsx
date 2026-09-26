"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { requiredStages, type TaskField } from "@/components/organization/process-template-task-fields";

type Values = Record<string, string | number | boolean | null>;
type Form = { fields: TaskField[]; source: { template_id: string; template_version: number } | null; task: { status: string; updated_at: string; template_fields: Values } };
const control = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

export function TaskTemplateFields({ projectId, taskId, currentStatus, currentVersion, onChanged }:  { projectId: string; taskId: string; currentStatus?: string; currentVersion?: string; onChanged?: () => void }) {
  const [form, setForm] = useState<Form | null>(null), [values, setValues] = useState<Values>({});
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const inFlight = useRef(false);
  const path = `/api/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/template-fields`;
  async function request(save: boolean) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const typed = { ...values };
      if (save && form) for (const field of form.fields) {
        if (field.kind === "number" && typeof typed[field.key] === "string" && String(typed[field.key]).trim()) {
          const number = Number(typed[field.key]);
          if (!Number.isFinite(number)) throw new Error(`请填写有效的${field.label}数值。`);
          typed[field.key] = number;
        }
      }
      const response = await fetch(path, { cache: "no-store", ...(save ? { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values: typed, expected_updated_at: form?.task.updated_at }) } : {}) });
      const body: unknown = await responseBody(response);
      if (!response.ok || !isRecord(body)) throw new Error(isRecord(body) && isRecord(body.detail) ? String(body.detail.message ?? "补充字段暂不可用") : "补充字段暂不可用，请保留输入后重试。");
      if (save && form) {
        const task = body as Form["task"];
        setForm({ ...form, task }); setValues(task.template_fields); setNotice("补充字段已保存。"); onChanged?.();
      } else {
        const next = body as Form; setForm(next); setValues(next.task.template_fields);
      }
    } catch (failure) { setError(failure instanceof Error ? failure.message : "办理失败，请保留输入后重试。"); }
    finally { inFlight.current = false; setBusy(false); }
  }
  return (
    <details className="rounded-md border p-3" onToggle={event => { if (event.currentTarget.open && !form) void request(false); }}>
      <summary className="cursor-pointer text-sm font-medium">产品流程要求的补充资料</summary>
      <div className="mt-3 space-y-3">
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        {notice && <p role="status" className="text-sm">{notice}</p>}
        {busy && <p className="text-xs text-muted-foreground">正在办理…</p>}
        {form && <>
          <p className="text-xs text-muted-foreground">{form.source ? `固定采用创建时的 ${form.source.template_id} v${form.source.template_version}。` : "此项目沿用原有字段。"}新增资料不会替代原有负责人、验证和完成要求。</p>
          {!form.fields.length && <p className="text-sm">此项目没有额外配置的补充字段。</p>}
          {Date.parse(currentVersion ?? "") > Date.parse(form.task.updated_at) && <p className="text-xs text-primary">任务已有更新；请保留需要的输入，重新读取后再核对保存。</p>}
          <fieldset disabled={busy || ["done", "skipped"].includes(currentStatus ?? "") || ["done", "skipped"].includes(form.task.status)} className="space-y-3">
            {form.fields.map(field => {
              const change = (value: Values[string]) => setValues(current => ({ ...current, [field.key]: value }));
              const value = values[field.key];
              return <label key={field.key} className="block text-sm">
                {field.label}{field.unit ? ` (${field.unit})` : ""} · {field.required_at ? `${requiredStages[field.required_at]}必填` : "选填"}
                {field.help_text && <span className="mt-1 block text-xs text-muted-foreground">{field.help_text}</span>}
                {field.kind === "text" ? <textarea className={control} maxLength={field.max_length} value={value == null ? "" : String(value)} onChange={event => change(event.target.value)} /> : field.kind === "boolean" ? <select className={control} value={value == null ? "" : String(value)} onChange={event => change(event.target.value === "" ? null : event.target.value === "true")}><option value="">未填写</option><option value="true">是</option><option value="false">否</option></select> : field.kind === "choice" ? <select className={control} value={value == null ? "" : String(value)} onChange={event => change(event.target.value || null)}><option value="">未填写</option>{field.choices.map(choice => <option key={choice} value={choice}>{choice}</option>)}</select> : <input className={control} type={field.kind === "number" ? "number" : "date"} step={field.kind === "number" ? "any" : undefined} min={field.minimum ?? undefined} max={field.maximum ?? undefined} value={value == null ? "" : String(value)} onChange={event => change(event.target.value || null)} />}
              </label>;
            })}
            {form.fields.length > 0 && <Button type="button" size="sm" onClick={() => void request(true)}>保存补充资料</Button>}
          </fieldset>
          {["done", "skipped"].includes(form.task.status) && <p className="text-xs text-muted-foreground">已完成或跳过的任务保留原资料；补充工作请沿原流程另行办理。</p>}
        </>}
        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void request(false)}>{form ? "重新读取（替换未保存输入）" : "重新读取"}</Button>
      </div>
    </details>
  );
}
