"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { browserApi } from "@/lib/browser-api";

type Product = { id: string; name: string };
type Parameter = {
  parameter_id: string; version: number; key: string; name: string;
  value_type: "number" | "range" | "text" | "boolean" | "enum";
  unit: string | null; standard_condition: string | null; enum_values: string[] | null;
};
type Requirement = {
  id: string; parameter: string; mode: "exact" | "min" | "max" | "between";
  value: string; second: string; unit: string; condition: string; tests: string;
};
type Check = {
  requirement_index: number; status: "meets" | "differs" | "unknown"; reasons: string[];
  observation: { value: string | boolean | null; lower: string | null; upper: string | null;
    text_value: string | null; unit: string | null; evidence_label: string;
    source_refs: { type: string; id: string; version: number }[] } | null;
};
type MatchResult = {
  as_of: string; requirements: { parameter: string }[];
  products: { product_id: string; name: string; definition_revision: number | null;
    status: "has_differences" | "needs_review" | "selected_specs_meet";
    counts: { meets: number; differs: number; unknown: number }; checks: Check[] }[];
};
const statusLabels = { meets: "满足", differs: "存在差异", unknown: "待核对" };
const productLabels = { has_differences: "存在规格差异", needs_review: "仍有待核对项", selected_specs_meet: "所选规格满足" };
const reasonLabels: Record<string, string> = {
  published_definition_required: "尚无可用的已发布定义", requirement_unknown: "客户要求尚未明确",
  requirement_expert_pending: "客户要求待专家核对", unit_missing: "客户单位未知", unit_differs: "单位与字典不同",
  condition_missing: "客户工况未知", different_parameter_or_conditions: "参数版本、单位或工况不同",
  spec_missing: "该型号未提供此规格", source_unavailable: "来源当前不可用", unmapped_parameter: "参数尚未映射",
  outside_required_bounds: "型号值不在要求范围内", partially_overlapping_bounds: "范围仅部分重叠，不能确定满足",
  value_differs: "值与客户要求不同", multiple_spec_values: "同一口径下有多个值，请核对",
  applicability_requires_review: "适用范围或例外需人工核对", prohibition_requires_review: "禁止性要求需人工核对",
  value_type_mismatch: "值类型不同", enum_value_unmapped: "选项不在字典内", spec_not_comparable: "规格目前不可比",
  unknown: "型号值未知", conflicted: "型号值有冲突", not_applicable: "此型号标记为不适用",
  value_missing_or_invalid: "型号值缺失或格式不完整",
  verification_basis_differs: "验证方法或判据不同", range_tolerance_requires_review: "范围规格的允差需人工核对",
  newer_definition_unavailable: "较新定义当前不可用，请核对历史版本",
};
const fieldClass = "min-w-0 w-full rounded-md border border-input bg-background px-3 py-2 text-sm";
function blank(): Requirement {
  return { id: crypto.randomUUID(), parameter: "", mode: "exact", value: "", second: "", unit: "", condition: "", tests: "" };
}
function parameterKey(item: Parameter) { return `${item.parameter_id}:${item.version}`; }
function valueLabel(value: string | boolean): string {
  if (typeof value === "boolean") return value ? "是" : "否";
  return /^-?\d+\.\d+$/.test(value) ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
}
function observed(check: Check): string {
  const value = check.observation;
  if (!value) return "无同口径值";
  const display = value.value !== null ? valueLabel(value.value) : value.text_value !== null ? value.text_value
    : value.lower !== null || value.upper !== null ? `${value.lower === null ? "不限" : valueLabel(value.lower)} ～ ${value.upper === null ? "不限" : valueLabel(value.upper)}` : "未知";
  return `${display}${value.unit ? ` ${value.unit}` : ""} · ${value.evidence_label}`;
}

