"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { readKnowledgeLibrary, readKnowledgeLibraryProducts } from "@/lib/knowledge-library";
import type { KnowledgeLibraryApi, KnowledgeLibraryProduct } from "@/lib/knowledge-library";
import type { KnowledgeCandidate, KnowledgeHistory, KnowledgeRule, KnowledgeTarget, KnowledgeView } from "@/lib/knowledge-experience";
import type { WorkSource } from "@/lib/project-work";
import { KnowledgeExperience } from "./knowledge-experience";
import styles from "./knowledge-library.module.css";

type Props = { api: KnowledgeLibraryApi; categoryId: string; categoryName: string; principalId: string; readVersion?: number };
type Choice = { api: KnowledgeLibraryApi; productId: string | null };
type Kind = "all" | "candidate" | "rule";
type Entry = { kind: "candidate"; value: KnowledgeCandidate } | { kind: "rule"; value: KnowledgeRule };
const usabilityNames = { current: "当前可用", not_yet_effective: "尚未生效", expired: "已过有效期", needs_recheck: "需要重核" };
const decisionNames = { applicable: "适用于固定配置及用途", not_applicable: "不适用", unknown: "未知", conflicted: "存在冲突" };
const configurationNames = { engineering_configuration: "工程配置", process_revision: "制造配置" };
const originNames = { human: "人工来源", ai: "AI 来源" };
const natureNames = { synthetic: "合成资料（synthetic）", real: "真实资料（real）" };
const targetName = (target: KnowledgeTarget, configurations: KnowledgeView["configurations"] = []) => `${configurationNames[target.kind]} · ${configurations.find(row => row.kind === target.kind && row.id === target.id && row.revision === target.revision)?.name ?? "固定配置"} · v${target.revision}`;
const projectName = (id: string | null, projects: KnowledgeView["projects"] = []) => id === null ? "未限定项目的候选" : projects.find(row => row.id === id)?.name ?? "固定项目（名称未取得）";

export function KnowledgeLibrary(props: Props) {
  return <ScopedKnowledgeLibrary key={JSON.stringify([props.categoryId, props.principalId, props.readVersion ?? 0])} {...props} />;
}

