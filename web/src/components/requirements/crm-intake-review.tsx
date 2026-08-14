"use client";

import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";

export type CrmReviewResult = { ok: true } | { ok: false; message: string };

export function CrmIntakeReview({
  busy,
  onReview,
}: {
  busy: boolean;
  onReview: (
    decision: "establish" | "reject",
    rationale: string,
  ) => Promise<CrmReviewResult>;
}) {
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const decision = submitter?.value === "reject" ? "reject" : "establish";
    const rationale = String(new FormData(event.currentTarget).get("rationale") ?? "").trim();
    if (!rationale) {
      setError("请填写人审理由。 ");
      return;
    }
    const result = await onReview(decision, rationale);
    if (!result.ok) setError(result.message);
  }

  return (
    <form className="mt-4 space-y-3 border-t pt-4" onSubmit={submit}>
      <div>
        <h3 className="text-sm font-semibold">CRM 草稿人审</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          外部 CRM 只创建草稿。成立后进入待评估；拒绝后终止。
        </p>
      </div>
      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      <label className="block text-xs font-medium" htmlFor="crm-review-rationale">
        人审理由
        <textarea
          className="mt-1 min-h-20 w-full resize-y rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20"
          disabled={busy}
          id="crm-review-rationale"
          maxLength={20_000}
          name="rationale"
          required
        />
      </label>
      <div className="grid grid-cols-2 gap-2">
        <Button disabled={busy} name="decision" type="submit" value="reject" variant="outline">
          拒绝草稿
        </Button>
        <Button disabled={busy} name="decision" type="submit" value="establish">
          成立需求
        </Button>
      </div>
    </form>
  );
}
