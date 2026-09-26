"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ProductMatrixHistory } from "./product-matrix-history";
import { ProductMatrixCoverage, type CoverageResume } from "./product-matrix-coverage";
import { RoadmapBoardCard, type Roadmap } from "./product-roadmap";
import type { Definition } from "./definitions";
import type { Fact } from "./market-segments";
import { request, type EvidenceContent, type ProductCatalog, type SourceRef } from "./product-work-api";

const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const lifecycles: Record<string, string> = { proposed: "拟议", developing: "开发中", available: "已上市", retired: "已退市" };
const levels: Record<string, string> = { line: "产品线", family: "家族", platform: "平台", series: "系列", model: "型号", variant: "变体" };
const kinds = { observed: "观察事实", derived: "推导", hypothesis: "假设" };
const publications: Record<string, string> = { current: "当前已发布", missing: "尚无发布定义", withdrawn: "已撤回" };
type Product = {
  id: string; name: string; code: string; product_line_id: string; level: string; lifecycle: string;
  regions: string[]; channels: string[]; path: { id: string; name: string; level: string }[];
  hierarchy_warning: string | null; publication: string; release_id: string | null;
  definition_id: string | null; definition_revision: number | null; released_at: string | null;
  href: string | null; target_users: string[] | null; scenarios: string[] | null;
  price_position: Fact | null; launch_window: Fact | null;
  roadmap: Roadmap | null; roadmap_source_current: boolean; roadmap_href: string;
};
type Query = { product_line_id: string | null; root_id: string | null; lifecycle: string | null; region: string; channel: string; scenario: string; search: string; publication: string };
const initial: Query = { product_line_id: null, root_id: null, lifecycle: null, region: "", channel: "", scenario: "", search: "", publication: "current" };
type Page = { items: Product[]; total: number; scope_counts: Record<string, number>; facets: { regions: string[]; channels: string[]; scenarios: string[] }; revision: string; next_offset: number | null };
type Selected = { product_id: string; release_id: string; name: string };
type ComparedProduct = Product & { content: Definition["content"]; sources: SourceRef[]; source_warnings: string[]; definition_digest: string };
type Comparison = { products: ComparedProduct[]; pairs: { left_id: string; right_id: string; shared: Record<string, string[]>; same_platform: boolean; ancestor_related: boolean }[]; limits: string[]; revision: string; comparison_version: string };
const joined = (items: string[] | null) => items?.length ? items.join("；") : "未声明";

function FactValue({ fact, onRead }: { fact: Fact | null; onRead: (id: string) => void }) {
  if (!fact) return <span className="text-muted-foreground">未声明</span>;
  return <div className="space-y-1"><p>{fact.text}</p><p className="text-xs text-muted-foreground">{kinds[fact.fact_kind]}{fact.derivation_version ? ` · 方法 ${fact.derivation_version}` : ""}{!fact.sources.length ? " · 无引用依据" : ""}</p>{fact.sources.map((ref, index) => <button type="button" key={`${ref.ref_id}:${index}`} className="mr-2 text-xs underline" onClick={() => onRead(ref.ref_id)}>依据 {index + 1}</button>)}</div>;
}

