"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { Definition, Item } from "./definitions";
import { request, type SourceRef } from "./product-work-api";

const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const labels: Record<string, string> = { job_to_be_done: "待完成工作", target_users: "目标用户", customer_problems: "客户问题", use_environments: "使用环境", buying_criteria: "购买标准", unmet_needs: "未满足需求", outcome: "期望成果" };
const states = { match: "声明有对应", gap: "已知声明缺口", unknown: "未知 / 待核对" };
export type Choice = { product_id: string; release_id: string };
type Segment = { id: string; title: string; version: number; product_line_id: string | null };
type Options = { items: Segment[]; total: number; revision: string; next_offset: number | null };
type Fact = { text: string; fact_kind: string; sources: SourceRef[]; target_value?: string | null; baseline_value?: string | null; unit?: string | null; measurement_method?: string; window?: string };
type Product = { id: string; code: string; name: string; lifecycle: string; release_id: string; definition_revision: number; href: string; content: Definition["content"]; source_warnings: string[] };
export type Preparation = { segment: Segment; products: Product[]; facts: { locator: string; fact: Fact }[]; source_digest: string; source_warnings: string[] };
export type Criterion = { key: string; source_locator: string; interpretation: string; mode: "feature" | "numeric_spec"; mappings: { product_id: string; item_key: string }[]; lower: string | null; upper: string | null; unit: string | null; conditions: string[] };
type Cell = { product_id: string; status: keyof typeof states; item_key: string | null; actual: Item | "included" | "excluded" | null; source_path: string | null; reason: string };
export type Result = { result_digest: string; snapshot: Preparation; criteria: { criterion: Criterion; market_fact: Fact; cells: Cell[]; counts: Record<keyof typeof states, number>; selected_portfolio_status: keyof typeof states }[]; product_summary: { product_id: string; match: number; gap: number; unknown: number }[]; overlap: { left_id: string; right_id: string; shared_criteria: string[]; ancestor_related: boolean }[]; formula_version: string; input_digest: string; scope: string; formula: string };

function MarketFact({ value, onRead }: { value: Fact; onRead: (id: string) => void }) {
  return <div className="space-y-1 text-sm"><p>{value.text}</p><p className="text-xs text-muted-foreground">{({ observed: "原观察事实", derived: "原推导", hypothesis: "原假设", desired_outcome: "期望成果" } as Record<string, string>)[value.fact_kind]}{!value.sources.length ? " · 没有引用依据" : ""}</p>{value.fact_kind === "desired_outcome" && <p className="text-xs">现状 {value.baseline_value ?? "未知"} → 目标 {value.target_value ?? "未定"} {value.unit} · {value.measurement_method} · {value.window}</p>}{value.sources.map((ref, index) => <button type="button" className="mr-2 text-xs underline" key={`${ref.ref_id}:${index}`} onClick={() => onRead(ref.ref_id)}>市场依据 {index + 1}</button>)}</div>;
}