function ScopedKnowledgeLibrary({ api, categoryId, categoryName, principalId }: Props) {
  const [attempt, setAttempt] = useState(0);
  const [productsReading, setProductsReading] = useState<{ api: KnowledgeLibraryApi; attempt: number; data: KnowledgeLibraryProduct[] | null; error: string } | null>(null);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [reading, setReading] = useState<{ api: KnowledgeLibraryApi; attempt: number; choice: Choice | null; productId: string | null; data: KnowledgeView | null; error: string } | null>(null);
  const [filters, setFilters] = useState<{ api: KnowledgeLibraryApi; attempt: number; choice: Choice | null; productId: string | null; query: string; kind: Kind } | null>(null);
  const [selection, setSelection] = useState<{ api: KnowledgeLibraryApi; attempt: number; choice: Choice | null; productId: string | null; kind: Entry["kind"]; id: string; revision: number } | null>(null);
  const [workbench, setWorkbench] = useState<{ api: KnowledgeLibraryApi; attempt: number; choice: Choice | null; product: KnowledgeLibraryProduct } | null>(null);
  const productsState = productsReading?.api === api && productsReading.attempt === attempt ? productsReading : null;
  const products = productsState?.data ?? null;
  const activeChoice = choice?.api === api ? choice : null;
  const productId = activeChoice?.productId ?? null;
  const selectedProduct = productId === null ? undefined : products?.find(row => row.id === productId);
  const scopeReady = productId === null || selectedProduct !== undefined;
  const current = scopeReady && reading?.api === api && reading.attempt === attempt && reading.choice === activeChoice && reading.productId === productId ? reading : null;
  const data = current?.data ?? null, error = current?.error ?? "";
  const manager = data && workbench?.api === api && workbench.attempt === attempt && workbench.choice === activeChoice && workbench.product === selectedProduct ? workbench : null;
  const filter = filters?.api === api && filters.attempt === attempt && filters.choice === activeChoice && filters.productId === productId ? filters : null;
  const query = filter?.query ?? "", kind = filter?.kind ?? "all";
  const entries: Entry[] = data ? [...data.candidates.map(value => ({ kind: "candidate" as const, value })), ...data.rules.map(value => ({ kind: "rule" as const, value }))] : [];
  const needle = query.trim().toLocaleLowerCase();
  const visible = entries.filter(entry => (kind === "all" || entry.kind === kind) && (!needle || (entry.kind === "candidate" ? [entry.value.title, entry.value.lesson, entry.value.evidence_summary, entry.value.applicability_hypothesis] : [entry.value.title, entry.value.rule_text, entry.value.applicability.purpose, entry.value.applicability.adopted_rule]).join("\n").toLocaleLowerCase().includes(needle)));
  const selected = selection?.api === api && selection.attempt === attempt && selection.choice === activeChoice && selection.productId === productId ? visible.find(entry => entry.kind === selection.kind && entry.value.id === selection.id && entry.value.revision === selection.revision) : undefined;
  const live = useRef<{ api: KnowledgeLibraryApi; attempt: number; choice: Choice | null; productId: string | null; scopeReady: boolean } | null>(null);
  useLayoutEffect(() => {
    const input = { api, attempt, choice: activeChoice, productId, scopeReady }; live.current = input;
    return () => { if (live.current === input) live.current = null; };
  }, [api, attempt, activeChoice, productId, scopeReady]);
  useEffect(() => {
    let active = true;
    const isCurrent = () => active && live.current?.api === api && live.current.attempt === attempt;
    void readKnowledgeLibraryProducts(api, { categoryId, principalId, productId: null }).then(value => {
      if (isCurrent()) setProductsReading({ api, attempt, data: value, error: "" });
    }).catch(failure => {
      if (isCurrent()) setProductsReading({ api, attempt, data: null, error: failure instanceof Error ? failure.message : "可读型号未完整取得。" });
    });
    return () => { active = false; };
  }, [api, categoryId, principalId, attempt]);
  useEffect(() => {
    if (!scopeReady) return;
    let active = true;
    const isCurrent = () => active && live.current?.api === api && live.current.attempt === attempt && live.current.choice === activeChoice && live.current.productId === productId && live.current.scopeReady;
    void readKnowledgeLibrary(api, { categoryId, principalId, productId }).then(value => {
      if (isCurrent()) setReading({ api, attempt, choice: activeChoice, productId, data: value, error: "" });
    }).catch(failure => {
      if (isCurrent()) setReading({ api, attempt, choice: activeChoice, productId, data: null, error: failure instanceof Error ? failure.message : "经验候选和配置规则未完整取得。" });
    });
    return () => { active = false; };
  }, [api, categoryId, principalId, attempt, activeChoice, productId, scopeReady]);
  const refresh = () => setAttempt(value => value + 1);
  const changeFilter = (next: Partial<{ query: string; kind: Kind }>) => { setFilters({ api, attempt, choice: activeChoice, productId, query, kind, ...next }); setSelection(null); };
  const openWorkbench = () => { if (selectedProduct && data && live.current?.api === api && live.current.attempt === attempt && live.current.choice === activeChoice && live.current.productId === selectedProduct.id && live.current.scopeReady) setWorkbench({ api, attempt, choice: activeChoice, product: selectedProduct }); };
  return <section className={styles.library} aria-label="知识库">
    <header className={styles.heading}><div><h1>知识库</h1><p>{categoryName} · {productId === null ? "品类经验候选" : selectedProduct?.name ?? "所选型号待核对"}</p></div><div className={styles.actions}><Button type="button" size="sm" variant="outline" onClick={refresh}>刷新知识资料</Button>{selectedProduct && data && !manager && <Button type="button" size="sm" variant="outline" onClick={openWorkbench}>记录 / 发布办理</Button>}</div></header>
    <div className={styles.toolbar}><label>读取范围<select aria-label="知识读取范围" value={productId ?? ""} disabled={!products} onChange={event => { const id = event.target.value; if (!id || products?.some(row => row.id === id)) { setChoice({ api, productId: id || null }); setSelection(null); setWorkbench(null); } }}><option value="">品类候选（不选型号）</option>{products?.map(product => <option key={product.id} value={product.id}>{product.name}</option>)}</select></label><p>{products ? `本次返回 ${products.length} 个可读型号，不作为型号总数。` : productsState?.error ? `可读型号暂不可读：${productsState.error}` : "正在读取可选择的真实型号…"}</p></div>
    {productId === null && <p className={styles.note}>当前只读品类候选。明确选择型号后，读取该范围候选与具体配置规则；品类级记录表单尚未接入。</p>}
    {!scopeReady ? <div className={styles.notice} role={productsState?.error || products ? "alert" : "status"}><p>{productsState?.error ? `所选型号无法重验：${productsState.error}` : products ? "所选型号已不在本次可读列表中，旧知识资料已隐藏。" : "正在重新核对所选型号，旧候选与规则已隐藏。"}</p><Button type="button" size="xs" variant="outline" onClick={() => { setChoice({ api, productId: null }); setWorkbench(null); }}>返回品类候选</Button></div> : error ? <div className={styles.notice} role="alert"><p>知识资料暂不可读：{error}</p><Button type="button" size="xs" variant="outline" onClick={refresh}>重新读取知识资料</Button></div> : !data ? <p className={styles.notice} role="status">正在读取{productId === null ? "品类候选" : "所选型号候选与规则"}…</p> : manager ? <section className={styles.reading} aria-label="已选型号知识办理"><div className={styles.actions}><Button type="button" size="sm" variant="outline" onClick={() => setWorkbench(null)}>返回知识目录</Button></div><p className={styles.context}>仅在已选型号的原工作台办理；记录与发布资格、固定版本及具名确认由既有服务器流程核对。</p><KnowledgeExperience api={api} categoryId={categoryId} product={{ id: manager.product.id, revision: manager.product.revision }} principalId={principalId} projectId={null} onSaved={refresh} /></section> : <>
      <div className={styles.filters}><label>查询本次返回内容<input aria-label="查询本次知识" value={query} maxLength={160} onChange={event => changeFilter({ query: event.target.value })} placeholder="标题、经验、规则或用途" /></label><label>类型<select aria-label="知识类型" value={kind} onChange={event => { if (["all", "candidate", "rule"].includes(event.target.value)) changeFilter({ kind: event.target.value as Kind }); }}><option value="all">候选与规则</option><option value="candidate">经验候选</option><option value="rule">正式配置规则</option></select></label></div>
      <p className={styles.note}>本次返回候选 {data.candidates.length} 条、规则 {data.rules.length} 条；筛选显示 {visible.length} 条。查询与筛选只作用于本次返回内容，非全局检索或总数。读取原时点：<time dateTime={data.as_of}>{data.as_of}</time>。</p>
      {visible.length ? <div className={styles.scroll} role="region" aria-label="本次知识候选与规则" tabIndex={0}><table className={styles.table}><thead><tr><th>标题 / 固定版本</th><th>类型 / 性质</th><th>服务器状态</th><th>固定适用判断</th><th>查看</th></tr></thead><tbody>{visible.map(entry => <tr key={`${entry.kind}:${entry.value.id}`} data-selected={selected?.kind === entry.kind && selected.value === entry.value}><td><strong>{entry.value.title}</strong><small>固定 v{entry.value.revision}</small></td><td>{entry.kind === "candidate" ? "经验候选" : "正式配置规则"}<small>{entry.kind === "candidate" ? originNames[entry.value.origin] : natureNames[entry.value.nature]}</small></td><td>{entry.kind === "candidate" ? "候选，尚非正式规则" : <>{usabilityNames[entry.value.usability.state]}<small>{entry.value.usability.state}</small></>}</td><td>{entry.kind === "candidate" ? "适用性仅为假设" : <>{decisionNames[entry.value.applicability.decision]}<small>{targetName(entry.value.applicability.target, data.configurations)}</small></>}</td><td><Button type="button" size="xs" variant="outline" aria-label={`展开${entry.kind === "candidate" ? "候选" : "规则"} ${entry.value.id} v${entry.value.revision}`} aria-pressed={selected?.kind === entry.kind && selected.value === entry.value} onClick={() => setSelection({ api, attempt, choice: activeChoice, productId, kind: entry.kind, id: entry.value.id, revision: entry.value.revision })}>展开详情</Button></td></tr>)}</tbody></table></div> : <p className={styles.notice}>{entries.length ? "本次返回内容没有匹配项，不代表其他知识不存在。" : "本次读集没有返回候选或规则，不推断全品类或其他型号没有知识。"}</p>}
      {selected && <section className={styles.selected} aria-label="已选知识详情"><header className={styles.detailHeading}><h2>{selected.kind === "candidate" ? "经验候选详情" : "固定配置规则详情"}</h2><Button type="button" size="xs" variant="outline" onClick={() => setSelection(null)}>收起知识详情</Button></header>{selected.kind === "candidate" ? <KnowledgeCandidateReading value={selected.value} projects={data.projects} /> : <KnowledgeRuleReading value={selected.value} projects={data.projects} configurations={data.configurations} />}</section>}
      <p className={styles.foot}>候选不等于正式规则。“当前可用”保留服务器判定，仅限原固定配置、用途、条件与时限；不自动适用于全部配置或授予发布资格。历史仅含服务器返回的固定版本元数据，不补旧正文。</p>
    </>}
  </section>;
}

