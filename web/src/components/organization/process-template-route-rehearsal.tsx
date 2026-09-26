"use client";

import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import { professionalRoles, type TaskRoutes } from "./process-template-routing";

export type RoutingCase = { name: string; features: Record<string,boolean>; participants: string[]; bindings: Record<string,string>; expected: Record<string,Partial<Record<"owner" | "receiver",string | null>>>; expect_valid: boolean };
export type RoutingTemplate = { features: Record<string,{ default: boolean; label: string }>; tasks: { code: string; title: string }[]; task_routes?: TaskRoutes };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const slots = { owner: "负责人", receiver: "接收人" };
function targets(template: RoutingTemplate) {
  return Object.entries(template.task_routes ?? {}).flatMap(([code,route]) => (Object.keys(slots) as (keyof typeof slots)[]).filter(slot => route[slot]).map(slot => ({ code, slot, role: route[slot]!, title: template.tasks.find(task => task.code === code)?.title ?? code })));
}
export function routingExamples(template: RoutingTemplate): RoutingCase[] {
  const routes = targets(template);
  if (!routes.length) return [];
  const bindings = Object.fromEntries(routes.map(item => [item.role, `模拟${professionalRoles[item.role]}联系人`]));
  const features = Object.fromEntries(Object.keys(template.features).map(key => [key,true]));
  const expected: RoutingCase["expected"] = {}, missing: RoutingCase["expected"] = {};
  for (const item of routes) { expected[item.code] = { ...expected[item.code], [item.slot]: bindings[item.role] }; missing[item.code] = { ...missing[item.code], [item.slot]: null }; }
  return [{ name: "各专业有联系人时准确分派", features, participants: Object.values(bindings), bindings, expected, expect_valid: true }, { name: "缺联系人时保持待指定", features, participants: [], bindings: {}, expected: missing, expect_valid: true }];
}
export function RouteRehearsalEditor({ template, value, onChange }: { template: RoutingTemplate; value: RoutingCase[]; onChange: (value: RoutingCase[]) => void }) {
  const routes = targets(template), roles = Array.from(new Set(routes.map(item => item.role)));
  const edit = (index: number, change: Partial<RoutingCase>) => onChange(value.map((item,n) => index === n ? { ...item, ...change } : item));
  return <details open={routes.length > 0}><summary className="cursor-pointer text-sm font-medium">任务路由演练</summary><p className="mt-2 text-xs text-muted-foreground">使用虚构的联系人标识，检查分派与缺人情况。它不代表真实账号权限、责任确认或任务已派发。</p><Button type="button" size="sm" variant="outline" className="mt-2" onClick={() => onChange(routingExamples(template))}>重新填入有联系人/缺联系人示例（替换本组场景）</Button>
    {value.map((item,index) => <div key={index} className="mt-3 space-y-3 rounded-md border p-3"><label className="block text-sm">场景名称<input className={field} maxLength={200} value={item.name} onChange={event => edit(index,{ name: event.target.value })}/></label><div className="flex flex-wrap gap-3">{Object.entries(template.features).map(([key,feature]) => <label key={key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={item.features[key] ?? feature.default} onChange={event => edit(index,{ features: { ...item.features,[key]: event.target.checked } })}/>{feature.label}</label>)}</div><label className="block text-sm">模拟参与人标识（每行一个，不填真实账号）<textarea className={field} rows={3} maxLength={3030} value={item.participants.join("\n")} onChange={event => edit(index,{ participants: event.target.value.split("\n") })}/></label><div className="grid gap-3 sm:grid-cols-2">{roles.map(role => <label key={role} className="text-sm">{professionalRoles[role]}联系人<select className={field} value={item.bindings[role] ?? ""} onChange={event => { const next={ ...item.bindings }; if(event.target.value) next[role]=event.target.value; else delete next[role]; edit(index,{ bindings: next }); }}><option value="">未指定</option>{Array.from(new Set([...item.participants.filter(Boolean),...(item.bindings[role] ? [item.bindings[role]] : [])])).map(person => <option key={person} value={person}>{person}</option>)}</select></label>)}</div><details open><summary className="cursor-pointer text-sm">预期分派结果</summary><div className="mt-2 max-h-80 space-y-2 overflow-auto">{routes.map(route => <label key={`${route.code}:${route.slot}`} className="block text-sm">{route.title} · {slots[route.slot]}<select className={field} value={item.expected[route.code]?.[route.slot] === null ? "missing" : item.expected[route.code]?.[route.slot] === undefined ? "skip" : `person:${item.expected[route.code][route.slot]}`} onChange={event => { const expected={ ...item.expected, [route.code]: { ...item.expected[route.code] } }; if(event.target.value === "skip") delete expected[route.code][route.slot]; else expected[route.code][route.slot]=event.target.value === "missing" ? null : event.target.value.slice(7); if(!Object.keys(expected[route.code]).length) delete expected[route.code]; edit(index,{ expected }); }}><option value="skip">本场景不判断此项</option><option value="missing">应保持待指定</option>{Array.from(new Set([...item.participants.filter(Boolean),...(typeof item.expected[route.code]?.[route.slot] === "string" ? [item.expected[route.code][route.slot]!] : [])])).map(person => <option key={person} value={`person:${person}`}>应交给 {person}</option>)}</select></label>)}</div></details><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!item.expect_valid} onChange={event => edit(index,{ expect_valid: !event.target.checked })}/>本场景应拒绝无效的分派输入</label><Button type="button" size="sm" variant="ghost" onClick={() => onChange(value.filter((_,n) => n !== index))}>移除此场景</Button></div>)}
    <Button type="button" size="sm" variant="outline" className="mt-2" disabled={value.length >= 20} onClick={() => onChange([...value,{ name: "新路由场景", features: {}, participants: [], bindings: {}, expected: {}, expect_valid: true }])}>增加路由场景</Button>
  </details>;
}
export function normalizedRoutingCases(cases: RoutingCase[]): RoutingCase[] {
  return cases.map(item => ({ ...item, participants: item.participants.map(person => person.trim()).filter(Boolean) }));
}
type Row = Record<string,unknown>;
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const obj = (value: unknown): Row => isRecord(value) ? value : {};
const text = (value: unknown) => value == null ? "待指定" : String(value);
export function RouteRehearsalResults({ value }: { value: unknown }) {
  if (!isRecord(value)) return null;
  return <details open className="rounded-md border p-3"><summary className="cursor-pointer text-sm font-medium">路由演练：{value.passed ? "预期相符" : "尚未满足发布条件"}</summary>{rows(value.cases).map((item,index) => <div key={index} className="mt-3 text-sm"><p>{text(item.name)} · {item.passed ? "预期相符" : "预期不符或缺少判断"}</p>{!!item.error && <p>{text(item.error)}</p>}<details className="text-xs text-muted-foreground"><summary className="cursor-pointer">本场景的模拟输入</summary><p>参与人：{Array.isArray(obj(item.inputs).participants) ? (obj(item.inputs).participants as string[]).join("、") || "无" : "无"}</p><p>职责绑定：{Object.entries(obj(obj(item.inputs).bindings)).map(([role,person]) => `${professionalRoles[role] ?? role} → ${text(person)}`).join("；") || "未指定"}</p><p>功能条件：{Object.entries(obj(obj(item.inputs).features)).map(([key,enabled]) => `${key}：${enabled ? "具有" : "不具有"}`).join("；") || "模板默认条件"}</p></details>{rows(item.checks).map((check,n) => <p key={n} className="text-xs">{text(check.node_key)} · {slots[check.slot as keyof typeof slots]}（{professionalRoles[String(check.responsibility)]}）：预期{text(check.expected_user)}，计算{text(check.user_id)}</p>)}</div>)}{rows(value.coverage).map(item => <p key={`${text(item.node_key)}:${text(item.slot)}`} className="mt-2 text-xs">{text(item.node_key)} · {slots[item.slot as keyof typeof slots]}：有联系人{item.positive ? "已覆盖" : "缺失"}，缺联系人{item.missing_contact ? "已覆盖" : "缺失"}</p>)}<p className="mt-3 text-xs text-muted-foreground">{text(value.scope)}</p></details>;
}
