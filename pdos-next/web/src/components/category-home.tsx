"use client";

import { Fragment, useEffect, useId, useState } from "react";
import { ArrowClockwise, ArrowLeft, ArrowRight, ArrowUpRight, Info, MagnifyingGlass, Sparkle, Plus } from "@phosphor-icons/react";
import { DetailSheet } from "@/components/ui/detail-sheet";
import { ProposalList } from "@/components/proposals/proposal-list";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/browser-api";
import { CategoryMatrix } from "@/components/preproject/category-matrix";
import { CompetitorSegments } from "@/components/preproject/competitor-segments";
import { StandardMatch } from "@/components/preproject/standard-match";
import { CategoryMetadataEditor } from "./category-metadata-editor";
import { CategoryMaterialEditor, type MaterialContext } from "./category-material-editor";
import type { MaterialKind, CategoryParameter } from "@/lib/category-materials";
import styles from "./category-home.module.css";

type Api = typeof browserApi;
type Product = { id: string; name: string; purpose: string };
type KnowledgeItem = { id?: string; lineage_id?: string; version?: number; kind: string; content: Record<string, unknown>; origin: string; status: string; regions?: string[]; source_refs?: import("@/lib/category-materials").MaterialRef[]; direct_source_refs?: import("@/lib/category-materials").MaterialRef[]; source_changes?: unknown[] };
type ParameterItem = CategoryParameter;
type Page<T> = { items: T[]; next_cursor?: string | null };
type ReadErrors = Partial<Record<"products" | "knowledge" | "parameters", string>>;
type ScopedRead<T> = { categoryId: string; api: Api; readVersion: number; value: T };
const views = [{ id: "overview", label: "共享知识" }, { id: "competitor", label: "竞品库" }, { id: "voice", label: "用户声音" }, { id: "regulation", label: "法规认证" }, { id: "parameters", label: "规格字典" }, { id: "products", label: "型号" }, { id: "matrix", label: "品类矩阵" }] as const;
type View = typeof views[number]["id"];
const originLabels: Record<string, string> = { human: "人工", ai_draft: "AI 草稿", imported: "导入" };
const natureLabels: Record<string, string> = { measured: "实测", claimed: "宣传", inferred: "推断", unknown: "未知" };
const typeLabels: Record<string, string> = { number: "数值", range: "范围", text: "文本", boolean: "是 / 否", enum: "枚举" };
const stateLabels: Record<string, string> = { unknown: "未知", confirmed: "已确认", ai_draft: "AI 草稿", pending: "待确认", needs_review: "待核对", not_assessed: "未评估", active: "当前记录", withdrawn: "已撤回" };
function record(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function rows(value: unknown): Record<string, unknown>[] { return Array.isArray(value) ? value.filter(record) : []; }
function text(value: unknown, fallback = "未登记"): string { return typeof value === "string" && value.trim() ? value : typeof value === "number" ? String(value) : typeof value === "boolean" ? value ? "是" : "否" : fallback; }
function state(value: unknown) { const valueText = text(value, "未知"); return stateLabels[valueText] ?? valueText; }
function sourceLabel(item: KnowledgeItem) {
  const nested = [...rows(item.content.metrics), ...rows(item.content.features), ...rows(item.content.prices)].some(observation => record(observation.source_ref)) || rows(item.content.representative_refs).length > 0;
  return item.source_changes?.length ? "来源需重核" : item.source_refs?.length || nested ? "已登记来源" : "来源未登记";
}

async function readPages<T>(api: Api, root: string, active: () => boolean): Promise<T[]> {
  const result: T[] = [], seen = new Set<string>();
  let cursor: string | null = null;
  do {
    const page: Page<T> = await api(`${root}${root.includes("?") ? "&" : "?"}page_size=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
    if (!active()) return [];
    result.push(...page.items);
    cursor = page.next_cursor ?? null;
    if (cursor && seen.has(cursor)) throw new Error("资料分页位置未推进，请刷新重试。");
    if (cursor) seen.add(cursor);
  } while (cursor);
  return result;
}

function CompetitorSpecs({ item, parameters }: { item: KnowledgeItem; parameters: ParameterItem[] | null }) {
  const observations = [...rows(item.content.metrics), ...rows(item.content.features)];
  if (!observations.length) return <span className={styles.muted}>规格未知</span>;
  return <div className={styles.observations}>{observations.map((observation, index) => {
    const parameter = parameters?.find(candidate => candidate.parameter_id === observation.parameter_id && candidate.version === observation.parameter_version);
    const value = observation.value !== null && observation.value !== undefined ? text(observation.value, "未知") : observation.text !== null && observation.text !== undefined ? text(observation.text, "未知") : observation.lower !== null && observation.lower !== undefined || observation.upper !== null && observation.upper !== undefined ? `${text(observation.lower, "不限")} ～ ${text(observation.upper, "不限")}` : "未知";
    return <div key={index}><span>{parameter?.name ?? "未映射参数"} · v{text(observation.parameter_version, "未知")}：<b>{value}</b>{observation.unit ? ` ${text(observation.unit)}` : ""}</span><span className={styles.badge} data-nature={text(observation.nature, "unknown")}>{natureLabels[text(observation.nature)] ?? "未知"}</span><small>工况：{text(observation.condition_note, "未知")}</small></div>;
  })}</div>;
}

export function CategoryHome({ categoryId, categoryName, categoryPurpose = "", categoryOwner, api, onOpenWorkbench, onOpenPai, onPaiContext, onBack }: {
  onBack?: () => void;
  categoryId: string; categoryName: string; categoryPurpose?: string; categoryOwner?: string | null; api: Api;
  onOpenWorkbench: (bench: "products" | "knowledge", productId?: string) => void;
  onOpenPai: (context?: MaterialContext) => void; onPaiContext?: (context: MaterialContext | undefined) => void;
}) {
  const [storedProducts, setProducts] = useState<ScopedRead<Product[]> | null>(null);
  const [storedKnowledge, setKnowledge] = useState<ScopedRead<KnowledgeItem[]> | null>(null);
  const [storedParameters, setParameters] = useState<ScopedRead<ParameterItem[]> | null>(null);
  const [storedErrors, setErrors] = useState<ScopedRead<ReadErrors> | null>(null);
  const [editing, setEditing] = useState<{ categoryId: string; api: Api; entryId: string } | null>(null);
  const [reload, setReload] = useState(0);
  const [inspection, setInspection] = useState<{ categoryId: string; api: Api; id: string } | null>(null);
  const [withdrawn, setWithdrawn] = useState(false);
  const [material, setMaterial] = useState<{ categoryId: string; api: Api; kind: MaterialKind; item: KnowledgeItem | ParameterItem | null } | null>(null);
  const inScope = (read: ScopedRead<unknown> | null) => read?.categoryId === categoryId && read.api === api && read.readVersion === reload;
  const products = inScope(storedProducts) ? storedProducts!.value : null, knowledge = inScope(storedKnowledge) ? storedKnowledge!.value : null, parameters = inScope(storedParameters) ? storedParameters!.value : null, errors: ReadErrors = inScope(storedErrors) ? storedErrors!.value : {};
  const editedEntryId = editing?.categoryId === categoryId && editing.api === api ? editing.entryId : null;
  const [view, setView] = useState<View>("overview");
  const [query, setQuery] = useState("");
  const [finding, setFinding] = useState(false);
  const panelId = useId();
  useEffect(() => {
    const saved = (event: Event) => { if ((event as CustomEvent).detail?.categoryId === categoryId) setReload(value => value + 1); };
    window.addEventListener("pdos:category-material-saved", saved);
    return () => window.removeEventListener("pdos:category-material-saved", saved);
  }, [categoryId]);

  useEffect(() => {
    let active = true;
    const failures: ReadErrors = {};
    void Promise.all([
      api<Product[]>(`v1/categories/${categoryId}/products`).then(value => { if (active) setProducts({ categoryId, api, readVersion: reload, value }); }).catch(failure => { failures.products = (failure as Error).message; }),
      readPages<KnowledgeItem>(api, `v1/categories/${categoryId}/knowledge${withdrawn ? "?status=withdrawn" : ""}`, () => active).then(value => { if (active) setKnowledge({ categoryId, api, readVersion: reload, value }); }).catch(failure => { failures.knowledge = (failure as Error).message; }),
      readPages<ParameterItem>(api, `v1/categories/${categoryId}/parameters`, () => active).then(value => { if (active) setParameters({ categoryId, api, readVersion: reload, value }); }).catch(failure => { failures.parameters = (failure as Error).message; }),
    ]).then(() => { if (active) setErrors({ categoryId, api, readVersion: reload, value: failures }); });
    return () => { active = false; };
  }, [api, categoryId, reload, withdrawn]);

  function refresh() { setProducts(null); setKnowledge(null); setParameters(null); setErrors(null); setReload(value => value + 1); }
  const activeView = views.find(item => item.id === view)!;
  const relevant = knowledge?.filter(item => item.kind === view && JSON.stringify(item.content).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) ?? [];
  const boundary = knowledge?.find(item => item.kind === "boundary" && item.status === "active");
  const viewError = view === "products" ? errors.products : view === "parameters" ? errors.parameters : view === "matrix" ? "" : errors.knowledge;
  const loading = view === "products" ? products === null : view === "parameters" ? parameters === null : view === "matrix" ? false : knowledge === null;

  const materialKind: MaterialKind | null = view === "parameters" ? "parameter" : view === "competitor" || view === "voice" ? view : null;
  const openPai = () => onOpenPai(materialKind ? { kind: materialKind, title: activeView.label, request: { id: crypto.randomUUID(), prompt: `请帮我整理${categoryName}的${activeView.label}，先核对已有资料和来源，再起草可编辑的资料；不确定的信息保留待补充。` } } : { kind: "category", title: categoryName, id: categoryId, draft: { name: categoryName, purpose: categoryPurpose }, request: { id: crypto.randomUUID(), prompt: `请读取${categoryName}现有的竞品、用户声音和规格字典，帮我完善品类资料。` } });
  if (material?.categoryId === categoryId && material.api === api) return <div className={styles.page}><div className={styles.title}><p>{categoryName} / {material.kind === "parameter" ? "规格字典" : material.kind === "competitor" ? "竞品库" : "用户声音"}</p></div><CategoryMaterialEditor categoryId={categoryId} kind={material.kind} item={material.item} parameters={parameters ?? []} api={api} onClose={() => { setMaterial(null); onPaiContext?.(undefined); refresh(); }} onSaved={refresh} onOpenPai={onOpenPai} onContextChange={onPaiContext}/></div>;
  const prepareProposal = () => onOpenPai({ kind: "proposal", title: `${categoryName} · 新提案`, draft: { category_name: categoryName, purpose: categoryPurpose, material_counts: { competitors: knowledge?.filter(item => item.kind === "competitor").length, voices: knowledge?.filter(item => item.kind === "voice").length, parameters: parameters?.length } }, request: { id: crypto.randomUUID(), prompt: "请先读取当前品类的竞品、用户声音和规格字典，结合主要场景起草一份私有立项提案。缺失信息先问我，提供可编辑候选，确认后保存。" } });
  return <div className={styles.page}>
    {onBack && <button type="button" className={styles.back} onClick={onBack}><ArrowLeft size={14}/>全部品类</button>}
    <header className={styles.categoryHead}>
      <div className={styles.title}><div className={styles.titleLine}><h1>{categoryName}</h1><CategoryMetadataEditor key={categoryId} categoryId={categoryId} api={api} iconOnly/></div><p>{categoryPurpose || (boundary ? text(boundary.content.definition) : errors.knowledge ? "品类资料暂不可读" : knowledge === null ? "正在读取品类资料…" : "主要场景尚未填写")} · 负责人 {categoryOwner || "待确认"}</p></div>
      <div className={styles.actions}><Button variant="outline" size="sm" onClick={() => setFinding(true)}>查看提案</Button><Button size="sm" onClick={prepareProposal}>准备立项提案</Button></div>
    </header>
    <div className={styles.tabs} role="group" aria-label="品类知识视图">{views.filter(item => item.id !== "regulation" || view === "regulation").map(item => <button type="button" key={item.id} aria-pressed={view === item.id} aria-controls={panelId} onClick={() => { setView(item.id); setQuery(""); }}>{item.label}</button>)}<button type="button" className={styles.refresh} onClick={refresh} aria-label="刷新品类资料" title="刷新品类资料"><ArrowClockwise size={14} aria-hidden="true"/></button></div>
    {view === "overview" ? <section className={styles.overview} aria-label="品类共享知识">
      <button type="button" className={styles.overviewRow} onClick={() => onOpenPai({ kind: "category", title: categoryName, id: categoryId, draft: { name: categoryName, purpose: categoryPurpose } })}><span><strong>用户与场景</strong><small>当前产品方向 · 待持续核对</small></span><span>{categoryPurpose || "主要场景尚未填写"}</span><ArrowUpRight size={14}/></button>
      {([{ id: "competitor", label: "竞品库", note: "实测 / 宣传 / 推断分别记录 · 查看与维护" }, { id: "voice", label: "用户声音", note: "保留出处与样本量 · 查看与维护" }, { id: "regulation", label: "法规认证", note: "已登记资料 · 版本与适用性待复核" }] as const).map(item => <button type="button" className={styles.overviewRow} key={item.id} onClick={() => { setView(item.id); setQuery(""); }}><span><strong>{item.label}</strong><small>{item.note}</small></span><span>{errors.knowledge ? "暂不可读" : knowledge ? `${knowledge.filter(row => row.kind === item.id).length} 条${item.id === "competitor" ? "竞品" : item.id === "voice" ? "声音" : "法规"}记录` : "读取中…"}</span><ArrowUpRight size={14}/></button>)}
      <p className={styles.overviewNote}>{parameters ? `已登记 ${parameters.length} 个参数。` : ""}客户原件保留在私有提案中，经人工去标识后才能沉淀为共享知识。</p>
    </section> : <>
    <div className={styles.listToolbar}><span>{viewError || loading ? activeView.label : view === "parameters" ? `${parameters?.length ?? 0} 个参数` : view === "products" ? `${products?.length ?? 0} 个型号` : `${relevant.length} 条记录`}</span>{(view === "competitor" || view === "voice") && <label className={styles.withdrawnToggle}><input type="checkbox" aria-label="显示已撤回" checked={withdrawn} onChange={event => { setWithdrawn(event.target.checked); refresh(); }}/>显示已撤回</label>}<span className={styles.toolbarSpacer}/><Button variant="ghost" size="xs" onClick={openPai}><Sparkle/>小Pai新增</Button><label className={styles.search}><MagnifyingGlass size={14} aria-hidden="true"/><input type="search" aria-label={`搜索${activeView.label}`} placeholder="搜索资料" value={query} onChange={event => setQuery(event.target.value)}/></label>{materialKind && <Button size="xs" variant="outline" onClick={() => setMaterial({ categoryId, api, kind: materialKind, item: null })}><Plus/>新增{materialKind === "parameter" ? "参数" : materialKind === "competitor" ? "竞品" : "声音"}</Button>}</div>
    <section className={styles.panel} id={panelId} aria-label={activeView.label}>
      <div className={styles.panelHead}><h2>{activeView.label}</h2><span>{view === "matrix" ? "只读分布" : viewError || loading ? "" : view === "products" ? `${products?.length ?? 0} 个型号` : view === "parameters" ? `${parameters?.length ?? 0} 项参数` : `${relevant.length} 条当前记录`}</span></div>
      {viewError ? <div className={styles.empty} role="alert"><p>{activeView.label}暂不可读：{viewError}</p><Button variant="outline" size="sm" onClick={refresh}>重新读取</Button></div> : loading ? <p className={styles.empty} role="status">正在读取{activeView.label}…</p> : view === "matrix" ? <CategoryMatrix key={`${categoryId}:${reload}`} categoryId={categoryId} api={api} onOpenProduct={id => onOpenWorkbench("products", id)}/> : view === "products" ? products?.length ? <div className={styles.scroll}><table className={styles.table}><thead><tr><th>型号</th><th>用途</th><th/></tr></thead><tbody>{products.filter(item => `${item.name} ${item.purpose}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).map(item => <tr key={item.id}><td><strong>{item.name}</strong></td><td>{item.purpose}</td><td className={styles.actionCell}><Button size="sm" variant="ghost" onClick={() => onOpenWorkbench("products", item.id)}>打开型号<ArrowRight size={14}/></Button></td></tr>)}</tbody></table></div> : <p className={styles.empty}>尚无型号。打开品类工作台建立型号范围。</p> : view === "parameters" ? parameters?.length ? <div className={styles.scroll}><table className={styles.table}><thead><tr><th>参数</th><th>单位</th><th>当前版本</th><th>数据类型</th><th>标准工况</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{parameters.filter(item => `${item.name} ${item.key}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).map(item => <tr key={`${item.parameter_id}:${item.version}`}><td>{item.name}</td><td className={styles.mono}>{item.unit ?? "未登记"}</td><td className={styles.mono}>v{item.version}</td><td>{typeLabels[item.value_type] ?? item.value_type}</td><td>{item.standard_condition ?? "未登记"}</td><td><Button size="xs" variant="ghost" onClick={() => setMaterial({ categoryId, api, kind: "parameter", item })}>编辑</Button></td></tr>)}</tbody></table></div> : <p className={styles.empty}>尚无规格参数。参数名称、单位与工况由规格字典逐项登记。</p> : relevant.length === 0 ? <p className={styles.empty}>尚无{activeView.label}记录。可通过品类小Pai起草，核对后进入共享知识。</p> : view === "competitor" ? <div className={styles.scroll}><table className={`${styles.table} ${styles.competitors}`}><thead><tr><th>竞品</th><th>品牌 / 场景</th><th>数据类型</th><th>报价</th><th>来源</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{relevant.map((item, index) => {
        const id = item.id ?? String(index), opened = inspection?.categoryId === categoryId && inspection.api === api && inspection.id === id;
        const prices = rows(item.content.prices), kinds = [...new Set([...rows(item.content.metrics), ...rows(item.content.features)].map(row => natureLabels[text(row.nature)] ?? "未知"))];
        return <Fragment key={id}><tr><td><button type="button" className={styles.recordTitle} aria-expanded={opened} aria-controls={`${panelId}-${index}-details`} onClick={() => setInspection(opened ? null : { categoryId, api, id })}>{text(item.content.model, text(item.content.brand))}<ArrowUpRight size={12}/></button></td><td>{text(item.content.brand)}{item.content.scenario ? ` · ${text(item.content.scenario)}` : ""}</td><td>{kinds.join(" / ") || "未知"}</td><td className={styles.mono}>{prices.length ? `${text(prices[0].amount, "价格未知")} ${text(prices[0].currency, "币种未知")}${prices.length > 1 ? ` 等 ${prices.length} 条` : ""}` : "价格未知"}</td><td><span className={styles.sourceStatus} data-warning={Boolean(item.source_changes?.length)}>{sourceLabel(item)}</span></td><td className={styles.actionCell}><Button size="xs" variant="ghost" disabled={!item.content || !!item.source_changes?.length} onClick={() => setMaterial({ categoryId, api, kind: "competitor", item })}>{withdrawn ? "查看与恢复" : "编辑"}</Button></td></tr>
        <tr hidden={!opened} id={`${panelId}-${index}-details`}><td colSpan={6}><div className={styles.competitorDetail}><section><h3>报价与口径</h3>{prices.length ? prices.map((price, priceIndex) => <div className={styles.price} key={priceIndex}><span className={styles.mono}>{text(price.amount, "价格未知")} {text(price.currency, "币种未知")}</span><small>{text(price.observed_on, "采集日期未知")} · {price.price_type === "retail" ? "零售" : price.price_type === "promo" ? "促销" : "价格类型未知"}</small><small>含税：{text(price.includes_tax, "未知")} · 含运：{text(price.includes_shipping, "未知")}</small>{typeof price.channel === "string" && price.channel && <small>渠道：{text(price.channel)}</small>}</div>) : <span className={styles.muted}>价格未知</span>}</section><section><h3>规格、性质与工况</h3><CompetitorSpecs item={item} parameters={parameters}/></section><section><h3>来源与记录</h3><span>{sourceLabel(item)}</span><small>{originLabels[item.origin] ?? item.origin} · 记录 v{item.version ?? "未知"}</small>{item.id && !withdrawn && <Button className={styles.segmentAction} type="button" size="xs" variant="outline" onClick={() => setEditing({ categoryId, api, entryId: item.id! })}>维护细分</Button>}</section></div></td></tr></Fragment>;
      })}</tbody></table></div> : view === "voice" ? <div>{relevant.map((item, index) => <article key={item.id ?? index} className={styles.voice}><p>{text(item.content.label)}</p><div className={styles.meta}><span>{text(item.content.source_platform, "平台未登记")}</span><span>{originLabels[item.origin] ?? item.origin}</span>{typeof item.content.sample_size === "number" && <span>样本 {item.content.sample_size}</span>}<span>{sourceLabel(item)}</span><Button size="xs" variant="ghost" disabled={!item.content || !!item.source_changes?.length} onClick={() => setMaterial({ categoryId, api, kind: "voice", item })}>{withdrawn ? "查看与恢复" : "编辑"}</Button></div></article>)}</div> : <div className={styles.scroll}><table className={styles.table}><thead><tr><th>法规 / 认证</th><th>地区与适用范围</th><th>来源状态</th><th>适用性 / 符合性</th></tr></thead><tbody>{relevant.map((item, index) => <tr key={item.id ?? index}><td>{text(item.content.instrument)}<small>{item.content.requirement_kind === "statutory" ? "法定义务" : item.content.requirement_kind === "customer_channel" ? "客户 / 渠道要求" : item.content.requirement_kind === "voluntary_reference" ? "自愿参考" : "要求性质未知"}</small></td><td>{text(item.content.region)}<small>{text(item.content.applicability, "适用范围未知")}</small></td><td>{state(item.content.source_state)}<small>{sourceLabel(item)}</small></td><td>适用性：{state(item.content.applicability_state)}<small>符合性：{state(item.content.compliance_state)}</small></td></tr>)}</tbody></table></div>}
      {view === "competitor" && editedEntryId && <CompetitorSegments key={`${categoryId}:${editedEntryId}`} categoryId={categoryId} entryId={editedEntryId} api={api} onSaved={refresh} onClose={() => setEditing(null)}/>}
      <div className={styles.panelFooter}><span>{view === "competitor" ? "价格保留币种、日期与税运口径；不同工况与性质分别呈现。" : view === "voice" ? "声音按标签和来源平台整理，原始材料可到知识区核对。" : view === "regulation" ? "来源、适用性与符合性分别保留，专业确认进展以各项状态为准。" : view === "parameters" ? "提案与定义引用各自固定的参数版本。" : ""}</span><button type="button" onClick={() => onOpenWorkbench(view === "products" || view === "parameters" ? "products" : "knowledge")}>{view === "products" || view === "parameters" ? "打开品类工作台" : "查看知识与来源"}<ArrowRight size={13} aria-hidden="true"/></button></div>
    </section>
    </>}
    {finding && <DetailSheet title="查找品类提案" onClose={() => setFinding(false)}><h2>{categoryName} · 提案</h2><p>仅显示当前身份可访问的提案。</p><ProposalList categoryId={categoryId} api={api} compact/></DetailSheet>}
    {view === "products" && products && <details className={styles.standardMatch}><summary><Info size={15} aria-hidden="true"/><span>先核对现有型号</span><span>已有规格能否满足？展开核对标准品</span></summary><StandardMatch key={categoryId} categoryId={categoryId} products={products} api={api} onOpenProduct={id => onOpenWorkbench("products", id)}/></details>}
  </div>;
}