export function KnowledgeCandidateReading({ value, projects = [] }: { value: KnowledgeCandidate; projects?: KnowledgeView["projects"] }) {
  return <article className={styles.reading} aria-label="经验候选正文"><h3>{value.title} · v{value.revision}</h3><p className={styles.context}>经验候选 · {originNames[value.origin]} · {projectName(value.project_id, projects)}。适用性仍为假设。</p><TextSection label="经验与教训" text={value.lesson} /><TextSection label="证据与实际结果摘要" text={value.evidence_summary} /><TextSection label="适用性假设与未知范围" text={value.applicability_hypothesis} /><p className={styles.context}>保存原时点：<time dateTime={value.created_at}>{value.created_at}</time></p><Sources values={value.sources} /><details className={styles.details}><summary>实际结果固定回执（{value.result_receipts.length} 条）</summary>{value.result_receipts.length ? <ul>{value.result_receipts.map(ref => <li key={ref.receipt_id}>{ref.receipt_id}</li>)}</ul> : <p>原列表为空，不推断无实际结果。</p>}</details><Identities value={value} /><History values={value.history} /></article>;
}

export function KnowledgeRuleReading({ value, projects = [], configurations = [] }: { value: KnowledgeRule; projects?: KnowledgeView["projects"]; configurations?: KnowledgeView["configurations"] }) {
  const assessment = value.applicability;
  return <article className={styles.reading} aria-label="固定配置规则正文"><h3>{value.title} · v{value.revision}</h3><p className={styles.context}>正式配置规则 · {natureNames[value.nature]} · {projectName(value.project_id, projects)}</p><p className={styles.state}>服务器可用状态：{usabilityNames[value.usability.state]}（{value.usability.state}）</p><p className={styles.context}>固定适用判断：{decisionNames[assessment.decision]}（{assessment.decision}）。可用状态与适用判断分别保留，不扩张至其他配置。</p><TextSection label="规则内容" text={value.rule_text} /><dl className={styles.facts}><div><dt>固定目标配置</dt><dd>{targetName(assessment.target, configurations)}</dd></div><div><dt>具体用途</dt><dd className={styles.prose}>{assessment.purpose}</dd></div><div><dt>原生效时点</dt><dd>{assessment.valid_from}</dd></div><div><dt>原有效期截至</dt><dd>{assessment.valid_until === null ? "未设截至时点（原值为空）" : assessment.valid_until}</dd></div></dl><TextList label="相对候选的差异" values={assessment.differences} /><TextSection label="本配置采用的规则" text={assessment.adopted_rule} /><TextList label="适用条件" values={assessment.conditions} /><TextSection label="具名判断依据" text={assessment.rationale} /><details className={styles.details}><summary>服务器可用性原因码（{value.usability.reason_codes.length} 条）</summary><OriginalList values={value.usability.reason_codes} /></details><Sources values={value.sources} /><details className={styles.details}><summary>固定候选、评估人与配置身份</summary><dl className={styles.identities}><div><dt>固定目标</dt><dd>{assessment.target.kind} · {assessment.target.id} · v{assessment.target.revision}</dd></div><div><dt>固定原候选</dt><dd>{value.candidate.id} · v{value.candidate.revision}</dd></div><div><dt>固定候选版本标识</dt><dd>{value.candidate_version_id}</dd></div><div><dt>评估固定候选版本</dt><dd>{assessment.candidate_version.id} · v{assessment.candidate_version.revision}</dd></div><div><dt>原评估人标识</dt><dd>{assessment.assessor_id}</dd></div><div><dt>原撤回原因字段</dt><dd>{assessment.withdrawal_reason === null ? "原值为空；不据此重判当前有效性" : assessment.withdrawal_reason}</dd></div></dl></details><Identities value={value} /><History values={value.history} /></article>;
}

