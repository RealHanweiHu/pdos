"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Archive, ArrowClockwise, ArrowRight, CaretRight, Info, Sparkle, UserCircle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/browser-api";
import { ProposalList } from "@/components/proposals/proposal-list";
import { CategoryMatrix } from "@/components/preproject/category-matrix";
import { CompetitorSegments } from "@/components/preproject/competitor-segments";
import { StandardMatch } from "@/components/preproject/standard-match";
import styles from "./category-home.module.css";

type Api = typeof browserApi;
type Product = { id: string; name: string; purpose: string };
type KnowledgeItem = { id?: string; lineage_id?: string; version?: number; kind: string; content: Record<string, unknown>; origin: string; status: string; source_refs?: unknown[]; source_changes?: unknown[] };
type ParameterItem = { parameter_id: string; version: number; key: string; name: string; unit: string | null; value_type: string; standard_condition?: string | null };
type Page<T> = { items: T[]; next_cursor?: string | null };
type ReadErrors = Partial<Record<"products" | "knowledge" | "parameters", string>>;
type ScopedRead<T> = { categoryId: string; api: Api; readVersion: number; value: T };
const views = [{ id: "competitor", label: "竞品库" }, { id: "voice", label: "用户声音" }, { id: "regulation", label: "法规认证" }, { id: "parameters", label: "规格字典" }, { id: "products", label: "型号" }, { id: "matrix", label: "品类矩阵" }] as const;
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
    const page: Page<T> = await api(`${root}?page_size=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
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

export function CategoryHome({ categoryId, categoryName, api, onOpenWorkbench, onOpenPai }: {
  categoryId: string; categoryName: string; api: Api;
  onOpenWorkbench: (bench: "products" | "knowledge", productId?: string) => void;
  onOpenPai: () => void;
}) {
  const [storedProducts, setProducts] = useState<ScopedRead<Product[]> | null>(null);
  const [storedKnowledge, setKnowledge] = useState<ScopedRead<KnowledgeItem[]> | null>(null);
  const [storedParameters, setParameters] = useState<ScopedRead<ParameterItem[]> | null>(null);
  const [storedErrors, setErrors] = useState<ScopedRead<ReadErrors> | null>(null);
  const [editing, setEditing] = useState<{ categoryId: string; api: Api; entryId: string } | null>(null);
  const [reload, setReload] = useState(0);
  const inScope = (read: ScopedRead<unknown> | null) => read?.categoryId === categoryId && read.api === api && read.readVersion === reload;
  const products = inScope(storedProducts) ? storedProducts!.value : null, knowledge = inScope(storedKnowledge) ? storedKnowledge!.value : null, parameters = inScope(storedParameters) ? storedParameters!.value : null, errors: ReadErrors = inScope(storedErrors) ? storedErrors!.value : {};
  const editedEntryId = editing?.categoryId === categoryId && editing.api === api ? editing.entryId : null;
  const [view, setView] = useState<View>("competitor");
  const pipeline = useRef<HTMLElement>(null);
  const panelId = useId();

  useEffect(() => {
    let active = true;
    const failures: ReadErrors = {};
    void Promise.all([
      api<Product[]>(`v1/categories/${categoryId}/products`).then(value => { if (active) setProducts({ categoryId, api, readVersion: reload, value }); }).catch(failure => { failures.products = (failure as Error).message; }),
      readPages<KnowledgeItem>(api, `v1/categories/${categoryId}/knowledge`, () => active).then(value => { if (active) setKnowledge({ categoryId, api, readVersion: reload, value }); }).catch(failure => { failures.knowledge = (failure as Error).message; }),
      readPages<ParameterItem>(api, `v1/categories/${categoryId}/parameters`, () => active).then(value => { if (active) setParameters({ categoryId, api, readVersion: reload, value }); }).catch(failure => { failures.parameters = (failure as Error).message; }),
    ]).then(() => { if (active) setErrors({ categoryId, api, readVersion: reload, value: failures }); });
    return () => { active = false; };
  }, [api, categoryId, reload]);

  function refresh() { setProducts(null); setKnowledge(null); setParameters(null); setErrors(null); setReload(value => value + 1); }
  function showProposals() { pipeline.current?.scrollIntoView({ block: "start", behavior: "instant" }); pipeline.current?.focus({ preventScroll: true }); }
  const activeView = views.find(item => item.id === view)!;
  const relevant = knowledge?.filter(item => item.kind === view) ?? [];
  const boundary = knowledge?.find(item => item.kind === "boundary" && item.status === "active");
  const viewError = view === "products" ? errors.products : view === "parameters" ? errors.parameters : view === "matrix" ? "" : errors.knowledge;
  const loading = view === "products" ? products === null : view === "parameters" ? parameters === null : view === "matrix" ? false : knowledge === null;

  return <div className={styles.page}>
    <div className={styles.roleNote}><UserCircle size={16} aria-hidden="true"/><span>立项前 · 产品管理工作区。项目工作从项目入口继续，提案经具名 G0 评审后承接到项目。</span></div>
    <header className={styles.categoryHead}>
      <div className={styles.title}><h1>{categoryName}</h1><p>{boundary ? `边界：${text(boundary.content.definition)}` : errors.knowledge ? "品类边界暂不可读" : knowledge === null ? "正在读取品类边界…" : "品类边界尚未登记"}</p><p>立项前只回答四个问题：值不值得做、做成什么样、走哪条路、还有什么不确定。</p></div>
      <div className={styles.actions}><span className={styles.badge}>立项前</span><Button variant="outline" onClick={showProposals}><Archive/>已有提案</Button><Button onClick={onOpenPai}><Sparkle/>立项提案</Button></div>
    </header>
    <nav className={styles.path} aria-label="立项路径"><span className={styles.muted}>立项路径</span>{["品类知识", "立项提案", "G0 立项评审", "项目（通过后生成）"].map((label, index) => <span key={label} className={styles.pathItem}>{index > 0 && <CaretRight size={13} aria-hidden="true"/>}<span className={styles.step}>{label}</span></span>)}</nav>
    <section ref={pipeline} tabIndex={-1} className={styles.panel} aria-label="立项提案"><div className={styles.panelHead}><h2>提案管道</h2><span>一案一页，放弃不留虚假项目</span></div><div className={styles.pipelineBody}><ProposalList key={`${categoryId}:${reload}`} categoryId={categoryId} api={api}/></div></section>
    <div className={styles.tabs} role="group" aria-label="品类知识视图">{views.map(item => <button type="button" key={item.id} aria-pressed={view === item.id} aria-controls={panelId} onClick={() => setView(item.id)}>{item.label}</button>)}<button type="button" className={styles.refresh} onClick={refresh} aria-label="刷新品类资料" title="刷新品类资料"><ArrowClockwise size={14} aria-hidden="true"/></button></div>
    <section className={styles.panel} id={panelId} aria-label={activeView.label}>
      <div className={styles.panelHead}><h2>{activeView.label}</h2><span>{view === "matrix" ? "只读分布" : viewError || loading ? "" : view === "products" ? `${products?.length ?? 0} 个型号` : view === "parameters" ? `${parameters?.length ?? 0} 项参数` : `${relevant.length} 条当前记录`}</span></div>
      {viewError ? <div className={styles.empty} role="alert"><p>{activeView.label}暂不可读：{viewError}</p><Button variant="outline" size="sm" onClick={refresh}>重新读取</Button></div> : loading ? <p className={styles.empty} role="status">正在读取{activeView.label}…</p> : view === "matrix" ? <CategoryMatrix key={`${categoryId}:${reload}`} categoryId={categoryId} api={api} onOpenProduct={id => onOpenWorkbench("products", id)}/> : view === "products" ? products?.length ? <div className={styles.scroll}><table className={styles.table}><thead><tr><th>型号</th><th>用途</th><th/></tr></thead><tbody>{products.map(item => <tr key={item.id}><td><strong>{item.name}</strong></td><td>{item.purpose}</td><td className={styles.actionCell}><Button size="sm" variant="ghost" onClick={() => onOpenWorkbench("products", item.id)}>打开型号<ArrowRight size={14}/></Button></td></tr>)}</tbody></table></div> : <p className={styles.empty}>尚无型号。打开品类工作台建立型号范围。</p> : view === "parameters" ? parameters?.length ? <div className={styles.scroll}><table className={styles.table}><thead><tr><th>参数</th><th>单位</th><th>当前版本</th><th>数据类型</th><th>标准工况</th></tr></thead><tbody>{parameters.map(item => <tr key={`${item.parameter_id}:${item.version}`}><td>{item.name}</td><td className={styles.mono}>{item.unit ?? "未登记"}</td><td className={styles.mono}>v{item.version}</td><td>{typeLabels[item.value_type] ?? item.value_type}</td><td>{item.standard_condition ?? "未登记"}</td></tr>)}</tbody></table></div> : <p className={styles.empty}>尚无规格参数。参数名称、单位与工况由规格字典逐项登记。</p> : relevant.length === 0 ? <p className={styles.empty}>尚无{activeView.label}记录。可通过品类小Pai起草，核对后进入共享知识。</p> : view === "competitor" ? <div className={styles.scroll}><table className={`${styles.table} ${styles.competitors}`}><thead><tr><th>竞品</th><th>价格 · 原口径</th><th>规格、性质与工况</th><th>来源 / 未知原因</th></tr></thead><tbody>{relevant.map((item, index) => <tr key={item.id ?? index}><td><strong>{text(item.content.brand)} {text(item.content.model)}</strong><small>{originLabels[item.origin] ?? item.origin}</small></td><td>{rows(item.content.prices).length ? rows(item.content.prices).map((price, priceIndex) => <div className={styles.price} key={priceIndex}><span className={styles.mono}>{text(price.amount, "价格未知")} {text(price.currency, "币种未知")}</span><small>{text(price.observed_on, "采集日期未知")} · {price.price_type === "retail" ? "零售" : price.price_type === "promo" ? "促销" : "价格类型未知"}</small><small>含税：{text(price.includes_tax, "未知")} · 含运：{text(price.includes_shipping, "未知")}</small>{typeof price.channel === "string" && price.channel && <small>渠道：{text(price.channel)}</small>}</div>) : <span className={styles.muted}>价格未知</span>}</td><td><CompetitorSpecs item={item} parameters={parameters}/></td><td><span className={styles.badge} data-warning={Boolean(item.source_changes?.length)}>{sourceLabel(item)}</span><small>记录 v{item.version ?? "未知"}</small>{item.id && <Button className={styles.segmentAction} type="button" size="xs" variant="outline" onClick={() => setEditing({ categoryId, api, entryId: item.id! })}>维护细分</Button>}</td></tr>)}</tbody></table></div> : view === "voice" ? <div>{relevant.map((item, index) => <article key={item.id ?? index} className={styles.voice}><p>{text(item.content.label)}</p><div className={styles.meta}><span>{text(item.content.source_platform, "平台未登记")}</span><span>{originLabels[item.origin] ?? item.origin}</span>{typeof item.content.sample_size === "number" && <span>样本 {item.content.sample_size}</span>}<span>{sourceLabel(item)}</span></div></article>)}</div> : <div className={styles.scroll}><table className={styles.table}><thead><tr><th>法规 / 认证</th><th>地区与适用范围</th><th>来源状态</th><th>适用性 / 符合性</th></tr></thead><tbody>{relevant.map((item, index) => <tr key={item.id ?? index}><td>{text(item.content.instrument)}<small>{item.content.requirement_kind === "statutory" ? "法定义务" : item.content.requirement_kind === "customer_channel" ? "客户 / 渠道要求" : item.content.requirement_kind === "voluntary_reference" ? "自愿参考" : "要求性质未知"}</small></td><td>{text(item.content.region)}<small>{text(item.content.applicability, "适用范围未知")}</small></td><td>{state(item.content.source_state)}<small>{sourceLabel(item)}</small></td><td>适用性：{state(item.content.applicability_state)}<small>符合性：{state(item.content.compliance_state)}</small></td></tr>)}</tbody></table></div>}
      {view === "competitor" && editedEntryId && <CompetitorSegments key={`${categoryId}:${editedEntryId}`} categoryId={categoryId} entryId={editedEntryId} api={api} onSaved={refresh} onClose={() => setEditing(null)}/>}
      <div className={styles.panelFooter}><span>{view === "competitor" ? "价格保留币种、日期与税运口径；不同工况与性质分别呈现。" : view === "voice" ? "声音按标签和来源平台整理，原始材料可到知识区核对。" : view === "regulation" ? "来源、适用性与符合性分别保留，专业确认进展以各项状态为准。" : view === "parameters" ? "提案与定义引用各自固定的参数版本。" : ""}</span><button type="button" onClick={() => onOpenWorkbench(view === "products" || view === "parameters" ? "products" : "knowledge")}>{view === "products" || view === "parameters" ? "打开品类工作台" : "查看知识与来源"}<ArrowRight size={13} aria-hidden="true"/></button></div>
    </section>
    {products && <details className={styles.standardMatch}><summary><Info size={15} aria-hidden="true"/><span>先核对现有型号</span><span>已有规格能否满足？展开核对标准品</span></summary><StandardMatch key={categoryId} categoryId={categoryId} products={products} api={api} onOpenProduct={id => onOpenWorkbench("products", id)}/></details>}
  </div>;
}
