"use client";

import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";

export type RiskField = {
  key: string; label: string; label_en: string; help_text: string;
  kind: "text" | "number" | "boolean" | "date" | "choice";
  required_at: "response" | "closed" | null;
  choices: string[]; max_length: number; minimum: number | null; maximum: number | null; unit: string;
};
export const fieldKinds = { text: "文字", number: "数值", boolean: "是/否", date: "日期", choice: "单选" };
export const requiredStages = { response: "进入处理或观察前", closed: "关闭前" };
const control = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

export function RiskFieldsEditor({ value, onChange }: { value: RiskField[]; onChange: (value: RiskField[]) => void }) {
  const edit = (index: number, change: Partial<RiskField>) => onChange(value.map((item, n) => n === index ? { ...item, ...change } : item));
  return (
    <details>
      <summary className="cursor-pointer text-sm font-medium">风险办理的补充字段</summary>
      <p className="mt-2 text-xs text-muted-foreground">用于记录本产品线需要的额外资料。新项目固定采用创建时版本，已有风险的字段和原有必填条件保留。风险可先暂存，进入所选节点前必须补齐；这些字段不会替代负责人、评分、处理方案或原结果核对。</p>
      <div className="mt-3 space-y-3">
        {value.map((item, index) => (
          <details key={index} className="rounded-md border p-3">
            <summary className="cursor-pointer text-sm">{item.label || "新字段"} · {fieldKinds[item.kind]}</summary>
            <div className="mt-3 space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm">字段标识（小写字母、数字和下划线）<input className={control} maxLength={64} value={item.key} onChange={event => edit(index, { key: event.target.value })} /></label>
                <label className="text-sm">字段名称<input className={control} maxLength={200} value={item.label} onChange={event => edit(index, { label: event.target.value })} /></label>
                <label className="text-sm">英文名称<input className={control} maxLength={200} value={item.label_en} onChange={event => edit(index, { label_en: event.target.value })} /></label>
                <label className="text-sm">填写形式<select className={control} value={item.kind} onChange={event => edit(index, { kind: event.target.value as RiskField["kind"], choices: event.target.value === "choice" ? ["选项一", "选项二"] : [], minimum: null, maximum: null, unit: "" })}>{Object.entries(fieldKinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
              </div>
              <label className="block text-sm">填写说明<textarea className={control} maxLength={2000} value={item.help_text} onChange={event => edit(index, { help_text: event.target.value })} /></label>
              <label className="block text-sm">必填时点<select className={control} value={item.required_at ?? ""} onChange={event => edit(index, { required_at: event.target.value as RiskField["required_at"] || null })}><option value="">选填</option>{Object.entries(requiredStages).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
              {item.kind === "text" && <label className="block text-sm">最大字数<input className={control} type="number" min={1} max={5000} step={1} value={item.max_length} onChange={event => edit(index, { max_length: Number(event.target.value) })} /></label>}
              {item.kind === "number" && <div className="grid gap-3 sm:grid-cols-3"><label className="text-sm">最小值（可空）<input type="number" step="any" className={control} value={item.minimum ?? ""} onChange={event => edit(index, { minimum: event.target.value === "" ? null : Number(event.target.value) })} /></label><label className="text-sm">最大值（可空）<input type="number" step="any" className={control} value={item.maximum ?? ""} onChange={event => edit(index, { maximum: event.target.value === "" ? null : Number(event.target.value) })} /></label><label className="text-sm">单位<input className={control} maxLength={50} value={item.unit} onChange={event => edit(index, { unit: event.target.value })} /></label></div>}
              {item.kind === "choice" && <label className="block text-sm">选项（每行一个，最多50个）<textarea className={control} rows={4} value={item.choices.join("\n")} onChange={event => edit(index, { choices: event.target.value.split("\n") })} /></label>}
              <Button type="button" size="sm" variant="ghost" onClick={() => onChange(value.filter((_, n) => n !== index))}>从此候选移除字段</Button>
            </div>
          </details>
        ))}
        <Button type="button" size="sm" variant="outline" disabled={value.length >= 30} onClick={() => onChange([...value, { key: "", label: "", label_en: "", help_text: "", kind: "text", required_at: null, choices: [], max_length: 2000, minimum: null, maximum: null, unit: "" }])}>增加风险补充字段</Button>
      </div>
    </details>
  );
}

export function RiskFieldDifference({ value }: { value: unknown }) {
  if (!Array.isArray(value)) return null;
  const describe = (input: unknown) => {
    if (!isRecord(input)) return "无";
    const item = input as RiskField;
    return `${item.label} (${item.label_en}) · ${fieldKinds[item.kind]} · ${item.required_at ? requiredStages[item.required_at] + "必填" : "选填"}${item.kind === "text" ? ` · 最多${item.max_length}字` : ""}${item.kind === "number" ? ` · ${item.minimum ?? "不限下限"}～${item.maximum ?? "不限上限"} ${item.unit}` : ""}${item.kind === "choice" ? ` · ${item.choices.join("、")}` : ""}${item.help_text ? ` · ${item.help_text}` : ""}`;
  };
  return <>{value.filter(isRecord).map(item => <div key={String(item.key)} className="space-y-1 rounded-md border p-2 text-sm"><p className="font-medium">风险补充字段 · {String(item.key)}</p><p>原：{describe(item.before)}</p><p>新：{describe(item.after)}</p></div>)}</>;
}