function TextSection({ label, text }: { label: string; text: string }) { return <section className={styles.textSection}><h4>{label}</h4><p className={styles.prose}>{text}</p></section>; }
function OriginalList({ values }: { values: string[] }) { return values.length ? <ul>{values.map((value, index) => <li key={index} className={styles.prose}>{value}</li>)}</ul> : <p>原列表为空，不补充推断。</p>; }
function TextList({ label, values }: { label: string; values: string[] }) { return <section className={styles.textSection}><h4>{label}</h4><OriginalList values={values} /></section>; }
function Sources({ values }: { values: WorkSource[] }) { return <details className={styles.details}><summary>原固定来源（{values.length} 条）</summary><ul>{values.map((value, index) => <li key={index}>{value.kind} · {value.id} · v{value.revision}<small>原定位：{value.position}</small></li>)}</ul></details>; }
function Identities({ value }: { value: KnowledgeCandidate | KnowledgeRule }) { return <details className={styles.details}><summary>固定身份、原署名与保存范围</summary><dl className={styles.identities}><div><dt>记录 / 版本标识</dt><dd>{value.id} · v{value.revision}<small>{value.version_id}</small></dd></div><div><dt>固定项目标识</dt><dd>{value.project_id ?? "原值为空，未限定项目"}</dd></div><div><dt>记录属主</dt><dd>{value.owner_id}</dd></div><div><dt>原署名标识</dt><dd>{value.author_id}</dd></div><div><dt>可读范围原值</dt><dd>{value.visibility}</dd></div><div><dt>保存原时点</dt><dd>{value.created_at}</dd></div></dl></details>; }
function History({ values }: { values: KnowledgeHistory[] }) { return <details className={styles.details}><summary>固定版本历史（{values.length} 条元数据）</summary><p>以下仅是已返回的版本、原署名、时点与回执；未读取历史正文。</p><div className={styles.scroll} role="region" aria-label="知识固定版本历史" tabIndex={0}><table className={styles.table}><thead><tr><th>固定版本</th><th>原署名标识</th><th>保存原时点</th><th>原回执</th></tr></thead><tbody>{values.map(value => <tr key={value.id}><td>v{value.revision}<small>{value.id}</small></td><td>{value.actor_id}</td><td>{value.created_at}</td><td>{value.receipt_id}</td></tr>)}</tbody></table></div></details>; }
