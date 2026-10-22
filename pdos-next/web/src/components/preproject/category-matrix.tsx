"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowClockwise, ArrowRight } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { browserApi } from "@/lib/browser-api";
import { categoryMatrixPath, isCategoryMatrixResponse, matrixBreaks, type CategoryMatrixResponse, type MatrixBand, type MatrixBasis, type MatrixPlacement, type MatrixSegment } from "@/lib/category-matrix";
import { ProposalSourceInspector } from "./proposal-source-inspector";
import styles from "./category-matrix.module.css";

type Props = { categoryId: string; api: typeof browserApi; onOpenProduct: (productId: string) => void };
const priceTypes: Record<string, string> = { retail: "零售", wholesale: "批发", promo: "促销", target: "目标价", unknown: "未知" };
const reasonLabels: Record<string, string> = {
  segment_missing: "未登记明确的细分关联", segment_unavailable: "固定细分不可读", segment_withdrawn: "细分已撤回",
  price_unknown: "价格未知", price_invalid: "价格不可用", price_source_unavailable: "价格来源不可用", currency_missing: "币种未提供",
  price_basis_missing: "价格类型未提供", price_date_missing: "价格日期未提供", source_unavailable: "来源不可用", source_missing: "来源未登记",
  g0_price_source_unavailable: "未取得可读的固定立项价格来源", target_price_g0_mismatch: "目标价格与固定立项口径不一致",
};
const limitationLabels: Record<string, string> = {
  competitor_segment_link_unavailable: "未登记明确细分关联的竞品保留在未落格列表。",
  competitor_segments_missing: "部分竞品尚未关联固定细分。",
  empty_cells_are_not_market_gaps: "空单元格仅说明当前读集暂无可读记录。",
  target_price_requires_readable_matching_g0_source: "我方目标价格按可读、口径一致的固定立项来源落格。",
  unknown_basis_dimensions_are_separate_null_groups: "未知价格维度单独保留，完整口径分别展示。",
};
const print = (value: unknown) => value === null || value === undefined || value === "" ? "未知" : typeof value === "boolean" ? value ? "是" : "否" : typeof value === "object" ? JSON.stringify(value) : String(value);

function bandLabel(band: MatrixBand) {
  if (band.lower === null) return `${band.upper_inclusive ? "≤" : "<"}${band.upper}`;
  if (band.upper === null) return `${band.lower_inclusive ? "≥" : ">"}${band.lower}`;
  return `${band.lower_inclusive ? "[" : "("}${band.lower}, ${band.upper}${band.upper_inclusive ? "]" : ")"}`;
}

function PriceBasis({ value }: { value: MatrixBasis }) {
  return <dl className={styles.basis}>{[["币种", value.currency], ["价格类型", value.basis ? priceTypes[value.basis] ?? value.basis : null], ["日期", value.as_of], ["含税", value.includes_tax], ["含运费", value.includes_shipping], ["地区", value.region], ["渠道", value.channel]].map(([label, content]) => <div key={String(label)}><dt>{label}</dt><dd>{print(content)}</dd></div>)}</dl>;
}

function Placement({ item, onOpenProduct }: { item: MatrixPlacement; onOpenProduct: Props["onOpenProduct"] }) {
  const own = item.subject.type === "product", price = item.price;
  return <div className={styles.placement} data-kind={item.subject.type}>
    <div className={styles.objectHeading}>{own ? <button type="button" onClick={() => onOpenProduct(item.subject.id)}>{item.subject.label}<ArrowRight size={11} aria-hidden="true"/></button> : <span>{item.subject.label}</span>}<span className={styles.amount}>{price.amount == null ? "价格未知" : print(price.amount)} · {price.currency == null ? "币种未知" : print(price.currency)}</span></div>
    <details className={styles.provenance}><summary>原口径与来源</summary>
      <dl className={styles.priceDetails}>{[["对象版本", item.subject.revision], ["价格类型", price.basis ?? price.price_type], ["价格日期", price.as_of ?? price.observed_on], ["含税", price.includes_tax], ["含运费", price.includes_shipping], ["地区", price.region], ["渠道", price.channel]].map(([label, content]) => <div key={String(label)}><dt>{print(label)}</dt><dd>{print(content)}</dd></div>)}</dl>
      <ProposalSourceInspector sources={item.source_refs} label="价格来源"/>
      {price.g0_source !== undefined && <details className={styles.fixedSource}><summary>固定立项价格依据</summary><pre>{JSON.stringify(price.g0_source, null, 2)}</pre></details>}
    </details>
  </div>;
}

function Segment({ value }: { value: MatrixSegment }) {
  return <><strong>{value.label ?? "细分名称不可读"}</strong><span className={styles.segmentVersion}>固定 v{value.version} · {value.status === "active" ? "未撤回" : print(value.status)}</span><div className={styles.segmentSource}><ProposalSourceInspector sources={value.source_refs} label="细分来源"/></div></>;
}

export function CategoryMatrix(props: Props) {
  return <ScopedCategoryMatrix key={props.categoryId} {...props}/>;
}

