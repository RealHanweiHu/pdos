"use client";
// D310 (P100 第 1–2 项): named withdrawal of a source already used by signed decisions or
// shared to the category. One's own unused originals keep the one-confirmation path.
import { useState } from "react";
import { ArrowUUpLeft } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { NamedCommandReview } from "@/features/projects/named-command-review";
import { makeCommand } from "@/lib/named-command";
import type { ProjectApi } from "@/lib/project-plan-view";
import { useNamedAction } from "./use-named-action";

type Props = {
  api: ProjectApi; product: { id: string; revision: number }; onSaved: () => void | Promise<void>;
  source: { id: string; title: string; revision: number; status: string; visibility: string };
  originals: { id: string; artifact_id: string | null; security?: { epoch: number; source_state: string } }[];
};
type Dependent = { table: string; count: number };
const tableNames: Record<string, string> = { definition_sources: "定义引用", definition_revisions: "定义版本", claims: "来源事实", claim_consumptions: "事实被决定使用", evidence_links: "证据关联" };

export function SourceWithdraw({ api, product, onSaved, source, originals }: Props) {
  const action = useNamedAction(api);
  const [reason, setReason] = useState("");
  if (source.status !== "active") return <p className="subtle text-xs">此来源已撤回，依赖它的结果显示“需重核”。</p>;
  const original = originals.find(row => row.artifact_id === source.id);
  const dependents = (action.prepared?.review.dependents ?? []) as Dependent[];
  return <details className="mt-3 space-y-2 rounded-lg border border-border p-3 text-sm">
    <summary className="cursor-pointer font-medium"><ArrowUUpLeft aria-hidden className="mr-1 inline" size={14}/>具名撤回来源</summary>
    <p className="subtle text-xs">用于已被签署决定使用或已共享到品类的来源，由来源负责人或品类负责人办理。撤回后依赖结果改为“需重核”，不删除任何记录。本人上传、未被使用的原件请用原件卡片上的“撤回”。</p>
    <label className="block text-xs">撤回理由<input value={reason} maxLength={2000} onChange={e => setReason(e.target.value)}/></label>
    {action.error && <p role="alert" className="text-xs text-destructive [overflow-wrap:anywhere]">{action.error}</p>}
    {action.notice && <p role="status" className="text-xs">{action.notice}</p>}
    {action.prepared ? <NamedCommandReview prepared={action.prepared} busy={action.busy} onCancel={action.cancel} onConfirm={() => void action.confirm(original ? "uploaded_original" : "artifact", "来源已撤回；依赖它的结果改为需重核。", onSaved)}>
      <p className="text-xs">将标为需重核：{dependents.length ? dependents.map(row => `${tableNames[row.table] ?? row.table} ${row.count} 项`).join("、") : "无业务记录使用"}</p>
    </NamedCommandReview> : <Button size="sm" variant="outline" disabled={action.busy || reason.trim().length < 3} onClick={() => void action.start(() => makeCommand(product, "evidence.source.withdraw", original
      ? { source_id: original.id, kind: "original", expected_revision: original.security?.epoch ?? 1, reason: reason.trim() }
      : { source_id: source.id, kind: "artifact", expected_revision: source.revision, reason: reason.trim() }), "T2")}>预览具名撤回</Button>}
  </details>;
}
