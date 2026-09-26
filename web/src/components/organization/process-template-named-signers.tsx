"use client";

import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import { gateSlots, type GateSlot, type GateRequirements } from "./process-template-gates";

export type NamedSlots = Record<string, GateSlot[]>;
type Stage = { code: string; name: string };
const scenarios = { qualified: "人员齐全且有签核权限", missing: "所选槽位未指定人员", unqualified: "所选人员无该槽位权限", nonmember: "所选人员不是有效项目成员" } as const;
export type SignerCase = { stage: string; slot: GateSlot; scenario: keyof typeof scenarios; expected_valid: boolean };
const field = "mt-1 block w-full rounded-md border bg-background p-2 text-sm";

export function namedSignerExamples(value: NamedSlots): SignerCase[] {
  return Object.entries(value).flatMap(([stage, slots]) => slots.flatMap(slot => (Object.keys(scenarios) as (keyof typeof scenarios)[]).map(scenario => ({ stage, slot, scenario, expected_valid: scenario === "qualified" }))));
}

export function NamedSignerEditor({ stages, requirements, value, onChange }: { stages: Stage[]; requirements: GateRequirements; value: NamedSlots; onChange: (value: NamedSlots) => void }) {
  function edit(stage: string, slot: GateSlot, enabled: boolean) {
    const next = { ...value, [stage]: enabled ? [...value[stage] ?? [], slot] : (value[stage] ?? []).filter(s => s !== slot) };
    if (!next[stage].length) delete next[stage];
    onChange(next);
  }
  return <details><summary className="cursor-pointer text-sm font-medium">必须具名的阶段签核</summary><p className="mt-2 text-xs text-muted-foreground">选择此版创建的新项目固定这些要求。每次开轮或更换人员后，必须为勾选槽位选择当前项目中有对应签核权限的人员；模板不指定具体账号。取消勾选仅影响以后采用此版的新项目。</p><div className="mt-3 space-y-2">{stages.map(stage => <div className="rounded-md border p-3" key={stage.code}><p className="text-sm font-medium">{stage.name}</p><div className="mt-2 flex flex-wrap gap-4">{(Object.keys(gateSlots) as GateSlot[]).map(slot => <label className="flex items-center gap-2 text-sm" key={slot}><input type="checkbox" disabled={requirements[stage.code]?.[slot] === "not_applicable" && !value[stage.code]?.includes(slot)} checked={value[stage.code]?.includes(slot) ?? false} onChange={e => edit(stage.code, slot, e.target.checked)} />{gateSlots[slot]}必须指定签核人{requirements[stage.code]?.[slot] === "not_applicable" && "（当前不适用）"}</label>)}</div></div>)}</div></details>;
}

export function NamedSignerRehearsal({ stages, policy, value, onChange }: { stages: Stage[]; policy: NamedSlots; value: SignerCase[]; onChange: (value: SignerCase[]) => void }) {
  if (!Object.values(policy).some(slots => slots.length) && !value.length) return null;
  const stageLabel = (code: string) => stages.find(s => s.code === code)?.name ?? code;
  function edit(index: number, change: Partial<SignerCase>) { onChange(value.map((item, n) => n === index ? { ...item, ...change } : item)); }
  return <details><summary className="cursor-pointer text-sm font-medium">具名签核分派演练 · {value.length} 项</summary><p className="mt-2 text-xs text-muted-foreground">每个必需具名槽位须覆盖人员齐全、缺人、权限不符和非项目成员。其余必需槽位使用有效的模拟人员；此处与实际开轮共用分派校验，不代表真实人员已签核。</p><Button type="button" variant="outline" size="sm" className="mt-2" onClick={() => onChange(namedSignerExamples(policy))}>按当前规则重新填入四类场景</Button><div className="mt-2 max-h-[32rem] space-y-2 overflow-auto">{value.map((item, index) => <div key={index} className="space-y-2 rounded-md border p-3"><div className="grid gap-2 sm:grid-cols-2"><label className="text-sm">阶段<select className={field} value={item.stage} onChange={e => edit(index, { stage: e.target.value })}>{stages.map(s => <option key={s.code} value={s.code}>{s.name}</option>)}</select></label><label className="text-sm">需核对的签核槽位<select className={field} value={item.slot} onChange={e => edit(index, { slot: e.target.value as GateSlot })}>{Object.entries(gateSlots).map(([slot, label]) => <option key={slot} value={slot}>{label}</option>)}</select></label></div><label className="block text-sm">人员条件<select className={field} value={item.scenario} onChange={e => edit(index, { scenario: e.target.value as SignerCase["scenario"] })}>{Object.entries(scenarios).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label className="block text-sm">预期结果<select className={field} value={String(item.expected_valid)} onChange={e => edit(index, { expected_valid: e.target.value === "true" })}><option value="true">允许开启签核轮次</option><option value="false">须补齐分派后再开轮</option></select></label><p className="text-xs">{stageLabel(item.stage)} · {gateSlots[item.slot]}</p><Button type="button" variant="ghost" size="sm" onClick={() => onChange(value.filter((_, n) => n !== index))}>移除此场景</Button></div>)}</div></details>;
}

export function NamedSignerDifference({ value }: { value: unknown }) {
  if (!Array.isArray(value) || !value.length) return null;
  function describe(slots: unknown) { return Array.isArray(slots) && slots.length ? slots.map(s => gateSlots[s as GateSlot] ?? String(s)).join("、") : "无强制具名槽位"; }
  return <div className="space-y-1 text-sm"><p className="font-medium">具名签核要求变化</p>{value.filter(isRecord).map(row => <p key={String(row.stage)}>{String(row.stage)}：{describe(row.before)} → {describe(row.after)}</p>)}</div>;
}

export function NamedSignerResults({ value }: { value: unknown }) {
  if (!isRecord(value)) return null;
  const rows = Array.isArray(value.results) ? value.results.filter(isRecord) : [];
  const missing = Array.isArray(value.missing) ? value.missing.filter(isRecord) : [];
  return <details><summary className="cursor-pointer text-sm font-medium">具名分派演练：{value.passed ? "预期一致且覆盖齐全" : "有预期差异或缺少场景"}</summary><div className="mt-2 max-h-80 space-y-2 overflow-auto text-xs">{rows.map((row, i) => <p key={i}>{String(row.stage)} · {gateSlots[row.slot as GateSlot]} · {scenarios[row.scenario as keyof typeof scenarios]}：实际{row.actual_valid ? "允许开轮" : "阻止开轮"}，{row.matched ? "符合预期" : "不符预期"}{row.problem ? `；${String(row.problem)}` : ""}</p>)}{missing.map((row, i) => <p key={i} className="text-primary">缺少：{String(row.stage)} · {gateSlots[row.slot as GateSlot]} · {scenarios[row.scenario as keyof typeof scenarios]}</p>)}<p>{String(value.scope ?? "")}</p></div></details>;
}
