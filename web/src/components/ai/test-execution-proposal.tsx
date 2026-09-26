"use client";

import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";

export type ExecutionProposal = {
  conditions: string; environment: string; required_sample_count: number | null;
  responsible_role: string; expected_output: string; resource_requirements: string[];
  unresolved: string[]; basis: string;
};
export function validExecutionProposal(value: unknown): value is ExecutionProposal {
  return isRecord(value) && ["conditions", "environment", "responsible_role", "expected_output", "basis"].every(key => typeof value[key] === "string")
    && (value.required_sample_count === null || typeof value.required_sample_count === "number" && Number.isSafeInteger(value.required_sample_count) && value.required_sample_count > 0 && value.required_sample_count <= 100000)
    && ["resource_requirements", "unresolved"].every(key => Array.isArray(value[key]) && value[key].every((item: unknown) => typeof item === "string"));
}
export function executionProposalReady(value: ExecutionProposal) {
  return !!value.basis.trim() && (value.unresolved.length > 0 || !!(value.conditions.trim() && value.environment.trim() && value.expected_output.trim() && value.responsible_role.trim() && value.required_sample_count));
}
const fields = { conditions: "计划测试条件", environment: "环境要求", responsible_role: "建议负责专业", expected_output: "交付要求", basis: "人工补充或核对依据" } as const;
export function TestExecutionProposal({ value, onChange }: { value?: ExecutionProposal | null; onChange?: (value: ExecutionProposal | null) => void }) {
  if (!value) return onChange ? <Button type="button" size="sm" variant="outline" onClick={() => onChange({ conditions: "", environment: "", required_sample_count: null, responsible_role: "", expected_output: "", resource_requirements: [], unresolved: [], basis: "" })}>补充执行准备要求</Button> : null;
  return <details className="space-y-3 rounded-md border p-3" open={!!onChange}>
    <summary className="cursor-pointer font-medium">执行准备要求 · 人工核对</summary>
    <p className="text-xs text-muted-foreground">随接受与独立应用进入新计划。实际负责人、日期、样机和资源预约在执行工作包中明确。</p>
    {Object.entries(fields).map(([key, label]) => <label key={key} className="block text-xs">{label}{onChange ? <textarea className="mt-1 w-full rounded-md border bg-background p-2 text-sm" maxLength={key === "conditions" || key === "expected_output" ? 10000 : key === "responsible_role" ? 128 : 2000} value={value[key as keyof typeof fields]} onChange={event => onChange({ ...value, [key]: event.target.value })} /> : <p className="mt-1 whitespace-pre-wrap">{value[key as keyof typeof fields] || "待补充"}</p>}</label>)}
    <label className="block text-xs">要求样机数量{onChange ? <input className="mt-1 w-full rounded-md border bg-background p-2 text-sm" type="number" min={1} max={100000} step={1} value={value.required_sample_count ?? ""} onChange={event => onChange({ ...value, required_sample_count: event.target.value ? Number(event.target.value) : null })} /> : <p>{value.required_sample_count ?? "待确认"}</p>}</label>
    {(["resource_requirements", "unresolved"] as const).map(key => <label key={key} className="block text-xs">{key === "resource_requirements" ? "资源需求说明（每行一项）" : "执行前待补条件（未知字段须说明）"}{onChange ? <textarea className="mt-1 w-full rounded-md border bg-background p-2 text-sm" value={value[key].join("\n")} onChange={event => onChange({ ...value, [key]: event.target.value.split("\n").filter(line => line.trim()) })} /> : <ul className="list-disc pl-5">{value[key].map((line, index) => <li key={index}>{line}</li>)}</ul>}</label>)}
    {onChange && <Button type="button" size="sm" variant="outline" onClick={() => onChange(null)}>移除此项执行准备补充</Button>}
  </details>;
}