export type CoverageResume = { record_id: string; title: string; prepared: Preparation; choices: Choice[]; criteria: Criterion[]; notice: string };
export function ProductMatrixCoverage({ base, choices, onRead, resume }: { base: string; choices: Choice[]; onRead: (id: string) => void; resume?: CoverageResume | null }) {
  const [options, setOptions] = useState<Options | null>(null);
  const [search, setSearch] = useState("");
  const [loadedSearch, setLoadedSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [prepared, setPrepared] = useState<Preparation | null>(resume?.prepared ?? null);
  const [criteria, setCriteria] = useState<Criterion[]>(resume?.criteria ?? []);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [calculatedInput, setCalculatedInput] = useState("");
  const [baseRecord, setBaseRecord] = useState<string | null>(resume?.record_id ?? null);
  const [reviewed, setReviewed] = useState(!resume);
  const [title, setTitle] = useState(resume?.title ?? "");
  const [reason, setReason] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const stableRequest = useRef({ body: "", id: "" });
  const input = JSON.stringify(criteria);
  const loadOptions = async (text: string, next = 0) => {
    setBusy(true); setError(null);
    try { const value = await request<Options>(`${base}/matrix-market-options`, "POST", { search: text, offset: next, revision: next ? options?.revision : null }); setOptions(value); setOffset(next); setLoadedSearch(text); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "市场细分暂不可用"); }
    finally { setBusy(false); }
  };
  const prepare = async (id: string) => {
    setBusy(true); setError(null); setResult(null);
    try { const value = await request<Preparation>(`${base}/matrix-coverage-context`, "POST", { segment_id: id, choices }); if (prepared?.segment.id !== id) { setCriteria([]); setBaseRecord(null); } setPrepared(value); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "原依据暂不可用"); }
    finally { setBusy(false); }
  };
  const calculate = async () => {
    if (!prepared) return;
    setBusy(true); setError(null); setResult(null); setSaved(null);
    try { setResult(await request<Result>(`${base}/matrix-coverage-calculation`, "POST", { segment_id: prepared.segment.id, choices, expected_source_digest: prepared.source_digest, criteria })); setCalculatedInput(input); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "本次对照未完成"); }
    finally { setBusy(false); }
  };
  const saveRecord = async () => {
    if (!prepared || !result || calculatedInput !== input) return;
    const body = { title: title.trim(), reason: reason.trim(), supersedes_id: baseRecord, expected_result_digest: result.result_digest, calculation: { segment_id: prepared.segment.id, choices, expected_source_digest: prepared.source_digest, criteria } };
    const signature = JSON.stringify(body);
    if (signature !== stableRequest.current.body) stableRequest.current = { body: signature, id: crypto.randomUUID() };
    setBusy(true); setError(null);
    try { const record = await request<{ id: string }>(`${base}/matrix-record-save`, "POST", { ...body, request_id: stableRequest.current.id }); setSaved(record.id); setBaseRecord(record.id); setReason(""); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "对照记录未保存"); }
    finally { setBusy(false); }
  };
  const update = (index: number, value: Partial<Criterion>) => setCriteria(old => old.map((item, i) => i === index ? { ...item, ...value } : item));
  return <details id="product-matrix-coverage" open={resume ? true : undefined} className="space-y-4 rounded-lg border p-4"><summary className="cursor-pointer font-semibold">市场需求覆盖与定位重叠</summary><p className="text-sm text-muted-foreground">选择原市场细分，明确需求如何对应本次所选产品的功能或规格。比较基于发布定义中的声明和标称目标，数值单位与条件不一致时保持未知。</p>
    <fieldset disabled={busy} className="space-y-3"><form className="flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); void loadOptions(search); }}><label className="min-w-64 flex-1 text-sm">查找当前市场细分<input maxLength={256} className={field} value={search} onChange={event => setSearch(event.target.value)}/></label><Button variant="outline">查询市场细分</Button></form>
      {options && <><p className="text-xs text-muted-foreground">匹配 {options.total} 项 · 第 {Math.floor(offset / 20) + 1} 页。只列各细分当前版本，不用历史版本代表当前需求。</p><div className="grid gap-2 sm:grid-cols-2">{options.items.map(item => <Button type="button" key={item.id} variant={prepared?.segment.id === item.id ? "secondary" : "outline"} className="h-auto justify-start whitespace-normal text-left" onClick={() => void prepare(item.id)}>{item.title} · v{item.version}{prepared?.segment.id === item.id ? " · 重读依据" : ""}</Button>)}</div>{options.items.length === 0 && <p className="text-sm">此范围没有当前市场细分，可先在“细分 / JTBD”登记需求与依据。</p>}<div className="flex gap-2"><Button type="button" variant="outline" size="sm" disabled={offset === 0} onClick={() => void loadOptions(loadedSearch, Math.max(0, offset - 20))}>上一页</Button><Button type="button" variant="outline" size="sm" disabled={options.next_offset === null} onClick={() => void loadOptions(loadedSearch, options.next_offset!)}>下一页</Button></div></>}
    </fieldset>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {prepared && <form className="space-y-4" onSubmit={event => { event.preventDefault(); void calculate(); }}><fieldset disabled={busy} className="space-y-4"><>{resume && <label className="block rounded-md bg-muted p-3 text-sm"><input type="checkbox" checked={reviewed} onChange={event => setReviewed(event.target.checked)}/> {resume.notice}。我已逐项核对当前需求和原条目对应。</label>}</><h5 className="font-medium">{prepared.segment.title} · 市场版本 {prepared.segment.version}</h5>{prepared.source_warnings.map(warning => <p className="text-sm" key={warning}>{warning}</p>)}<details className="space-y-2 rounded-md bg-muted p-3"><summary className="cursor-pointer text-sm">核对完整原市场需求与证据</summary>{prepared.facts.map(entry => <div key={entry.locator} className="space-y-1 border-t pt-2"><p className="text-xs font-medium">{labels[entry.locator.split(".")[0]]} · {entry.locator}</p><MarketFact value={entry.fact} onRead={onRead}/></div>)}</details>
      <p className="text-xs text-muted-foreground">判据是本次人工解读，尚未修改市场记录或产品定义。功能须明确选对应标识；数值只比较确认规格的标称目标，不计公差、实测分布或换算。每个判据都作为本次比较的必需项，最多20项。</p>
      {criteria.map((criterion, index) => <section className="space-y-3 rounded-md border p-3" key={criterion.key}><div className="flex justify-between gap-2"><h6 className="font-medium">判据 {index + 1}</h6><Button type="button" variant="ghost" size="sm" onClick={() => setCriteria(old => old.filter((_, i) => i !== index))}>移除此判据</Button></div><label className="block text-sm">对应原市场需求<select required className={field} value={criterion.source_locator} onChange={event => update(index, { source_locator: event.target.value })}>{prepared.facts.map(entry => <option key={entry.locator} value={entry.locator}>{labels[entry.locator.split(".")[0]]} · {entry.fact.text.slice(0, 100)}</option>)}</select></label><label className="block text-sm">本次判据解读与对应理由<textarea required maxLength={2048} className={field} value={criterion.interpretation} onChange={event => update(index, { interpretation: event.target.value })}/></label><label className="block text-sm">比较方法<select className={field} value={criterion.mode} onChange={event => update(index, { mode: event.target.value as Criterion["mode"], mappings: [], lower: null, upper: null, unit: null, conditions: [] })}><option value="feature">定义明确包含 / 排除功能</option><option value="numeric_spec">同单位、同条件的确认规格标称值</option></select></label>
        {criterion.mode === "numeric_spec" && <div className="grid gap-3 sm:grid-cols-3"><label className="text-sm">最低值（含，可留空）<input inputMode="decimal" className={field} value={criterion.lower ?? ""} onChange={event => update(index, { lower: event.target.value.trim() || null })}/></label><label className="text-sm">最高值（含，可留空）<input inputMode="decimal" className={field} value={criterion.upper ?? ""} onChange={event => update(index, { upper: event.target.value.trim() || null })}/></label><label className="text-sm">统一单位（原文）<input maxLength={64} className={field} value={criterion.unit ?? ""} onChange={event => update(index, { unit: event.target.value || null })}/></label><label className="text-sm sm:col-span-3">一致的测试条件（每行一项；空白表示要求规格也没有条件声明）<textarea className={field} value={criterion.conditions.join("\n")} onChange={event => update(index, { conditions: event.target.value.split("\n") })} onBlur={() => update(index, { conditions: criterion.conditions.map(value => value.trim()).filter(Boolean) })}/></label></div>}
        <div className="grid gap-3 sm:grid-cols-2">{prepared.products.map(product => <label key={product.id} className="text-sm">{product.code} · {product.name}<select className={field} value={criterion.mappings.find(mapping => mapping.product_id === product.id)?.item_key ?? ""} onChange={event => update(index, { mappings: [...criterion.mappings.filter(mapping => mapping.product_id !== product.id), ...(event.target.value ? [{ product_id: product.id, item_key: event.target.value }] : [])] })}><option value="">未对应（未知）</option>{criterion.mode === "feature" ? <>{product.content.included_features.map(key => <option key={`in:${key}`} value={key}>明确包含 · {key}</option>)}{product.content.excluded_features.map(key => <option key={`out:${key}`} value={key}>明确排除 · {key}</option>)}</> : product.content.items.map(item => <option key={item.item_key} value={item.item_key}>{item.item_key} · {item.title} · {item.target_value ?? "无数值"} {item.unit ?? ""}</option>)}</select></label>)}</div>
      </section>)}
      <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" disabled={criteria.length >= 20} onClick={() => setCriteria(old => [...old, { key: `criterion-${crypto.randomUUID().slice(0, 8)}`, source_locator: prepared.facts[0].locator, interpretation: "", mode: "feature", mappings: [], lower: null, upper: null, unit: null, conditions: [] }])}>增加市场判据</Button><Button disabled={criteria.length === 0 || !reviewed}>计算声明覆盖与重叠</Button><Button type="button" variant="ghost" onClick={() => void prepare(prepared.segment.id)}>重读当前依据</Button></div>
    </fieldset></form>}
    {result && <>{calculatedInput !== input && <p className="text-sm text-destructive">判据已改动，以下仍是上次计算；请重新计算。</p>}<CoverageResult value={result} onRead={onRead}/><form className="space-y-3 rounded-md bg-muted p-3" onSubmit={event => { event.preventDefault(); void saveRecord(); }}><p className="text-sm">具名保存原输入与结果{baseRecord ? "，接续原对照版本" : "，建立独立对照记录"}。保存分析不代表批准产品方案。</p><label className="block text-sm">对照名称<input required maxLength={2048} className={field} value={title} onChange={event => setTitle(event.target.value)}/></label><label className="block text-sm">保存 / 修订原因<textarea required maxLength={2048} className={field} value={reason} onChange={event => setReason(event.target.value)}/></label><Button disabled={busy || !!saved || input !== calculatedInput || !title.trim() || !reason.trim()}>保存本次对照</Button>{saved && <p className="text-sm">对照已保存。可在下方历史中回查；修改判据并重新计算后可续存新版本。</p>}</form></>}
  </details>;
}

