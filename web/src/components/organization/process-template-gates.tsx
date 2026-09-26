"use client";

import { Button } from "@/components/ui/button";

export type GateSlot = "product" | "engineering" | "quality";
export type GateRequirement = "not_applicable" | "conditional" | "required";
export type GateStatus = "pending" | "approved" | "conditional" | "rejected" | "not_applicable";
export type GateRequirements = Record<string, Record<GateSlot, GateRequirement>>;
export type GateCheck = { stage: string; signoffs: Partial<Record<GateSlot, GateStatus>>; expected_ready: boolean };
type Stage = { code: string; name: string };
export const gateSlots: Record<GateSlot, string> = { product: "产品", engineering: "工程", quality: "品质" };
export const gateRequirements: Record<GateRequirement, string> = { not_applicable: "不适用", conditional: "可有条件签核", required: "必须批准" };
const statuses: Record<GateStatus, string> = { pending: "待签核", approved: "批准", conditional: "有条件批准", rejected: "拒绝", not_applicable: "不适用" };
const rank: Record<GateRequirement, number> = { not_applicable: 0, conditional: 1, required: 2 };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

export function GateRulesEditor({ stages, minimum, value, onChange }: { stages: Stage[]; minimum: GateRequirements; value: GateRequirements; onChange: (value: GateRequirements) => void }) {
  return <details><summary className="cursor-pointer text-sm font-medium">各阶段审批要求</summary>
    <p className="mt-2 text-xs text-muted-foreground">发布后选择此版创建的新项目会实际采用以下签核要求。原有硬闸和依据版本已设要求保留；在途项目不自动改写。</p>
    <div className="mt-3 space-y-3">{stages.map(stage => <div key={stage.code} className="rounded-md border p-3"><p className="text-sm font-medium">{stage.name}</p><div className="grid gap-3 sm:grid-cols-3">{(Object.keys(gateSlots) as GateSlot[]).map(slot => <label key={slot} className="text-sm">{gateSlots[slot]}签核<select className={field} value={value[stage.code]?.[slot] ?? minimum[stage.code][slot]} onChange={event => onChange({ ...value, [stage.code]: { ...(value[stage.code] ?? minimum[stage.code]), [slot]: event.target.value as GateRequirement } })}>{(Object.keys(gateRequirements) as GateRequirement[]).filter(item => rank[item] >= rank[minimum[stage.code][slot]]).map(item => <option key={item} value={item}>{gateRequirements[item]}</option>)}</select></label>)}</div></div>)}</div>
  </details>;
}

export function gateExamples(baseline: GateRequirements, configured: GateRequirements): [GateCheck[], GateCheck[]] {
  const positive: GateCheck[] = [], negative: GateCheck[] = [];
  for (const [stage, slots] of Object.entries(configured)) {
    const changes = (Object.keys(gateSlots) as GateSlot[]).filter(slot => slots[slot] !== baseline[stage][slot]);
    if (!changes.length) continue;
    const signoffs = Object.fromEntries((Object.keys(gateSlots) as GateSlot[]).map(slot => [slot, slots[slot] === "not_applicable" ? "not_applicable" : "approved"])) as Record<GateSlot, GateStatus>;
    positive.push({ stage, signoffs, expected_ready: true });
    for (const slot of changes) negative.push({ stage, signoffs: { ...signoffs, [slot]: baseline[stage][slot] === "not_applicable" ? "not_applicable" : "conditional" }, expected_ready: false });
  }
  return [positive, negative];
}

export function GateRehearsalEditor({ stages, value, onChange }: { stages: Stage[]; value: GateCheck[]; onChange: (value: GateCheck[]) => void }) {
  const edit = (index: number, change: Partial<GateCheck>) => onChange(value.map((item, n) => n === index ? { ...item, ...change } : item));
  return <details open={value.length > 0}><summary className="cursor-pointer text-sm font-medium">模拟审批签核</summary>
    <p className="mt-2 text-xs text-muted-foreground">每项新增签核要求须有满足要求的正例，以及原规则能通过、新规则应拦截的反例。这里只判断签核状态，业务证据及签核人权限仍由正式办理核验。</p>
    {value.map((item, index) => <div key={index} className="mt-3 space-y-2 rounded-md border p-3"><label className="block text-sm">阶段<select className={field} value={item.stage} onChange={event => edit(index, { stage: event.target.value })}>{stages.map(stage => <option key={stage.code} value={stage.code}>{stage.name}</option>)}</select></label><div className="grid gap-3 sm:grid-cols-3">{(Object.keys(gateSlots) as GateSlot[]).map(slot => <label key={slot} className="text-sm">{gateSlots[slot]}签核<select className={field} value={item.signoffs[slot] ?? "pending"} onChange={event => edit(index, { signoffs: { ...item.signoffs, [slot]: event.target.value as GateStatus } })}>{Object.entries(statuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>)}</div><label className="block text-sm">预期签核条件<select className={field} value={String(item.expected_ready)} onChange={event => edit(index, { expected_ready: event.target.value === "true" })}><option value="true">已满足</option><option value="false">未满足</option></select></label><Button type="button" size="sm" variant="ghost" onClick={() => onChange(value.filter((_, n) => n !== index))}>移除此签核场景</Button></div>)}
    <Button type="button" size="sm" variant="outline" className="mt-2" disabled={value.length >= 30} onClick={() => onChange([...value, { stage: stages[0].code, signoffs: {}, expected_ready: false }])}>增加签核场景</Button>
  </details>;
}
