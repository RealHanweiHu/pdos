"use client";
// D308 (P96 第 5–7 项): engineering named approval of an alternate for one BOM line of this
// Build only; it counts in this Build's kit, never changes the BOM, and may expire or be revoked.
import { useCallback, useEffect, useRef, useState } from "react";
import { Swap } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { NamedCommandReview } from "@/features/projects/named-command-review";
import { makeCommand } from "@/lib/named-command";
import type { ProjectApi } from "@/lib/project-plan-view";
import { alternateStateNames, isoFromLocal, timeText } from "@/lib/d47-records";
import { useNamedAction } from "./use-named-action";

type Approval = { id: string; revision: number; state: string; item_id: string; target_material_id: string; alternate_material_id: string; alternate_unit: string; alternate_quantity_per_target: string; valid_until: string | null; evidence_run: { id: string; revision: number; status: string } | null; reason: string | null };
export type DemandLine = { item_id: string; material_id: string | null; name?: string; unit?: string | null };
type Props = { api: ProjectApi; product: { id: string; revision: number }; build: { id: string; revision: number }; lines: DemandLine[] };

export function AlternateApprovals({ api, product, build, lines }: Props) {
  const action = useNamedAction(api);
  const { setError } = action;
  const [items, setItems] = useState<Approval[] | null>(null);
  const [item, setItem] = useState(""), [alternate, setAlternate] = useState(""), [unit, setUnit] = useState("ea"), [ratio, setRatio] = useState("1");
  const [run, setRun] = useState(""), [runRevision, setRunRevision] = useState(""), [until, setUntil] = useState(""), [reason, setReason] = useState("");
  const alive = useRef(true);
  const refresh = useCallback(async () => { const value = await api<{ items: Approval[] }>(`v1/products/${product.id}/builds/${build.id}/alternate-approvals`); if (alive.current) setItems(value.items); }, [api, product.id, build.id]);
  useEffect(() => { alive.current = true; void Promise.resolve().then(() => alive.current ? refresh() : undefined).catch(failure => setError((failure as Error).message)); return () => { alive.current = false; }; }, [refresh, setError]);
  const evidence = () => { if (!run.trim() || !Number(runRevision)) throw new Error("请填写替代料测试运行的标识与当前版本（须已有具名复核）。"); return { id: run.trim(), revision: Number(runRevision) }; };
  function approve(previous?: Approval) {
    void action.start(() => makeCommand(product, "supply.alternate.approve", previous
      ? { approval: { id: previous.id, revision: previous.revision }, action: "approve", evidence_run: evidence(), valid_until: isoFromLocal(until), reason: reason.trim() || "重新批准替代料" }
      : { action: "approve", scope: { build_id: build.id, expected_build_revision: build.revision, item_id: item, alternate_material_id: alternate.trim(), alternate_unit: unit.trim(), alternate_quantity_per_target: ratio.trim() }, evidence_run: evidence(), valid_until: isoFromLocal(until), reason: reason.trim() || "替代料经复测可用于本轮" }), "T2");
  }
  function revoke(previous: Approval) {
    void action.start(() => makeCommand(product, "supply.alternate.approve", { approval: { id: previous.id, revision: previous.revision }, action: "revoke", reason: reason.trim() || "撤销替代料批准" }), "T2");
  }
  return <section className="min-w-0 space-y-3 rounded-lg border border-border p-3" aria-label="替代料批准">
    <h3 className="flex items-center gap-2 font-semibold"><Swap aria-hidden size={16}/>替代料批准（本轮）</h3>
    <p className="subtle text-xs">工程具名批准，须引用替代料的测试运行和当前具名复核。只计入这一轮齐套，不改 BOM；过期、撤销或 BOM 变化后不再计入。永久替换走变更单。</p>
    {action.error && <p role="alert" className="text-sm text-destructive [overflow-wrap:anywhere]">{action.error}</p>}
    {action.notice && <p role="status" className="text-sm">{action.notice}</p>}
    {items === null ? <p className="subtle text-sm">正在读取…</p> : items.length === 0 ? <p className="subtle text-sm">本轮没有替代料批准。</p> : <ul className="space-y-2">{items.map(row => <li key={row.id} className="border-t border-border pt-2 text-sm">
      <p>{row.item_id}：{row.target_material_id} → {row.alternate_material_id}（每件 {row.alternate_quantity_per_target} {row.alternate_unit}）· {alternateStateNames[row.state]} · v{row.revision} · 有效至 {timeText(row.valid_until)}</p>
      {row.evidence_run && <p className="subtle text-xs">证据运行 {row.evidence_run.id.slice(0, 8)} v{row.evidence_run.revision}（{row.evidence_run.status === "disposed" ? "已处置" : "已复核"}）</p>}
      <div className="mt-1 flex gap-2">{row.state === "approved" ? <Button size="sm" variant="ghost" disabled={action.busy} onClick={() => revoke(row)}>撤销</Button> : <Button size="sm" variant="outline" disabled={action.busy} onClick={() => approve(row)}>重新批准</Button>}</div>
    </li>)}</ul>}
    <details className="space-y-2"><summary className="cursor-pointer text-sm font-medium">批准新的替代</summary>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block text-xs">BOM 行<select value={item} onChange={e => setItem(e.target.value)}><option value="">选择本轮需求行</option>{lines.filter(l => l.material_id).map(l => <option key={l.item_id} value={l.item_id}>{l.name ?? l.item_id} · {l.material_id}</option>)}</select></label>
        <label className="block text-xs">替代料标识<input value={alternate} onChange={e => setAlternate(e.target.value)}/></label>
        <label className="block text-xs">替代料单位<input value={unit} onChange={e => setUnit(e.target.value)}/></label>
        <label className="block text-xs">每件原料用替代料数量<input value={ratio} inputMode="decimal" onChange={e => setRatio(e.target.value)}/></label>
      </div>
    </details>
    <div className="grid gap-2 sm:grid-cols-2">
      <label className="block text-xs">证据测试运行标识<input value={run} onChange={e => setRun(e.target.value)}/></label>
      <label className="block text-xs">证据运行当前版本<input value={runRevision} inputMode="numeric" onChange={e => setRunRevision(e.target.value)}/></label>
      <label className="block text-xs">有效期至（可选）<input type="datetime-local" value={until} onChange={e => setUntil(e.target.value)}/></label>
      <label className="block text-xs">理由<input value={reason} onChange={e => setReason(e.target.value)}/></label>
    </div>
    {action.prepared ? <NamedCommandReview prepared={action.prepared} busy={action.busy} onCancel={action.cancel} onConfirm={() => void action.confirm("alternate_approval", "已保存；重新记录供给快照并计算齐套后计入。", refresh)}/> : <Button size="sm" variant="outline" disabled={action.busy || !item || !alternate.trim()} onClick={() => approve()}>预览具名批准</Button>}
  </section>;
}
