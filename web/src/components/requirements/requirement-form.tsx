"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

import type { CustomerSummary, Requirement } from "./requirement-types";

export type RequirementFormValues = {
  code: string;
  title: string;
  customer_id: string | null;
  priority: "low" | "medium" | "high" | "critical";
  source: string | null;
  description: string | null;
  acceptance_criteria: string[];
  status?: "draft" | "proposed" | "approved" | "rejected";
};

export type RequirementSubmissionResult =
  | { ok: true }
  | { ok: false; message: string };

const controlClass =
  "mt-1 min-h-11 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 disabled:cursor-not-allowed disabled:opacity-60";

export function RequirementForm({
  busy,
  customers,
  onCancel,
  onSubmit,
  requirement,
}: {
  busy: boolean;
  customers: CustomerSummary[];
  onCancel: () => void;
  onSubmit: (values: RequirementFormValues) => Promise<RequirementSubmissionResult>;
  requirement?: Requirement;
}) {
  const codeRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const pendingCrmReview = requirement?.source === "crm" && requirement.status === "draft";

  useEffect(() => {
    codeRef.current?.focus();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const data = new FormData(event.currentTarget);
    const source = String(data.get("source") ?? "").trim();
    const description = String(data.get("description") ?? "").trim();
    const customerId = String(data.get("customer_id") ?? "");
    const criteria = String(data.get("acceptance_criteria") ?? "")
      .split("\n")
      .map((value) => value.trim())
      .filter(Boolean);
    const values: RequirementFormValues = {
      code: String(data.get("code") ?? "").trim(),
      title: String(data.get("title") ?? "").trim(),
      customer_id: customerId || null,
      priority: String(data.get("priority") ?? "medium") as RequirementFormValues["priority"],
      source: source || null,
      description: description || null,
      acceptance_criteria: criteria,
    };
    if (requirement && requirement.status !== "converted" && !pendingCrmReview) {
      values.status = String(data.get("status") ?? "draft") as NonNullable<
        RequirementFormValues["status"]
      >;
    }
    const result = await onSubmit(values);
    if (!result.ok) setError(result.message);
  }

  return (
    <form aria-labelledby="requirement-form-title" className="space-y-4" onSubmit={submit}>
      <div>
        <h2 className="font-semibold" id="requirement-form-title">
          {requirement ? "编辑需求" : "新建需求"}
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">
          {requirement ? "修改会留下事件与前后快照。" : "编号与标题必填；客户可稍后关联。"}
        </p>
      </div>
      {error ? (
        <div
          className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          role="alert"
        >
          {error}
        </div>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-xs font-medium" htmlFor="requirement-code">
          需求编号
          <input
            className={controlClass}
            disabled={busy}
            id="requirement-code"
            maxLength={64}
            name="code"
            ref={codeRef}
            required
            defaultValue={requirement?.code}
          />
        </label>
        <label className="text-xs font-medium" htmlFor="requirement-priority">
          优先级
          <select
            className={controlClass}
            defaultValue={requirement?.priority ?? "medium"}
            disabled={busy}
            id="requirement-priority"
            name="priority"
          >
            <option value="low">低</option>
            <option value="medium">中</option>
            <option value="high">高</option>
            <option value="critical">关键</option>
          </select>
        </label>
      </div>
      <label className="block text-xs font-medium" htmlFor="requirement-title">
        标题
        <input
          className={controlClass}
          disabled={busy}
          id="requirement-title"
          maxLength={512}
          name="title"
          required
          defaultValue={requirement?.title}
        />
      </label>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-xs font-medium" htmlFor="requirement-customer">
          客户
          <select
            className={controlClass}
            defaultValue={requirement?.customer?.id ?? ""}
            disabled={busy}
            id="requirement-customer"
            name="customer_id"
          >
            <option value="">暂不关联</option>
            {customers.map((customer) => (
              <option
                disabled={
                  customer.status !== "active" && customer.id !== requirement?.customer?.id
                }
                key={customer.id}
                value={customer.id}
              >
                {customer.code} · {customer.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-medium" htmlFor="requirement-source">
          来源{requirement ? "（创建后不可修改）" : null}
          <input
            className={controlClass}
            defaultValue={requirement ? (requirement.source ?? "") : "manual"}
            disabled={busy || Boolean(requirement)}
            id="requirement-source"
            maxLength={64}
            name="source"
          />
        </label>
      </div>
      <label className="block text-xs font-medium" htmlFor="requirement-description">
        描述
        <textarea
          className={`${controlClass} min-h-24 resize-y`}
          disabled={busy}
          id="requirement-description"
          maxLength={20_000}
          name="description"
          defaultValue={requirement?.description ?? ""}
        />
      </label>
      <label className="block text-xs font-medium" htmlFor="requirement-criteria">
        验收标准（每行一条）
        <textarea
          className={`${controlClass} min-h-24 resize-y font-mono text-xs`}
          disabled={busy}
          id="requirement-criteria"
          name="acceptance_criteria"
          defaultValue={requirement?.acceptance_criteria.join("\n")}
        />
      </label>
      {requirement && requirement.status !== "converted" && !pendingCrmReview ? (
        <label className="block text-xs font-medium" htmlFor="requirement-status">
          状态
          <select
            className={controlClass}
            defaultValue={requirement.status}
            disabled={busy}
            id="requirement-status"
            name="status"
          >
            <option value="draft">草稿</option>
            <option value="proposed">待评估</option>
            <option value="approved">已批准</option>
            <option value="rejected">已拒绝</option>
          </select>
        </label>
      ) : requirement ? (
        <div className="text-xs font-medium">
          状态
          <p className="mt-1 rounded-lg border bg-muted px-3 py-2 text-sm font-normal text-muted-foreground">
            {pendingCrmReview
              ? "CRM 草稿（状态仅可通过下方独立人审动作更新）"
              : "已转开发案（状态由转 Case 流程维护）"}
          </p>
        </div>
      ) : null}
      <div className="flex justify-end gap-2 border-t pt-4">
        <Button
          className="h-11 sm:h-8"
          disabled={busy}
          onClick={onCancel}
          type="button"
          variant="outline"
        >
          取消
        </Button>
        <Button className="h-11 sm:h-8" disabled={busy} type="submit">
          {busy ? "正在保存…" : requirement ? "保存更改" : "保存需求"}
        </Button>
      </div>
    </form>
  );
}
