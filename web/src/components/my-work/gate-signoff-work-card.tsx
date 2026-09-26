"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { requestProjectGates, signProjectGateRound } from "@/components/projects/project-gate-document-api";
import type { ProjectGate } from "@/components/projects/project-gate-document-types";
import type { MyWorkGateSignoff } from "./my-work-types";

const slots: Record<string, string> = { product: "产品", engineering: "工程", quality: "质量" };
const statuses: Record<string, string> = { pending: "待签核", approved: "通过", conditional: "有条件通过", rejected: "不通过", not_applicable: "不适用" };
const requirements: Record<string, string> = { required: "必需签核", conditional: "允许有条件签核", not_applicable: "不适用" };
const blockerTabs: Record<string, string> = { task: "work-items", issue: "work-items", risk: "work-items", sample: "npi", test: "npi", test_run: "npi", sample_signoff: "quality", ncr: "quality", capa: "quality", document: "documents" };
type Outcome = "approved" | "conditional" | "rejected";

export function GateSignoffWorkCard({ item, onChanged, onNotice }: {
  item: MyWorkGateSignoff;
  onChanged: () => Promise<void>;
  onNotice: (notice: string) => void;
}) {
  const [gate, setGate] = useState<ProjectGate | null>(null);
  const [loaded, setLoaded] = useState(false), [busy, setBusy] = useState(false), [stale, setStale] = useState(false);
  const [error, setError] = useState("");
  const [outcome, setOutcome] = useState<Outcome>("approved"), [note, setNote] = useState(""), [reviewed, setReviewed] = useState(false);
  const round = gate?.round;
  const signoff = round?.signoffs.find(row => row.slot === item.slot);
  const routeBlockers = round?.routing_blockers?.[item.slot] ?? [];
  const sameWork = !!gate?.is_current && gate.status === "reviewing" && round?.status === "open" && round.round_number === item.round_number && signoff?.id === item.id && signoff.status === "pending";
  const maySubmit = sameWork && !!gate?.signing_basis && !busy && !stale && reviewed && !!note.trim() && (outcome === "rejected" || routeBlockers.length === 0) && (outcome !== "conditional" || signoff?.requirement === "conditional");

  async function read() {
    setLoaded(true); setBusy(true); setError(""); setReviewed(false);
    try {
      const result = (await requestProjectGates(item.project.id)).find(row => row.id === item.gate_id);
      if (!result) throw new Error("原阶段签核当前不可用，请刷新待办。");
      setGate(result); setStale(false);
    } catch (error) { setStale(true); setError(error instanceof Error ? error.message : "读取签核失败"); }
    finally { setBusy(false); }
  }

  async function submit() {
    if (!maySubmit || !gate || !round || !["product", "engineering", "quality"].includes(item.slot)) return;
    setBusy(true); setError("");
    try {
      const result = await signProjectGateRound(item.project.id, gate.id, round.id, item.slot as "product" | "engineering" | "quality", { status: outcome, note: note.trim(), expected_basis: gate.signing_basis });
      setGate(result); setReviewed(false);
      onNotice(`${item.gate_name} · 第 ${round.round_number} 轮${slots[item.slot]}签核已记录：${statuses[outcome]}。阶段决策仍按原流程办理。`);
      await onChanged();
    } catch (error) { setStale(true); setReviewed(false); setError(error instanceof Error ? error.message : "签核结果未确认，请刷新后核对"); }
    finally { setBusy(false); }
  }

  return <details className="mx-4 mb-3" onToggle={event => { if (event.currentTarget.open && !loaded) void read(); }}>
    <summary className="cursor-pointer text-sm text-primary">查看依据并签核</summary>
    <div className="mt-2 space-y-3 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void read()}>{busy ? "处理中…" : "刷新本轮资料"}</Button><a className="text-primary underline" href={`/projects?project=${item.project.id}&tab=gates`}>打开项目阶段依据</a></div>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {stale && <p>刷新后核对实际签核状态再提交；填写的意见保留。</p>}
      {gate && <>
        <p>{gate.stage.name} · {gate.name} · 当前第 {round?.round_number ?? "—"} 轮 · {requirements[signoff?.requirement ?? ""] ?? "签核要求不可用"}</p>
        {!sameWork && <p role="status">本项已办理、轮次已变化或不再属于当前阶段，请刷新待办后继续。</p>}
        <div className="space-y-2">{round?.signoffs.map(row => <div key={row.slot} className="rounded-md border p-2">
          <p>{slots[row.slot] ?? row.slot}：{statuses[row.status] ?? row.status} · {requirements[row.requirement] ?? row.requirement}</p>
          {round?.routing_snapshot?.assignment?.signers[row.slot] && <p className="text-xs">本轮指定：{round.routing_snapshot.assignment.signers[row.slot].display_name}</p>}
          {row.signed_at && <p className="text-xs text-muted-foreground">签核时间 {new Date(row.signed_at).toLocaleString("zh-CN")}</p>}
          {row.note && <p className="whitespace-pre-wrap">意见：{row.note}</p>}
        </div>)}</div>
        {routeBlockers.length > 0 && <p className="text-pending">通过前需先完成：{routeBlockers.map(slot => slots[slot] ?? slot).join("、")}签核。</p>}
        <details className="rounded-md border p-2"><summary className="cursor-pointer">当前阶段前置检查 · {gate.readiness.blockers.length} 项待办</summary>
          <p className="my-2 text-xs">单席签核不会自动通过阶段。阶段负责人仍须核对全部前置及三席意见并记录决策。</p>
          {gate.readiness.blockers.map(blocker => <p key={blocker.key} className="my-1"><a className="text-primary underline" href={`/projects?project=${item.project.id}&tab=${blockerTabs[blocker.kind] ?? "gates"}`}>{blocker.label}</a></p>)}
        </details>
        {sameWork && <form className="space-y-3" onSubmit={event => { event.preventDefault(); void submit(); }}><fieldset disabled={busy || stale} className="space-y-3">
          <label className="block">本席结论<select className="ml-2 rounded-md border bg-background p-2" value={outcome} onChange={event => { setOutcome(event.target.value as Outcome); setReviewed(false); }}><option value="approved">通过</option>{signoff?.requirement === "conditional" && <option value="conditional">有条件通过</option>}<option value="rejected">不通过</option></select></label>
          <label className="block">签核意见、依据及需补齐事项<textarea required maxLength={20000} className="mt-1 min-h-24 w-full rounded-md border bg-background p-2" value={note} onChange={event => { setNote(event.target.value); setReviewed(false); }}/></label>
          <p>本次将{slots[item.slot]}席由“{statuses[signoff?.status ?? ""]}”改为“{statuses[outcome]}”，记录本人意见；后续由依赖本席的专业及阶段负责人办理。</p>
          <label className="flex items-start gap-2"><input type="checkbox" checked={reviewed} onChange={event => setReviewed(event.target.checked)}/><span>已核对当前轮次、各席意见及依据，确认本席结论。</span></label>
          <Button size="sm" type="submit" disabled={!maySubmit}>记录本席签核</Button>
        </fieldset></form>}
      </>}
    </div>
  </details>;
}
