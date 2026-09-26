"use client";
import { type TaskField, requiredStages as taskRequiredStages } from "@/components/organization/process-template-task-fields";

import { useState } from "react";
import { requiredStages, fieldKinds, type IssueField } from "@/components/organization/process-template-fields";
import { ReminderPolicySummary, type ReminderPolicy } from "@/components/organization/process-template-reminders";
import { gateSlots, gateRequirements, type GateRequirements, type GateSlot } from "@/components/organization/process-template-gates";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

export type CreationTemplate = { template_id: string; version: number; features: Record<string, boolean>; language: "zh-CN" | "en"; reason: string };
type Template = { risk_fields?: { key: string; label: string; required_at: "response" | "closed" | null }[]; named_gate_slots?: Record<string, GateSlot[]>; task_fields?: TaskField[]; issue_fields?: IssueField[]; approval_routes?: Record<string, Partial<Record<GateSlot, GateSlot[]>>>; reminder_policy: ReminderPolicy; gate_requirements: GateRequirements; id: string; version: number; name: string; features: Record<string, { label: string; default: boolean }>; stages: { code: string; name: string; name_en: string; description?: string }[] };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
export function CaseProjectTemplatePicker({ busy, value, onChange }: { busy: boolean; value: CreationTemplate | null; onChange: (value: CreationTemplate | null) => void }) {
  const [items, setItems] = useState<Template[] | null>(null), [loading, setLoading] = useState(false), [error, setError] = useState("");
  const selected = items?.find(item => item.id === value?.template_id && item.version === value.version);
  async function load() {
    setLoading(true); setError("");
    try {
      const response = await fetch("/api/projects/creation-templates", { cache: "no-store" });
      const body: unknown = await responseBody(response);
      if (!response.ok || !isRecord(body) || !Array.isArray(body.items)) throw new Error("可用模板暂未加载，请稍后重试。");
      setItems(body.items as Template[]);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "模板加载失败"); }
    finally { setLoading(false); }
  }
  return <fieldset disabled={busy || loading} className="space-y-3 rounded-md border p-3">
    <legend className="px-1 text-sm font-medium">创建时采用的流程</legend>
    <p className="text-xs text-muted-foreground">默认使用标准 NPD 七阶段；可选已发布产品模板，创建时保存版本，后续发布不自动更改本项目。</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <Button type="button" size="sm" variant="outline" onClick={() => void load()}>{loading ? "正在加载…" : items ? "刷新可用模板" : "选择产品或组织模板"}</Button>
    {items && <label className="block text-sm">产品流程模板<select className={field} value={value ? `${value.template_id}:${value.version}` : ""} onChange={event => {
      const item = items.find(item => `${item.id}:${item.version}` === event.target.value);
      onChange(item ? { template_id: item.id, version: item.version, features: Object.fromEntries(Object.entries(item.features).map(([key, feature]) => [key, feature.default])), language: "zh-CN", reason: `创建项目时采用 ${item.name} v${item.version}` } : null);
    }}><option value="">标准 NPD 七阶段（暂不采用产品模板）</option>{items.map(item => <option key={`${item.id}:${item.version}`} value={`${item.id}:${item.version}`}>{item.name} · v{item.version}</option>)}</select></label>}
    {value && !selected && items && <p role="alert" className="text-sm text-destructive">原选版本已不在当前发布库，请重新选择后提交。</p>}
    {selected && value && <>
      <div className="flex flex-wrap gap-3">{Object.entries(selected.features).map(([key, feature]) => <label className="flex items-center gap-2 text-sm" key={key}><input type="checkbox" checked={value.features[key] ?? feature.default} onChange={event => onChange({ ...value, features: { ...value.features, [key]: event.target.checked } })}/>{feature.label}</label>)}</div>
      <label className="block text-sm">项目阶段显示语言<select className={field} value={value.language} onChange={event => onChange({ ...value, language: event.target.value as "zh-CN" | "en" })}><option value="zh-CN">中文</option><option value="en">English</option></select></label>
      <ol className="list-decimal space-y-1 pl-5 text-sm">{selected.stages.map(stage => <li key={stage.code}>{value.language === "en" ? stage.name_en : stage.name}{stage.description && <p className="whitespace-pre-wrap text-xs text-muted-foreground">{stage.description}</p>}</li>)}</ol>
      <details><summary className="cursor-pointer text-sm">同时采用的阶段签核要求</summary><div className="mt-2 space-y-2">{selected.stages.map(stage => <p key={stage.code} className="text-xs">{stage.name}：{(Object.keys(gateSlots) as GateSlot[]).map(slot => `${gateSlots[slot]}${gateRequirements[selected.gate_requirements[stage.code][slot]]}`).join("；")}</p>)}</div></details>
      {Boolean(selected.risk_fields?.length) && <details><summary className="cursor-pointer text-sm">风险办理的补充资料</summary><div className="mt-2 space-y-1 text-xs">{selected.risk_fields?.map(field => <p key={field.key}>{field.label}：{field.required_at === "response" ? "进入处理或观察前必填" : field.required_at === "closed" ? "关闭前必填" : "选填"}。</p>)}<p>固定采用创建版，原责任、评分和处理要求保留。</p></div></details>}
      {selected.named_gate_slots && Object.keys(selected.named_gate_slots).length > 0 && <details><summary className="cursor-pointer text-sm">必须具名的阶段签核</summary><div className="mt-2 space-y-1 text-xs">{Object.entries(selected.named_gate_slots).map(([stage, slots]) => <p key={stage}>{selected.stages.find(item => item.code === stage)?.name ?? stage}：{slots.map(slot => gateSlots[slot]).join("、")}须指定实际签核人。</p>)}<p>本项目将固定此版要求；每次开轮时选择有权限的当前项目成员。</p></div></details>}
      {selected.approval_routes && Object.keys(selected.approval_routes).length > 0 && <details><summary className="cursor-pointer text-sm">同时采用的签核先后依赖</summary><div className="mt-2 space-y-1 text-xs">{Object.entries(selected.approval_routes).flatMap(([stage, routes]) => Object.entries(routes).map(([slot, priors]) => <p key={`${stage}:${slot}`}>{selected.stages.find(item => item.code === stage)?.name ?? stage}：{gateSlots[slot as GateSlot]}等待{priors.map(prior => gateSlots[prior]).join("、")}签核。</p>))}<p>上游修改后，下游需重新确认；原签核权限保留。</p></div></details>}
      {Boolean(selected.task_fields?.length) && <details><summary className="cursor-pointer text-sm">任务办理需要的补充资料</summary><div className="mt-2 space-y-1 text-xs">{selected.task_fields?.map(item => <p key={item.key}>{item.label} · {fieldKinds[item.kind]} · {item.required_at ? `${taskRequiredStages[item.required_at]}必填` : "选填"}</p>)}</div></details>}
      {Boolean(selected.issue_fields?.length) && <details><summary className="cursor-pointer text-sm">问题办理需要的补充资料</summary><div className="mt-2 space-y-1 text-xs">{selected.issue_fields?.map(item => <p key={item.key}>{item.label} · {fieldKinds[item.kind]} · {item.required_at ? `${requiredStages[item.required_at]}必填` : "选填"}</p>)}</div></details>}
      <ReminderPolicySummary value={selected.reminder_policy}/>
      <label className="block text-sm">采用说明<textarea className={field} required maxLength={5000} value={value.reason} onChange={event => onChange({ ...value, reason: event.target.value })}/></label>
      <p className="text-xs text-muted-foreground">提交创建即确认采用以上版本与功能。任务、测试计划和正式基线仍分别按其办理流程生成。</p>
    </>}
  </fieldset>;
}
