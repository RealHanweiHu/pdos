"use client";

import { useId, useState, type FormEvent } from "react";
import { FileText } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { locationLabel, type Callbacks, type Context, type Observation, type Research, type SourceOption, type SpecValue } from "./contracts";

const input = "w-full rounded-lg border bg-background px-3 py-2 text-sm";
export function SourceImport({ research, sources, context, callbacks }: {
  research: Research; sources: SourceOption[]; context: Context; callbacks: Callbacks;
}) {
  const id = useId();
  const [selected, setSelected] = useState<string[]>([]);
  const [kind, setKind] = useState<Observation["kind"]>("spec");
  const [valueType, setValueType] = useState<SpecValue["value_type"]>("number");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const available = context.readiness.import && !!callbacks.onImport;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!available || busy) return;
    const form = new FormData(event.currentTarget);
    const picked = sources.filter(source => selected.includes(source.id));
    if (!picked.length) { setError("请选择已有权限且位置已核对的来源。"); return; }
    const nullable = (key: string) => String(form.get(key) ?? "").trim() || null;
    const spec: SpecValue | null = kind === "spec" ? {
      parameter: String(form.get("parameter")), value_type: valueType,
      value: valueType === "number" ? nullable("value") : null,
      lower: valueType === "range" ? nullable("lower") : null,
      upper: valueType === "range" ? nullable("upper") : null,
      text: valueType === "text" ? nullable("text") : null, unit: nullable("unit"),
      tolerance: valueType === "text" ? null : nullable("tolerance"),
      test_conditions: String(form.get("conditions") ?? "").split("\n").filter(value => value.trim()),
      method: nullable("method"), applicability: nullable("applicability"), acceptance_criterion: nullable("criterion"),
    } : null;
    setBusy(true); setError(null);
    try {
      const observation: Observation = { id: crypto.randomUUID(), key: String(form.get("key")), kind,
        origin: "human_observation", raw_text: picked.map(source => source.citation.quote).join("\n"),
        statement: String(form.get("statement")), spec, sources: picked.map(source => source.citation) };
      await callbacks.onImport!(research.id, research.revision, {
        items: picked.map(source => ({ category: source.category, source: source.citation })), observations: [observation],
      });
    } catch (cause) { setError(cause instanceof Error ? cause.message : "导入失败；当前输入保留。"); }
    finally { setBusy(false); }
  }
  const fields = [
    ["parameter", "参数名称"], ...(valueType === "number" ? [["value", "原值"]] : valueType === "range" ? [["lower", "下限"], ["upper", "上限"]] : [["text", "文字目标"]]),
    ["unit", "原单位"], ...(valueType === "text" ? [] : [["tolerance", "原允差"]]),
    ["method", "判定方法"], ["applicability", "适用范围"], ["criterion", "验收准则"],
  ];
  return <section className="space-y-3 rounded-lg border p-4" aria-labelledby={`${id}-heading`}>
    <h2 id={`${id}-heading`} className="flex items-center gap-2 font-semibold"><FileText />来源包与人工观察</h2>
    <p className="text-sm text-muted-foreground">只选择已核验原件版本和精确位置。录入值会逐字段重核，缺失留空；原文不会被替换。</p>
    {!available && <p role="status">{context.unavailableReason ?? "来源导入待主线接入"}</p>}
    {!sources.length && <p role="status">暂无可消费的授权来源；先完成原件登记与安全解析。</p>}
    <form onSubmit={submit} className="space-y-3">
      <fieldset className="space-y-2"><legend className="text-sm font-medium">本条观察的并列证据</legend>
        {sources.map(source => <label key={source.id} className="block rounded-lg border p-3 text-sm">
          <span className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={selected.includes(source.id)}
            onChange={event => setSelected(current => event.target.checked ? [...current, source.id] : current.filter(value => value !== source.id))} />
            {source.label} · {source.category} · v{source.citation.expected_revision} · {locationLabel(source.citation)}</span>
          <span className="block whitespace-pre-wrap break-words text-muted-foreground">{source.citation.quote}</span>
        </label>)}
      </fieldset>
      <label htmlFor={`${id}-kind`} className="block text-sm">观察类型</label>
      <select id={`${id}-kind`} className={input} value={kind} onChange={event => setKind(event.target.value as Observation["kind"])}>
        <option value="spec">规格候选</option><option value="requirement">要求候选</option><option value="constraint">约束候选</option><option value="note">研究观察</option>
      </select>
      <label htmlFor={`${id}-key`} className="block text-sm">稳定参数标识，同参数沿用同标识</label>
      <input id={`${id}-key`} name="key" required pattern="[a-zA-Z0-9_-]+" maxLength={80} className={input} />
      <label htmlFor={`${id}-statement`} className="block text-sm">观察或要求文字</label>
      <textarea id={`${id}-statement`} name="statement" required maxLength={2000} className={input} />
      {kind === "spec" && <>
        <label htmlFor={`${id}-value-type`} className="block text-sm">原值类型</label>
        <select id={`${id}-value-type`} className={input} value={valueType} onChange={event => setValueType(event.target.value as SpecValue["value_type"])}>
          <option value="number">数值</option><option value="range">范围</option><option value="text">文字</option>
        </select>
        <div className="grid gap-3 sm:grid-cols-2">{fields.map(([name, label]) => <label key={name} className="space-y-1 text-sm" htmlFor={`${id}-${name}`}>
          <span>{label}</span><input id={`${id}-${name}`} name={name} required={name === "parameter"} className={input} maxLength={name === "unit" ? 80 : 2000} />
        </label>)}</div>
        <label htmlFor={`${id}-conditions`} className="block text-sm">原测试条件，每行一项</label>
        <textarea id={`${id}-conditions`} name="conditions" className={input} maxLength={30000} />
      </>}
      <Button type="submit" disabled={!available || !sources.length || busy} className="min-h-11">{busy ? "核对中…" : "保存为待核对观察"}</Button>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </form>
  </section>;
}