export function StandardMatch({ categoryId, products, api, onOpenProduct }: {
  categoryId: string; products: Product[]; api: typeof browserApi; onOpenProduct: (id: string) => void;
}) {
  const prefix = useId();
  const [parameters, setParameters] = useState<Parameter[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [reload, setReload] = useState(0);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<MatchResult | null>(null);
  const generation = useRef(0);
  useEffect(() => () => { generation.current += 1; }, []);

  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true); setLoadError("");
      try {
        const all: Parameter[] = [];
        let cursor: string | null = null;
        do {
          const page: { items: Parameter[]; next_cursor: string | null } = await api(
            `v1/categories/${categoryId}/parameters?page_size=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
          );
          all.push(...page.items); cursor = page.next_cursor;
        } while (cursor && active);
        if (active) setParameters(all);
      } catch (failure) { if (active) setLoadError((failure as Error).message); }
      finally { if (active) setLoading(false); }
    }
    void load();
    return () => { active = false; };
  }, [api, categoryId, reload]);

  function change(id: string, values: Partial<Requirement>) {
    generation.current += 1; setResult(null); setError("");
    setRequirements(rows => rows.map(row => row.id === id ? { ...row, ...values } : row));
  }
  async function compare(event: React.FormEvent) {
    event.preventDefault();
    const ticket = ++generation.current;
    setBusy(true); setError(""); setResult(null);
    try {
      const specs = requirements.map(row => {
        const parameter = parameters.find(item => parameterKey(item) === row.parameter);
        if (!parameter) throw new Error("请为每一条要求选择规格参数。");
        const numeric = ["number", "range"].includes(parameter.value_type);
        const known = row.value.trim() !== "" && (!numeric || row.mode !== "between" || row.second.trim() !== "");
        return {
          key: parameter.key, parameter: parameter.name, parameter_id: parameter.parameter_id,
          parameter_version: parameter.version, value_type: parameter.value_type,
          availability: known ? "known" : "unknown", item_status: "unknown", nature: "decided",
          unit: numeric ? row.unit.trim() || null : parameter.unit,
          condition_note: row.condition.trim() || null,
          test_conditions: row.tests.split("\n").map(value => value.trim()).filter(Boolean),
          ...(known ? numeric ? row.mode === "exact" && parameter.value_type === "number" ? { value: row.value }
            : row.mode === "min" ? { lower: row.value } : row.mode === "max" ? { upper: row.value }
            : { lower: row.value, upper: row.mode === "exact" ? row.value : row.second }
            : { text_value: row.value } : {}),
        };
      });
      const next = await api<MatchResult>(`v1/categories/${categoryId}/standard-match`, { product_ids: selected, requirements: specs });
      if (ticket === generation.current) setResult(next);
    } catch (failure) { if (ticket === generation.current) setError((failure as Error).message); }
    finally { if (ticket === generation.current) setBusy(false); }
  }

  return <section className="panel mb-6" aria-label="标准品匹配">
    <h2 className="font-semibold">先核对现有型号</h2>
    <p className="subtle mt-2">只核对所选规格。全部满足且确认没有开发活动时，回到 CRM 办理报价与沟通，无需立项。</p>
    <details className="mt-4">
      <summary className="cursor-pointer text-sm font-medium">核对标准品规格</summary>
      {loading ? <p role="status" className="subtle mt-3">正在读取规格字典…</p> : loadError ? <div role="alert" className="mt-3"><p>{loadError}</p><Button variant="outline" onClick={() => setReload(value => value + 1)}>重新读取字典</Button></div>
        : !parameters.length ? <p className="subtle mt-3">请先在规格字典登记参数，再按同一参数版本核对。</p>
        : !products.length ? <p className="subtle mt-3">当前品类还没有可核对的型号。</p>
        : <form className="mt-4 space-y-4" onSubmit={compare}>
          <fieldset disabled={busy} className="space-y-4">
            <legend className="text-sm font-medium">选择现有型号</legend>
            <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">{products.map(product => <label key={product.id} className="standard-match-product"><input type="checkbox" checked={selected.includes(product.id)} onChange={event => {
              setResult(null); setError(""); setSelected(ids => event.target.checked ? [...ids, product.id] : ids.filter(id => id !== product.id));
            }}/>{product.name}</label>)}</div>
            {requirements.map((row, index) => {
              const parameter = parameters.find(item => parameterKey(item) === row.parameter);
              const numeric = parameter && ["number", "range"].includes(parameter.value_type);
              const rowId = `${prefix}-${row.id}`;
              return <div key={row.id} className="space-y-3 rounded-md border border-border p-3">
                <div className="flex items-center justify-between gap-2"><span className="text-sm font-medium">客户要求 {index + 1}</span><Button type="button" variant="ghost" size="sm" onClick={() => { setResult(null); setRequirements(rows => rows.filter(item => item.id !== row.id)); }}>移除要求 {index + 1}</Button></div>
                <label className="grid gap-1 text-sm" htmlFor={`${rowId}-parameter`}>规格参数<select id={`${rowId}-parameter`} className={fieldClass} required value={row.parameter} onChange={event => change(row.id, { ...blank(), id: row.id, parameter: event.target.value })}><option value="">选择参数及版本</option>{parameters.map(item => <option key={parameterKey(item)} value={parameterKey(item)}>{item.name} · v{item.version}{item.unit ? ` · ${item.unit}` : ""}</option>)}</select></label>
                {parameter && <>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {numeric && <label className="grid gap-1 text-sm">要求范围<select className={fieldClass} value={row.mode} onChange={event => change(row.id, { mode: event.target.value as Requirement["mode"] })}><option value="exact">等于</option><option value="min">不低于</option><option value="max">不高于</option><option value="between">介于</option></select></label>}
                    <label className="grid gap-1 text-sm">{numeric ? "客户要求值（空白表示未知）" : "客户要求（未选择表示未知）"}
                      {parameter.value_type === "boolean" || parameter.value_type === "enum" ? <select className={fieldClass} value={row.value} onChange={event => change(row.id, { value: event.target.value })}><option value="">未知</option>{(parameter.value_type === "boolean" ? ["true", "false"] : parameter.enum_values ?? []).map(value => <option key={value} value={value}>{value === "true" ? "是" : value === "false" ? "否" : value}</option>)}</select>
                        : <input className={fieldClass} type={numeric ? "number" : "text"} step={numeric ? "any" : undefined} value={row.value} onChange={event => change(row.id, { value: event.target.value })}/>}
                    </label>
                    {numeric && row.mode === "between" && <label className="grid gap-1 text-sm">客户要求上限<input className={fieldClass} type="number" step="any" value={row.second} onChange={event => change(row.id, { second: event.target.value })}/></label>}
                    {numeric && <label className="grid gap-1 text-sm">客户单位（空白表示未知）<input className={fieldClass} value={row.unit} placeholder={parameter.unit ?? "字典未设单位"} onChange={event => change(row.id, { unit: event.target.value })}/></label>}
                    <label className="grid gap-1 text-sm">客户测试工况<input className={fieldClass} value={row.condition} placeholder="未明确则留空" onChange={event => change(row.id, { condition: event.target.value })}/></label>
                    <label className="grid gap-1 text-sm">补充测试条件（每行一条）<textarea className={fieldClass} value={row.tests} placeholder="按客户原文填写，未明确则留空" onChange={event => change(row.id, { tests: event.target.value })}/></label>
                  </div>
                  <Button type="button" size="sm" variant="outline" onClick={() => change(row.id, { unit: parameter.unit ?? "", condition: parameter.standard_condition ?? "" })}>客户已确认字典口径</Button>
                  <p className="subtle">字典工况：{parameter.standard_condition ?? "未登记"}。认证、适用范围和客户特殊要求仍须逐项核对。</p>
                </>}
              </div>;
            })}
            <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" onClick={() => { setResult(null); setRequirements(rows => [...rows, blank()]); }}>添加客户要求</Button><Button type="submit" disabled={!selected.length || !requirements.length}>{busy ? "正在核对…" : "核对所选规格"}</Button></div>
          </fieldset>
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        </form>}
      {result && <div className="mt-5 space-y-4" aria-live="polite">
        <p className="subtle">核对时间：{new Date(result.as_of).toLocaleString()}。结果来自当时可读的定义版本，刷新核对可读取最新事实。</p>
        {result.products.map(product => <article className="rounded-md border border-border p-4" key={product.product_id}>
          <div className="flex flex-wrap items-center justify-between gap-2"><div><h3 className="font-medium">{product.name} · {productLabels[product.status]}</h3><p className="subtle">{product.definition_revision ? `定义 v${product.definition_revision}` : "暂无定义"} · 满足 {product.counts.meets} · 差异 {product.counts.differs} · 待核对 {product.counts.unknown}</p></div><Button type="button" variant="outline" size="sm" onClick={() => onOpenProduct(product.product_id)}>查看型号与来源</Button></div>
          <ol className="mt-3 space-y-3">{product.checks.map(check => <li key={check.requirement_index} className="border-t border-border pt-3 text-sm"><p className="font-medium">{result.requirements[check.requirement_index].parameter} · {statusLabels[check.status]}</p><p className="mt-1">型号：{observed(check)}</p>{check.reasons.length > 0 && <p className="subtle mt-1">{check.reasons.map(reason => reasonLabels[reason] ?? "需要核对规格及来源").join("；")}</p>}</li>)}</ol>
        </article>)}
        <p className="text-sm">若所选规格均满足，请继续确认认证、销售地区、客户特殊要求和交付条件；确认无需开发后，在 CRM 继续办理。存在开发差异时再起草立项提案。</p>
      </div>}
    </details>
  </section>;
}
