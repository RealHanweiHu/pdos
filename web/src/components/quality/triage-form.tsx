import { Button } from "@/components/ui/button";

import type { Complaint, NcrCreateInput } from "./quality-types";

const fieldClass =
  "min-h-11 w-full rounded-lg border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/20";

export function TriageForm({
  busy,
  complaint,
  onSubmit,
}: {
  busy: boolean;
  complaint: Complaint;
  onSubmit: (input: NcrCreateInput) => Promise<boolean>;
}) {
  return (
    <form
      action={(form) =>
        void onSubmit({
          nonconformity: String(form.get("nonconformity")),
          requirement_reference: String(form.get("requirement_reference")),
          severity: String(form.get("severity")) as NcrCreateInput["severity"],
          owner_user_id: complaint.owner_user_id,
          target_date: String(form.get("target_date")),
          affected_quantity: form.get("affected_quantity")
            ? Number(form.get("affected_quantity"))
            : null,
          affected_scope: complaint.affected_scope,
        })
      }
      className="mt-4 grid gap-3 rounded-lg border border-primary/20 bg-primary/5 p-4"
    >
      <h4 className="font-semibold">Triage 并创建 NCR</h4>
      <label className="grid gap-1.5 text-sm font-medium">
        不符合描述
        <textarea className={fieldClass} name="nonconformity" required rows={3} />
      </label>
      <label className="grid gap-1.5 text-sm font-medium">
        违反要求
        <input className={fieldClass} name="requirement_reference" required />
      </label>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="grid gap-1.5 text-sm font-medium">
          严重度
          <select className={fieldClass} defaultValue={complaint.severity} name="severity">
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          目标日期
          <input className={fieldClass} name="target_date" required type="date" />
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          影响数量
          <input className={fieldClass} min={0} name="affected_quantity" type="number" />
        </label>
      </div>
      <Button className="h-11 justify-self-start" disabled={busy} type="submit">
        {busy ? "正在 Triage…" : "确认 Triage"}
      </Button>
    </form>
  );
}