export function ProductMatrix({ base, catalog }: { base: string; catalog: ProductCatalog }) {
  const [query, setQuery] = useState<Query>(initial);
  const [loaded, setLoaded] = useState<Query>(initial);
  const [page, setPage] = useState<Page | null>(null);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Selected[]>([]);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [resume, setResume] = useState<CoverageResume | null>(null);
  useEffect(() => { if (resume) document.getElementById("product-matrix-coverage")?.scrollIntoView({ block: "start" }); }, [resume]);
  const [view, setView] = useState("matrix");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<EvidenceContent | null>(null);
  const [reading, setReading] = useState(false);
  useEffect(() => {
    let live = true;
    void request<Page>(`${base}/product-matrix`, "POST", initial).then(value => { if (live) setPage(value); }).catch(failure => { if (live) setError(failure.message); }).finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [base]);
  const load = async (filters: Query, next = 0) => {
    setBusy(true); setError(null);
    try { const value = await request<Page>(`${base}/product-matrix`, "POST", { ...filters, offset: next, revision: next ? page?.revision : null }); setPage(value); setOffset(next); setLoaded(filters); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "矩阵暂不可用"); }
    finally { setBusy(false); }
  };
  const read = (id: string) => {
    if (reading) return;
    setReading(true); setEvidence(null); setError(null);
    void request<EvidenceContent>(`${base}/evidence/${id}/content`).then(setEvidence).catch(failure => setError(failure.message)).finally(() => setReading(false));
  };
  const compare = async () => {
    setBusy(true); setError(null); setComparison(null); setResume(null);
    try { setComparison(await request<Comparison>(`${base}/product-matrix-comparison`, "POST", { choices: selected.map(({ product_id, release_id }) => ({ product_id, release_id })) })); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "比较暂不可用"); }
    finally { setBusy(false); }
  };
  const resumeRecord = async (id: string) => {
    setBusy(true);
    try {
      const value = await request<CoverageResume>(`${base}/matrix-record-refresh`, "POST", { record_id: id });
      const comparison = await request<Comparison>(`${base}/product-matrix-comparison`, "POST", { choices: value.choices });
      setComparison(comparison); setResume(value);
      setSelected(comparison.products.map(product => ({ product_id: product.id, release_id: product.release_id!, name: `${product.code} · ${product.name}` })));
    } finally { setBusy(false); }
  };
  const toggle = (product: Product) => {
    setComparison(null);
    setSelected(old => old.some(item => item.product_id === product.id) ? old.filter(item => item.product_id !== product.id) : [...old, { product_id: product.id, release_id: product.release_id!, name: `${product.code} · ${product.name}` }]);
  };
  const fact = (value: Fact | null) => <FactValue fact={value} onRead={read} />;
  return <section className="space-y-4 rounded-lg border p-4">
    <header><h3 className="font-semibold">产品矩阵与上市窗口</h3><p className="mt-1 text-sm text-muted-foreground">从当前发布的产品定义比较定位与规格，尚未立项的产品也可加入。产品家族归属在下方维护。</p></header>
    <fieldset disabled={busy} className="space-y-3"><form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" onSubmit={event => { event.preventDefault(); void load(query); }}>
      <label className="text-sm">产品线<select className={field} value={query.product_line_id ?? ""} onChange={event => setQuery({ ...query, product_line_id: event.target.value || null, root_id: null })}><option value="">全部可访问产品线</option>{catalog.nodes.filter(node => node.level === "line").map(node => <option key={node.id} value={node.id}>{node.name}</option>)}</select></label>
      <label className="text-sm">家族 / 平台 / 系列范围<select className={field} value={query.root_id ?? ""} onChange={event => setQuery({ ...query, root_id: event.target.value || null })}><option value="">全部层级</option>{catalog.nodes.filter(node => (!query.product_line_id || node.product_line_id === query.product_line_id) && ["family", "platform", "series", "model"].includes(node.level)).map(node => <option key={node.id} value={node.id}>{levels[node.level]} · {node.code} · {node.name}</option>)}</select></label>
      <label className="text-sm">生命周期<select className={field} value={query.lifecycle ?? ""} onChange={event => setQuery({ ...query, lifecycle: event.target.value || null })}><option value="">全部状态</option>{Object.entries(lifecycles).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label className="text-sm">定义状态<select className={field} value={query.publication} onChange={event => setQuery({ ...query, publication: event.target.value })}><option value="all">全部（含缺项）</option>{Object.entries(publications).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      {([["region", "regions", "地区"], ["channel", "channels", "渠道"], ["scenario", "scenarios", "使用场景"]] as const).map(([key, facet, label]) => <label key={key} className="text-sm">{label}<select className={field} value={query[key]} onChange={event => setQuery({ ...query, [key]: event.target.value })}><option value="">全部</option>{Array.from(new Set([...(page?.facets[facet] ?? []), ...(query[key] ? [query[key]] : [])])).map(value => <option key={value} value={value}>{value}</option>)}</select></label>)}
      <label className="text-sm">名称 / 用户 / 价格定位 / 窗口<input className={field} maxLength={256} value={query.search} onChange={event => setQuery({ ...query, search: event.target.value })} /></label>
      <div className="flex gap-2 sm:col-span-2 lg:col-span-4"><Button>查询 / 刷新</Button><Button type="button" variant="outline" onClick={() => { setQuery(initial); void load(initial); }}>重置筛选</Button><Button type="button" variant={view === "matrix" ? "secondary" : "ghost"} onClick={() => setView("matrix")}>矩阵</Button><Button type="button" variant={view === "windows" ? "secondary" : "ghost"} onClick={() => setView("windows")}>路线图 / 上市窗口</Button></div>
    </form></fieldset>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {reading && <p role="status" className="text-sm">正在读取原依据…</p>}
    {evidence && <section className="space-y-2 rounded-md bg-muted p-3"><div className="flex items-center justify-between"><h4 className="font-medium">原依据正文</h4><Button variant="ghost" size="sm" onClick={() => setEvidence(null)}>关闭</Button></div><p className="break-all text-xs">{evidence.snapshot_id} · {evidence.content_digest}</p><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words text-sm">{evidence.content}</pre></section>}
    {page && <><p className="text-sm">所选层级范围：当前已发布 {page.scope_counts.current} · 尚无发布定义 {page.scope_counts.missing} · 已撤回 {page.scope_counts.withdrawn}。全部筛选匹配 {page.total} 项。</p>
      {JSON.stringify(query) !== JSON.stringify(loaded) && <p className="text-xs text-muted-foreground">筛选尚未应用，当前仍显示上次查询结果。</p>}
      <p className="text-xs text-muted-foreground">地区与渠道取该产品当前登记值，不自动继承父级。价格、窗口和场景取当前发布定义；原上市窗口与具名路线图分列，计划日期不表示实际完成。</p>
      {page.items.length === 0 ? <p className="text-sm">此范围没有匹配产品。可切换“全部（含缺项）”查看尚未发布的产品。</p> : view === "matrix" ? <div className="overflow-x-auto"><table className="w-full min-w-[920px] text-left text-sm"><thead><tr className="border-b">{["加入比较", "产品与家族", "用户 / 场景", "地区 / 渠道", "价格定位", "上市窗口"].map(label => <th key={label} className="p-2 align-top font-medium">{label}</th>)}</tr></thead><tbody>{page.items.map(product => <tr key={product.id} className="border-b"><td className="p-2 align-top"><input type="checkbox" aria-label={`比较 ${product.code} ${product.name}`} checked={selected.some(item => item.product_id === product.id)} disabled={busy || product.publication !== "current" || (selected.length >= 8 && !selected.some(item => item.product_id === product.id))} onChange={() => toggle(product)} /></td><td className="min-w-52 space-y-1 p-2 align-top"><strong>{product.code} · {product.name}</strong><p className="text-xs text-muted-foreground">{product.path.map(node => node.name).join(" → ")}</p><p>{lifecycles[product.lifecycle]} · {levels[product.level]}</p><p>{publications[product.publication]}{product.definition_revision ? ` · 定义 v${product.definition_revision}` : ""}</p>{product.hierarchy_warning && <p className="text-destructive">{product.hierarchy_warning}</p>}{product.href && <a href={product.href} className="text-xs underline">原定义与发布记录</a>}</td><td className="min-w-44 p-2 align-top"><p>{joined(product.target_users)}</p><p className="mt-1 text-muted-foreground">{joined(product.scenarios)}</p></td><td className="p-2 align-top"><p>{joined(product.regions)}</p><p>{joined(product.channels)}</p></td><td className="min-w-48 p-2 align-top">{fact(product.price_position)}</td><td className="min-w-48 p-2 align-top">{fact(product.launch_window)}<a href={product.roadmap_href} className="mt-2 inline-block text-xs underline">编排 / 查看路线图</a></td></tr>)}</tbody></table></div> : <div className="grid gap-3 sm:grid-cols-2">{Object.entries(lifecycles).map(([key, label]) => <section key={key} className="space-y-3 rounded-md border p-3"><h4 className="font-medium">{label} · 本页 {page.items.filter(item => item.lifecycle === key).length} 项</h4>{page.items.filter(item => item.lifecycle === key).map(product => <article key={product.id} className="space-y-2 border-t pt-2 text-sm"><p>{product.code} · {product.name} · {publications[product.publication]}</p>{fact(product.launch_window)}<RoadmapBoardCard roadmap={product.roadmap} sourceCurrent={product.roadmap_source_current}/><a href={product.roadmap_href} className="inline-block text-xs underline">编排 / 查看路线图与依据</a>{product.href && <a href={product.href} className="inline-block text-xs underline">原定义与发布依据</a>}</article>)}</section>)}</div>}
      <div className="flex items-center gap-3"><Button variant="outline" size="sm" disabled={busy || offset === 0} onClick={() => void load(loaded, Math.max(0, offset - 20))}>上一页</Button><span className="text-sm">第 {Math.floor(offset / 20) + 1} 页</span><Button variant="outline" size="sm" disabled={busy || page.next_offset === null} onClick={() => void load(loaded, page.next_offset!)}>下一页</Button></div>
    </>}
    {!page && <p className="text-sm">{error ? "矩阵尚未加载，可查询重试。" : "正在读取产品和发布版本…"}</p>}
    <div className="space-y-2 rounded-md bg-muted p-3"><p className="text-sm">跨页选择 2–8 项比较（已选 {selected.length}）。按产品编号区分同名型号与变体。</p><div className="flex flex-wrap gap-2">{selected.map(item => <Button variant="outline" size="sm" key={item.product_id} disabled={busy} onClick={() => { setSelected(old => old.filter(value => value.product_id !== item.product_id)); setComparison(null); }}>{item.name} · 移除</Button>)}</div><div className="flex gap-2"><Button disabled={busy || selected.length < 2} onClick={() => void compare()}>比较当前发布定义</Button><Button variant="ghost" disabled={busy || !selected.length} onClick={() => { setSelected([]); setComparison(null); }}>清空选择</Button></div></div>
    {comparison && <ComparisonView base={base} comparison={comparison} onRead={read} resume={resume} />}
    <ProductMatrixHistory base={base} onRead={read} onResume={resumeRecord}/>
  </section>;
}

function ComparisonView({ base, comparison, onRead, resume }: { base: string; comparison: Comparison; onRead: (id: string) => void; resume: CoverageResume | null }) {
  const products = comparison.products;
  const fact = (value: Fact) => <FactValue fact={value} onRead={onRead} />;
  const name = (id: string) => { const item = products.find(product => product.id === id); return `${item?.code} · ${item?.name}`; };
  const features = Array.from(new Set(products.flatMap(product => [...product.content.included_features, ...product.content.excluded_features]))).sort();
  return <section className="space-y-4"><h4 className="font-semibold">发布定义并列比较</h4><ul className="space-y-1 text-xs text-muted-foreground">{comparison.limits.map(note => <li key={note}>{note}</li>)}</ul><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b"><th className="min-w-32 p-2">比较维度</th>{products.map(product => <th className="min-w-72 p-2 align-top" key={product.id}>{product.code} · {product.name}<p className="font-normal">定义 v{product.definition_revision} · {product.released_at && new Date(product.released_at).toLocaleString()}</p><a href={product.href!} className="font-normal underline">原定义 / 原依据</a></th>)}</tr></thead><tbody>
    {([ ["归属", (product: ComparedProduct) => product.path.map(node => `${levels[node.level]} ${node.name}`).join(" → ")], ["用户 / 场景", (product: ComparedProduct) => <>{joined(product.target_users)}<hr className="my-2" />{joined(product.scenarios)}</>], ["地区 / 渠道", (product: ComparedProduct) => <>{joined(product.regions)}<hr className="my-2" />{joined(product.channels)}</>], ["生命周期", (product: ComparedProduct) => lifecycles[product.lifecycle]], ["目标成本", (product: ComparedProduct) => fact(product.content.target_cost)], ["价格定位", (product: ComparedProduct) => fact(product.content.price_position)], ["上市窗口", (product: ComparedProduct) => fact(product.content.launch_window)], ["地区约束", (product: ComparedProduct) => product.content.region_constraints.length ? product.content.region_constraints.map((value, index) => <div key={index} className="mb-2">{fact(value)}</div>) : "未声明"], ["服务要求", (product: ComparedProduct) => product.content.service_requirements.length ? product.content.service_requirements.map((value, index) => <div key={index} className="mb-2">{fact(value)}</div>) : "未声明"], ["成功指标", (product: ComparedProduct) => product.content.success_criteria.map((value, index) => <div key={index} className="mb-2">{fact(value)}</div>)], ["依据状态", (product: ComparedProduct) => product.source_warnings.length ? <ul>{product.source_warnings.map(warning => <li key={warning}>{warning}</li>)}</ul> : "原来源检查未发现停用、过期或冲突标记；仍需核对适用范围"] ] as const).map(([label, render]) => <tr key={label} className="border-b"><th className="p-2 align-top font-medium">{label}</th>{products.map(product => <td className="p-2 align-top" key={product.id}>{render(product)}</td>)}</tr>)}
    {features.map(feature => <tr key={`feature:${feature}`} className="border-b"><th className="p-2 align-top font-medium">功能 · {feature}</th>{products.map(product => <td className="p-2 align-top" key={product.id}>{product.content.included_features.includes(feature) ? "明确包含" : product.content.excluded_features.includes(feature) ? "明确排除" : "未声明"}</td>)}</tr>)}
  </tbody></table></div>
  <details className="space-y-3 rounded-md border p-3"><summary className="cursor-pointer font-medium">原始规格、单位与验证条件</summary><div className="grid gap-3 lg:grid-cols-2">{products.map(product => <section key={product.id} className="space-y-2"><h5 className="font-medium">{product.code} · {product.name}</h5>{product.content.items.map(item => <article key={item.item_key} className="space-y-1 rounded-md bg-muted p-3 text-sm"><p>{item.item_key} · {item.title}</p><p>目标：{item.target_text ?? "未声明文本"}{item.target_value !== null ? ` · ${item.target_value} ${item.unit ?? ""}` : ""} · 公差 {item.tolerance ?? "未声明"}</p><p>条件：{joined(item.conditions)}</p><p>状态：{({ proposed: "拟议", needs_confirmation: "待确认", confirmed: "已确认", not_applicable: "不适用" })[item.state]}{item.disposition_reason ? ` · ${item.disposition_reason}` : ""}</p><p>验证：{item.verification_method ?? "未声明"} · {item.verification_stage ?? "阶段未声明"}</p><p>判据：{item.acceptance_criterion ?? "未声明"}</p>{fact(item.rationale)}</article>)}</section>)}</div></details>
  <details className="space-y-3 rounded-md border p-3"><summary className="cursor-pointer font-medium">相同声明与平台归属 · 人工核对线索</summary>{comparison.pairs.map(pair => <article key={`${pair.left_id}:${pair.right_id}`} className="space-y-1 border-t pt-2 text-sm"><p className="font-medium">{name(pair.left_id)} / {name(pair.right_id)}</p><p>{pair.ancestor_related ? "存在父子层级关系，声明可能有意继承。" : "不是直接或间接父子层级。"} {pair.same_platform ? "登记为同一平台，可核对工程复用条件。" : "没有共同平台归属记录。"}</p>{Object.entries(pair.shared).map(([key, values]) => <p key={key}>{({ target_users: "相同用户原文", scenarios: "相同场景原文", regions: "相同地区", channels: "相同渠道", included_features: "共同包含功能标识" } as Record<string, string>)[key]}：{values.length ? values.join("；") : "无完全相同声明"}</p>)}</article>)}</details>
  <ProductMatrixCoverage key={`${comparison.revision}:${resume?.record_id ?? "new"}`} resume={resume} base={base} choices={products.map(product => ({ product_id: product.id, release_id: product.release_id! }))} onRead={onRead}/>
  <p className="break-all text-xs text-muted-foreground">比较版本 {comparison.comparison_version} · {comparison.revision}。这是本次读取的定义对照，未保存为正式方案。</p>
  </section>;
}