function ScopedCategoryMatrix({ categoryId, api, onOpenProduct }: Props) {
  const [input, setInput] = useState("150, 300");
  const [request, setRequest] = useState({ breaks: ["150", "300"], attempt: 0 });
  const [data, setData] = useState<CategoryMatrixResponse | null>(null);
  const [error, setError] = useState("");
  const [inputError, setInputError] = useState("");
  const generation = useRef(0);
  useEffect(() => {
    let active = true;
    const own = ++generation.current;
    void api<unknown>(categoryMatrixPath(categoryId, request.breaks)).then(value => {
      if (!active || generation.current !== own) return;
      if (!isCategoryMatrixResponse(value, categoryId, request.breaks)) throw new Error("矩阵结果与当前品类、价格分界不一致，或资料不完整，请重新读取。");
      setData(value); setError("");
    }).catch(failure => { if (active && generation.current === own) { setData(null); setError((failure as Error).message); } });
    return () => { active = false; };
  }, [api, categoryId, request]);

  function load(breaks: string[]) {
    generation.current++; setData(null); setError(""); setInputError("");
    setRequest(previous => ({ breaks, attempt: previous.attempt + 1 }));
  }
  return <div className={styles.content}>
    <form className={styles.toolbar} onSubmit={event => { event.preventDefault(); try { load(matrixBreaks(input)); } catch (failure) { setInputError((failure as Error).message); } }}>
      <label>价格分界<input type="text" inputMode="decimal" value={input} onChange={event => setInput(event.target.value)} aria-describedby="category-matrix-break-help" placeholder="150, 300"/></label>
      <Button size="xs" variant="outline">查看分布</Button>
      <Button type="button" size="xs" variant="ghost" onClick={() => load(request.breaks)}><ArrowClockwise size={12} aria-hidden="true"/>刷新</Button>
      <p id="category-matrix-break-help">分界仅调整展示；每格下界含、上界不含，按各组原币种读取。</p>
    </form>
    {inputError && <p className={styles.inputError} role="alert">{inputError}</p>}
    {error ? <div className={styles.notice} role="alert"><p>品类矩阵暂不可读：{error}</p><Button type="button" size="xs" variant="outline" onClick={() => load(request.breaks)}>重新读取矩阵</Button></div> : !data ? <p className={styles.notice} role="status">正在读取当前品类的细分与价格分布…</p> : <>
      <p className={styles.scopeNote}>当前分界：{data.display.breaks.join("、")}。<span className={styles.ownLegend}>我方型号</span><span className={styles.competitorLegend}>竞品</span>；价格口径分别呈现。</p>
      <div className={styles.coverage} aria-label="矩阵可见范围"><span>可见型号 <b>{data.coverage.visible_products}</b></span><span>可见竞品 <b>{data.coverage.visible_competitors}</b></span><span>已落格对象 <b>{data.coverage.placed_subjects}</b></span><span>未落格对象 <b>{data.coverage.unplaced_subjects}</b></span>{data.coverage.partially_placed_subjects > 0 && <span>部分价格已落格 <b>{data.coverage.partially_placed_subjects}</b></span>}<span>落格记录 <b>{data.coverage.placements}</b></span></div>
      {data.groups.map((group, index) => <section className={styles.group} key={group.id} aria-label={`价格口径 ${index + 1}`}>
        <header className={styles.groupHeading}><h3>价格口径 {index + 1}</h3><PriceBasis value={group.basis}/></header>
        <div className={styles.matrixScroll}><table className={styles.matrix} style={{ minWidth: 120 + data.display.bands.length * 180 }}><caption className="sr-only">{group.basis.currency ?? "币种未知"}价格带与固定细分分布</caption><thead><tr><th scope="col">细分 \ 价格带</th>{data.display.bands.map(band => <th key={band.id} scope="col">{bandLabel(band)}<span>{group.basis.currency ?? "币种未知"}</span></th>)}</tr></thead><tbody>{group.rows.map(row => <tr key={`${row.segment.lineage_id}:${row.segment.version}`}><th scope="row"><Segment value={row.segment}/></th>{data.display.bands.map(band => {
          const cell = row.cells.find(item => item.band_id === band.id)!;
          return <td key={band.id} data-own={cell.products.length > 0}>{cell.status === "no_readable_observations" ? <p className={styles.emptyCell}>暂无可读记录</p> : <><p className={styles.cellCount}><span>我方 <b>{cell.counts.products}</b></span><span>竞品 <b>{cell.counts.competitors}</b></span></p>{[...cell.products, ...cell.competitors].map((item, itemIndex) => <Placement key={`${item.subject.type}:${item.subject.id}:${itemIndex}`} item={item} onOpenProduct={onOpenProduct}/>)}</>}</td>;
        })}</tr>)}</tbody></table></div>
      </section>)}
      {data.groups.length === 0 && <p className={styles.notice}>{data.coverage.visible_products + data.coverage.visible_competitors === 0 ? "当前品类的可见范围内尚无型号或竞品记录。" : "当前没有同时具备可读细分与价格依据的落格记录。"}</p>}
      {data.unplaced.length > 0 && <section className={styles.unplaced} aria-label="未落格记录"><header><h3>未落格记录</h3><p>保留原价格与缺失原因，补齐依据后可重新读取。</p></header>{data.unplaced.map((item, index) => <div className={styles.unplacedRow} key={`${item.subject.type}:${item.subject.id}:${index}`}><Placement item={item} onOpenProduct={onOpenProduct}/><div className={styles.unplacedReasons}><p>细分：{item.fixed_segment ? `${item.fixed_segment.label ?? "名称不可读"} · 固定 v${item.fixed_segment.version}` : "未登记关联"}</p><ul>{item.reasons.map(reason => <li key={reason}>{reasonLabels[reason] ?? reason}</li>)}</ul>{item.fixed_segment && <div className={styles.segmentSource}><ProposalSourceInspector sources={item.fixed_segment.source_refs} label="细分来源"/></div>}</div></div>)}</section>}
      {data.limitations.length > 0 && <ul className={styles.limitations}>{data.limitations.map(item => <li key={item}>{limitationLabels[item] ?? item}</li>)}</ul>}
      <p className={styles.asOf}>资料读取于 {data.as_of ? <time dateTime={data.as_of}>{new Date(data.as_of).toLocaleString()}</time> : "时间未提供"}</p>
    </>}
  </div>;
}
