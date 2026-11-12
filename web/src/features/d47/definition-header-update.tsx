"use client";
// D311 (P100 第 3 项): edit the definition's header as the next draft revision, one confirmation.
import { useState } from "react";
import { NotePencil } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { NamedCommandReview } from "@/features/projects/named-command-review";
import { makeCommand } from "@/lib/named-command";
import type { ProjectApi } from "@/lib/project-plan-view";
import { splitLines } from "@/lib/d47-records";
import { useNamedAction } from "./use-named-action";

type Definition = {
  id: string; revision: number; status: string; variant_id: string | null; sealed: boolean;
  title: string; purpose: string; use_cases: string[]; requirements: string[]; constraints: string[]; unknowns: string[]; exclusions: string[];
};
type Props = { definition: Definition; product: { id: string; revision: number }; api: ProjectApi; onSaved: () => void | Promise<void> };
const LISTS = [["use_cases", "使用场景"], ["requirements", "需求"], ["constraints", "约束"], ["exclusions", "排除项"], ["unknowns", "未知项"]] as const;
type Change = { path: string; before: unknown; after: unknown };

export function DefinitionHeaderUpdate({ definition, product, api, onSaved }: Props) {
  const action = useNamedAction(api);
  const [title, setTitle] = useState(definition.title), [purpose, setPurpose] = useState(definition.purpose), [reason, setReason] = useState("");
  const [lists, setLists] = useState<Record<string, string>>(() => Object.fromEntries(LISTS.map(([key]) => [key, (definition[key] ?? []).join("\n")])));
  if (definition.status === "published" || definition.variant_id) return <p className="subtle text-xs">{definition.status === "published" ? "规格已冻结，修改须走变更单。" : "派生型号的定义按派生与重新基准办理。"}</p>;
  const changes = (action.prepared?.review.changes ?? []) as Change[];
  return <details className="space-y-3 rounded-lg border border-border p-3">
    <summary className="cursor-pointer text-sm font-medium"><NotePencil aria-hidden className="mr-1 inline" size={14}/>修改整体字段（生成第 {definition.revision + 1} 版草稿）</summary>
    <p className="subtle text-xs">只生成新的草稿版本，第 {definition.revision} 版及其条目不变；条目请在“维护条目”里修改。{definition.sealed ? "当前版本已封存，修改从新版本开始。" : ""}</p>
    <label className="block space-y-1 text-sm"><span>标题</span><input value={title} maxLength={200} onChange={event => setTitle(event.target.value)}/></label>
    <label className="block space-y-1 text-sm"><span>目的</span><textarea value={purpose} maxLength={2000} onChange={event => setPurpose(event.target.value)}/></label>
    {LISTS.map(([key, label]) => <label key={key} className="block space-y-1 text-sm"><span>{label}（每行一条）</span><textarea value={lists[key]} onChange={event => setLists(current => ({ ...current, [key]: event.target.value }))}/></label>)}
    <label className="block space-y-1 text-sm"><span>改版原因</span><input value={reason} maxLength={2000} onChange={event => setReason(event.target.value)}/></label>
    {action.error && <p role="alert" className="text-sm text-destructive [overflow-wrap:anywhere]">{action.error}</p>}
    {action.notice && <p role="status" className="text-sm">{action.notice}</p>}
    {action.prepared ? <NamedCommandReview prepared={action.prepared} busy={action.busy} onCancel={action.cancel} onConfirm={() => void action.confirm("definition_revision", `已生成第 ${definition.revision + 1} 版草稿。`, onSaved)}>
      <ul className="space-y-1 text-xs">{changes.map(change => <li key={change.path}><span className="font-medium">{change.path}</span>：{JSON.stringify(change.before)} → {JSON.stringify(change.after)}</li>)}</ul>
    </NamedCommandReview> : <Button size="sm" variant="outline" disabled={action.busy} onClick={() => void action.start(() => makeCommand(product, "product.definition.update", {
      definition_id: definition.id, expected_definition_revision: definition.revision, title: title.trim(), purpose: purpose.trim(),
      ...Object.fromEntries(LISTS.map(([key]) => [key, splitLines(lists[key])])), change_reason: reason.trim(),
    }), "T1")}>预览新草稿</Button>}
  </details>;
}