export function CoverageResult({ value, onRead }: { value: Result; onRead: (id: string) => void }) {
  const products = value.snapshot.products;
  const name = (id: string) => { const product = products.find(item => item.id === id); return `${product?.code} · ${product?.name}`; };
  return <section className="space-y-3"><h5 className="font-semibold">本次所选范围的声明覆盖</h5><p className="text-sm">{value.scope}</p><p className="text-xs text-muted-foreground">{value.formula}</p><div className="grid gap-3 sm:grid-cols-2">{value.product_summary.map(summary => <article key={summary.product_id} className="space-y-1 rounded-md bg-muted p-3 text-sm"><p className="font-medium">{name(summary.product_id)} · {({ proposed: "拟议", developing: "开发中", available: "已上市", retired: "已退市" } as Record<string, string>)[products.find(product => product.id === summary.product_id)!.lifecycle]}</p><p>声明有对应 {summary.match} · 已知声明缺口 {summary.gap} · 未知 {summary.unknown}</p><a href={products.find(product => product.id === summary.product_id)!.href} className="text-xs underline">原发布定义与规格</a>{products.find(product => product.id === summary.product_id)!.source_warnings.map(warning => <p key={warning}>{warning}</p>)}</article>)}</div><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead><tr className="border-b"><th className="min-w-64 p-2">原需求与人工判据</th>{products.map(product => <th key={product.id} className="min-w-52 p-2">{product.code} · 定义 v{product.definition_revision}</th>)}<th className="min-w-44 p-2">所选组合</th></tr></thead><tbody>{value.criteria.map((row, index) => <tr key={row.criterion.key} className="border-b"><td className="space-y-2 p-2 align-top"><p className="font-medium">判据 {index + 1} · {row.criterion.interpretation}</p><MarketFact value={row.market_fact} onRead={onRead}/>{row.criterion.mode === "numeric_spec" && <p>标称目标区间：{row.criterion.lower ?? "未设下界"} ～ {row.criterion.upper ?? "未设上界"} {row.criterion.unit ?? "单位未定"}；条件 {row.criterion.conditions.join("；") || "无条件声明"}</p>}</td>{products.map(product => { const cell = row.cells.find(item => item.product_id === product.id)!; return <td className="space-y-1 p-2 align-top" key={product.id}><p className="font-medium">{states[cell.status]}</p><p>{cell.reason}</p>{cell.item_key && <p className="text-xs">对应：{cell.item_key}</p>}{cell.actual && typeof cell.actual === "object" && <details><summary className="cursor-pointer text-xs">原规格与依据</summary><p>{cell.actual.title} · 标称 {cell.actual.target_value ?? "未知"} {cell.actual.unit ?? ""}</p><p>原条件：{cell.actual.conditions.join("；") || "未声明"}</p><p>公差：{cell.actual.tolerance ?? "未声明"}（未纳入本次标称比较）</p><p>{cell.actual.rationale.text}</p>{cell.actual.rationale.sources.map((ref, i) => <button type="button" className="mr-2 text-xs underline" key={`${ref.ref_id}:${i}`} onClick={() => onRead(ref.ref_id)}>规格依据 {i + 1}</button>)}</details>}</td>; })}<td className="space-y-1 p-2 align-top"><p>{states[row.selected_portfolio_status]}</p><p className="text-xs">有对应 {row.counts.match} · 已知缺口 {row.counts.gap} · 未知 {row.counts.unknown}</p></td></tr>)}</tbody></table></div>
    <details className="space-y-2 rounded-md border p-3"><summary className="cursor-pointer text-sm">同一市场判据的定位重叠线索</summary><p className="text-xs text-muted-foreground">只统计本次都能对应的声明。不据此认定销量替代、产品蚕食或平台复用收益；父子定义可能有意继承。</p>{value.overlap.map(pair => <p key={`${pair.left_id}:${pair.right_id}`} className="text-sm">{name(pair.left_id)} / {name(pair.right_id)}：{pair.shared_criteria.length ? `共同对应判据 ${pair.shared_criteria.map(key => value.criteria.findIndex(row => row.criterion.key === key) + 1).join("、")}` : "无共同匹配判据"}{pair.ancestor_related ? " · 存在父子关系" : ""}</p>)}</details><p className="break-all text-xs text-muted-foreground">计算规则 {value.formula_version} · 输入 {value.input_digest}。此处为分析对照，保存后可回查输入与结果；原市场、产品定义与路线图保持原有发布记录。</p>
  </section>;
}
