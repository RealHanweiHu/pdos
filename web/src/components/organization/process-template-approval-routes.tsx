"use client";

import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import { gateSlots, type GateSlot, type GateStatus, type GateRequirements } from "./process-template-gates";

export type ApprovalRoutes = Record<string, Partial<Record<GateSlot, GateSlot[]>>>;
export type ApprovalCase = { name: string; stage: string; slot: GateSlot; signoffs: Partial<Record<GateSlot, GateStatus>>; expected_allowed: boolean };
type Stage = { code: string; name: string };
const slots = Object.keys(gateSlots) as GateSlot[];
const statuses: Record<GateStatus, string> = { pending: "待签核", approved: "批准", conditional: "有条件批准", rejected: "拒绝", not_applicable: "不适用" };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

export function ApprovalRoutesEditor({ stages, requirements, value, onChange }: {
  stages: Stage[]; requirements: GateRequirements; value: ApprovalRoutes; onChange: (value: ApprovalRoutes) => void;
}) {
  return (
    <details>
      <summary className="cursor-pointer text-sm font-medium">阶段签核的先后依赖</summary>
      <p className="mt-2 text-xs text-muted-foreground">勾选必须先满足的专业签核。未配置时可分别办理；先后依赖不能循环，双方均须适用。新项目采用创建时版本，签核权限仍按原职责核验。上游修改后，下游已签结果回到待确认，原签核保留在审计记录中。</p>
      <div className="mt-3 space-y-3">
        {stages.map(stage => (
          <div key={stage.code} className="rounded-md border p-3">
            <p className="text-sm font-medium">{stage.name}</p>
            <div className="mt-2 space-y-2">
              {slots.map(slot => (
                <div key={slot} className="flex flex-wrap gap-3 text-sm">
                  <span>{gateSlots[slot]}签核之前：</span>
                  {slots.filter(prior => prior !== slot).map(prior => {
                    const selected = value[stage.code]?.[slot]?.includes(prior) ?? false;
                    const applicable = requirements[stage.code]?.[slot] !== "not_applicable" && requirements[stage.code]?.[prior] !== "not_applicable";
                    return <label key={prior} className="flex items-center gap-2"><input type="checkbox" checked={selected} disabled={!selected && !applicable} onChange={event => onChange({ ...value, [stage.code]: { ...value[stage.code], [slot]: event.target.checked ? [...(value[stage.code]?.[slot] ?? []), prior] : (value[stage.code]?.[slot] ?? []).filter(item => item !== prior) } })} />先完成{gateSlots[prior]}{!applicable ? "（当前不适用）" : ""}</label>;
                  })}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}

export function approvalExamples(routes: ApprovalRoutes, requirements: GateRequirements): ApprovalCase[] {
  const cases: ApprovalCase[] = [];
  for (const [stage, targets] of Object.entries(routes)) {
    for (const slot of slots) {
      const priors = targets[slot] ?? [];
      if (!priors.length) continue;
      const signoffs = Object.fromEntries(slots.map(key => [key, requirements[stage][key] === "not_applicable" ? "not_applicable" : "approved"])) as Record<GateSlot, GateStatus>;
      cases.push({ name: `${stage} ${gateSlots[slot]}前置满足`, stage, slot, signoffs, expected_allowed: true });
      for (const prior of priors) cases.push({ name: `${stage} ${gateSlots[slot]}等待${gateSlots[prior]}`, stage, slot, signoffs: { ...signoffs, [prior]: "pending" }, expected_allowed: false });
    }
  }
  return cases;
}

export function ApprovalRehearsalEditor({ stages, value, onChange }: { stages: Stage[]; value: ApprovalCase[]; onChange: (value: ApprovalCase[]) => void }) {
  const edit = (index: number, change: Partial<ApprovalCase>) => onChange(value.map((item, n) => n === index ? { ...item, ...change } : item));
  return (
    <details>
      <summary className="cursor-pointer text-sm font-medium">签核先后依赖演练</summary>
      <p className="mt-2 text-xs text-muted-foreground">每条依赖需覆盖前置满足，以及仅这项前置未满足的情况。示例预期可独立修改；正式签核人员权限和过闸业务证据仍由实际办理核验。</p>
      <div className="mt-3 space-y-3">
        {value.map((item, index) => (
          <details key={index} className="rounded-md border p-3">
            <summary className="cursor-pointer text-sm">{item.name}</summary>
            <div className="mt-2 space-y-3">
              <label className="block text-sm">场景名称<input className={field} maxLength={200} value={item.name} onChange={event => edit(index, { name: event.target.value })} /></label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm">阶段<select className={field} value={item.stage} onChange={event => edit(index, { stage: event.target.value })}>{stages.map(stage => <option key={stage.code} value={stage.code}>{stage.name}</option>)}</select></label>
                <label className="text-sm">准备办理的签核<select className={field} value={item.slot} onChange={event => edit(index, { slot: event.target.value as GateSlot })}>{slots.map(slot => <option key={slot} value={slot}>{gateSlots[slot]}</option>)}</select></label>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">{slots.map(slot => <label key={slot} className="text-sm">当前{gateSlots[slot]}状态<select className={field} value={item.signoffs[slot] ?? "pending"} onChange={event => edit(index, { signoffs: { ...item.signoffs, [slot]: event.target.value as GateStatus } })}>{Object.entries(statuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>)}</div>
              <label className="block text-sm">预期先后条件<select className={field} value={String(item.expected_allowed)} onChange={event => edit(index, { expected_allowed: event.target.value === "true" })}><option value="true">满足，可继续签核</option><option value="false">不满足，应等待前置</option></select></label>
              <Button type="button" variant="ghost" size="sm" onClick={() => onChange(value.filter((_, n) => n !== index))}>移除此场景</Button>
            </div>
          </details>
        ))}
        <Button type="button" size="sm" variant="outline" disabled={value.length >= 100} onClick={() => onChange([...value, { name: "新签核依赖场景", stage: stages[0].code, slot: "product", signoffs: {}, expected_allowed: false }])}>增加场景</Button>
      </div>
    </details>
  );
}

export function ApprovalRouteDifference({ value }: { value: unknown }) {
  if (!Array.isArray(value)) return null;
  const describe = (input: unknown) => isRecord(input) ? Object.entries(input).filter(([, priors]) => Array.isArray(priors) && priors.length).map(([slot, priors]) => `${gateSlots[slot as GateSlot]}等待${(priors as GateSlot[]).map(prior => gateSlots[prior]).join("、")}`).join("；") || "分别办理，无先后依赖" : "分别办理，无先后依赖";
  return <>{value.filter(isRecord).map(item => <p key={String(item.stage)} className="text-sm">{String(item.stage)} 签核顺序：{describe(item.before)} → {describe(item.after)}</p>)}</>;
}

export function ApprovalRehearsalResults({ value }: { value: unknown }) {
  if (!isRecord(value)) return null;
  const rows = (input: unknown) => Array.isArray(input) ? input.filter(isRecord) : [];
  return (
    <div className="space-y-2 rounded-md border p-3 text-sm">
      <p className="font-medium">签核先后演练：{value.passed ? "预期相符" : "预期不符或覆盖不全"}</p>
      <p className="text-xs text-muted-foreground">{String(value.scope ?? "")}</p>
      {rows(value.coverage).map((item, index) => <p key={index} className="text-xs">{String(item.stage)} · {gateSlots[item.slot as GateSlot]}等待{gateSlots[item.prior as GateSlot]}：满足{item.positive ? "已覆盖" : "缺失"}，缺前置{item.negative ? "已覆盖" : "缺失"}</p>)}
      {rows(value.cases).map((item, index) => <div key={index}><p>{String(item.name)} · {item.passed ? "相符" : "不符"}；实际{item.valid ? item.allowed ? "可继续签核" : `等待${(item.blockers as GateSlot[]).map(slot => gateSlots[slot]).join("、")}` : "未引用已配置的签核依赖"}</p>{Array.isArray(item.invalidated_on_change) && item.invalidated_on_change.length > 0 && <p className="text-xs text-muted-foreground">此签核修改后，{(item.invalidated_on_change as GateSlot[]).map(slot => gateSlots[slot]).join("、")}需重新确认。</p>}</div>)}
    </div>
  );
}
