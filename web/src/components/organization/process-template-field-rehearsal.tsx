"use client";

import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import type { IssueField } from "./process-template-fields";

type Scalar = string | number | boolean | null;
export type FieldCase = {
  name: string; status: "open" | "analysis" | "action" | "verification" | "closed";
  values: Record<string, Scalar>; expected_valid: boolean; expected_error_field: string | null;
};
const statuses = { open: "暂存问题", analysis: "进入分析", action: "进入行动", verification: "提交验证", closed: "关闭问题" };
const control = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

export function fieldExamples(fields: IssueField[]): FieldCase[] {
  if (!fields.length) return [];
  const values: Record<string, Scalar> = {};
  for (const item of fields) {
    values[item.key] = item.kind === "number" ? item.minimum ?? Math.min(0, item.maximum ?? 0) : item.kind === "boolean" ? false : item.kind === "date" ? "2026-01-10" : item.kind === "choice" ? item.choices[0] : "模拟资料".slice(0, item.max_length);
  }
  const cases: FieldCase[] = [
    { name: "资料齐全时满足字段要求", status: "closed", values, expected_valid: true, expected_error_field: null },
    { name: "问题可先暂存再补齐", status: "open", values: {}, expected_valid: true, expected_error_field: null },
  ];
  for (const item of fields) {
    cases.push({ name: `${item.label}格式不符`.slice(0, 200), status: "closed", values: { ...values, [item.key]: ["number", "boolean"].includes(item.kind) ? "非数值" : 123 }, expected_valid: false, expected_error_field: item.key });
    if (item.required_at) cases.push({ name: `办理前缺少${item.label}`.slice(0, 200), status: item.required_at, values: Object.fromEntries(Object.entries(values).filter(([key]) => key !== item.key)), expected_valid: false, expected_error_field: item.key });
  }
  return cases;
}

export function FieldRehearsalEditor({ fields, value, onChange }: { fields: IssueField[]; value: FieldCase[]; onChange: (value: FieldCase[]) => void }) {
  const edit = (index: number, change: Partial<FieldCase>) => onChange(value.map((item, n) => n === index ? { ...item, ...change } : item));
  return (
    <details>
      <summary className="cursor-pointer text-sm font-medium">问题补充资料的填写演练</summary>
      <p className="mt-2 text-xs text-muted-foreground">每项字段核对正确值与单项格式错误；必填项另核对“可先暂存”和“到办理节点缺项会拦截”。可故意选择不同填写类型演练错误输入；预期由你独立核对。示例不代表实际问题已流转或验收通过。</p>
      <div className="mt-3 space-y-3">
        {value.map((item, index) => (
          <details key={index} className="rounded-md border p-3">
            <summary className="cursor-pointer text-sm">{item.name || `场景${index + 1}`}</summary>
            <div className="mt-3 space-y-3">
              <label className="block text-sm">场景名称<input className={control} maxLength={200} value={item.name} onChange={event => edit(index, { name: event.target.value })} /></label>
              <label className="block text-sm">办理节点<select className={control} value={item.status} onChange={event => edit(index, { status: event.target.value as FieldCase["status"] })}>{Object.entries(statuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
              {[...new Set([...fields.map(field => field.key), ...Object.keys(item.values)])].map(key => {
                const current = item.values[key];
                const kind = current == null ? "missing" : typeof current;
                const change = (next: Scalar) => edit(index, { values: { ...item.values, [key]: next } });
                return (
                  <div key={key} className="grid gap-2 rounded-md border p-2 sm:grid-cols-2">
                    <label className="text-xs">{fields.find(field => field.key === key)?.label || key} · 模拟填写类型<select className={control} value={kind} onChange={event => change(event.target.value === "missing" ? null : event.target.value === "boolean" ? false : event.target.value === "number" ? 0 : "模拟资料")}><option value="missing">未填写</option><option value="string">文字/日期/选项</option><option value="number">数值</option><option value="boolean">是/否</option></select></label>
                    {kind === "boolean" ? <label className="text-xs">模拟值<select className={control} value={String(current)} onChange={event => change(event.target.value === "true")}><option value="true">是</option><option value="false">否</option></select></label> : kind !== "missing" ? <label className="text-xs">模拟值<input className={control} type={kind === "number" ? "number" : "text"} step={kind === "number" ? "any" : undefined} maxLength={6000} value={String(current)} onChange={event => change(kind === "number" ? event.target.value === "" ? null : Number(event.target.value) : event.target.value)} /></label> : <p className="self-center text-xs text-muted-foreground">本场景不填写此项。</p>}
                  </div>
                );
              })}
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm">预期字段检查<select className={control} value={String(item.expected_valid)} onChange={event => edit(index, { expected_valid: event.target.value === "true", expected_error_field: event.target.value === "true" ? null : item.expected_error_field })}><option value="true">应满足字段要求</option><option value="false">应提示补齐或修正</option></select></label>
                {!item.expected_valid && <label className="text-sm">预期指出的问题字段<select className={control} value={item.expected_error_field ?? ""} onChange={event => edit(index, { expected_error_field: event.target.value || null })}><option value="">非单项错误 / 未指定</option>{fields.map(field => <option key={field.key} value={field.key}>{field.label}</option>)}</select></label>}
              </div>
              <Button type="button" size="sm" variant="ghost" onClick={() => onChange(value.filter((_, n) => n !== index))}>移除此场景</Button>
            </div>
          </details>
        ))}
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="outline" onClick={() => onChange(fieldExamples(fields))}>以当前字段示例替换演练场景</Button>
          <Button type="button" size="sm" variant="outline" disabled={value.length >= 100} onClick={() => onChange([...value, { name: "新填写场景", status: "open", values: {}, expected_valid: true, expected_error_field: null }])}>增加场景</Button>
        </div>
      </div>
    </details>
  );
}

export function FieldRehearsalResults({ value }: { value: unknown }) {
  if (!isRecord(value)) return null;
  const rows = (input: unknown) => Array.isArray(input) ? input.filter(isRecord) : [];
  const labels = Object.fromEntries(rows(value.coverage).map(item => [String(item.key), String(item.label)]));
  return (
    <div className="space-y-2 rounded-md border p-3 text-sm">
      <p className="font-medium">补充字段演练：{value.passed ? "预期相符" : "预期不符或覆盖不全"}</p>
      <p className="text-xs text-muted-foreground">{String(value.scope ?? "")}</p>
      {rows(value.coverage).map(item => <p key={String(item.key)} className="text-xs">{String(item.label)}：正确填写{item.positive ? "已覆盖" : "缺失"}，格式错误{item.invalid ? "已覆盖" : "缺失"}{item.required ? `，必填缺项${item.missing ? "已覆盖" : "缺失"}，可先暂存${item.draft ? "已覆盖" : "缺失"}` : ""}</p>)}
      {rows(value.cases).map((item, index) => <details key={index}><summary className="cursor-pointer">{String(item.name)} · {item.passed ? "相符" : "不符"}</summary><div className="mt-2 space-y-1 text-xs"><p>实际：{item.valid ? "满足补充字段要求" : String(item.error ?? "需修正")}</p>{isRecord(item.inputs) && <p>预期：{item.inputs.expected_valid ? "满足字段要求" : `提示修正${labels[String(item.inputs.expected_error_field)] ?? "输入"}`}</p>}{isRecord(item.normalized) && Object.entries(item.normalized).map(([key, answer]) => <p key={key}>{labels[key] ?? key}：{typeof answer === "boolean" ? answer ? "是" : "否" : String(answer)}</p>)}</div></details>)}
    </div>
  );
}
