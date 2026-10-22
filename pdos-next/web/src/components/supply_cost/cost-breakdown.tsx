"use client";

import { useState } from "react";
import { Calculator } from "@phosphor-icons/react";
import { Basis, Issues, Panel, ReadStatus, Source } from "./display";
import { freshnessLabels, quantity } from "./presentation";
import type { CostView, ProjectionRecord, ReadState } from "./types";

export type CostBreakdownProps = ReadState & { projections: ProjectionRecord<CostView>[] };
const categoryLabels = { material: "物料", process: "工艺", nre: "一次性费用" };
export function CostBreakdown({ projections, ...readState }: CostBreakdownProps) {
  const [selectedId, setSelectedId] = useState("");
  const selected = projections.find(item => item.id === selectedId) ?? projections[0];
  const result = selected?.result;
  const scope = result?.input_snapshot.scope;
  return <Panel title="成本候选与分项" note="保留报价、工艺、汇率、数量和损耗口径；估算不表示实际降本或财务批准。">
    <ReadStatus {...readState}/>
    {!selected && readState.status !== "loading" && readState.status !== "unconnected" && <p className="subtle">尚无固定输入的成本估算。</p>}
    {selected && result && scope && <>
      <label>估算历史<select value={selected.id} onChange={event => setSelectedId(event.target.value)}>{projections.map(item => <option key={item.id} value={item.id}>v{item.revision} · {freshnessLabels[item.freshness]} · {item.created_at}</option>)}</select></label>
      <p className="font-medium text-sm">{freshnessLabels[selected.freshness]} · {result.complete_in_selected_scope ? "所选费用范围完整" : "所选费用范围有缺项"}</p>
      {selected.freshness !== "current" && <p className="subtle">下列估算只描述当时固定输入，不能用作当前成本。</p>}
      {selected.freshness_reasons.map((reason, index) => <p key={index} className="text-sm break-words">{reason}</p>)}
      <Basis basis={result.input_snapshot.basis}/>
      <dl className="grid gap-3 text-sm sm:grid-cols-2"><div><dt className="subtle">本次选定范围</dt><dd>{scope.coverage === "materials_only" ? "仅物料" : "物料与工艺"} · {scope.tax_basis === "inclusive" ? "含税" : "未税"} · {scope.freight_basis === "included" ? "含运费" : "不含运费"}</dd></div><div><dt className="subtle">估算时点与汇率</dt><dd><time dateTime={result.input_snapshot.as_of}>{result.input_snapshot.as_of}</time> · {scope.rate_purpose === "spot" ? "即期" : "预算"}汇率 · 最长 {scope.max_rate_age_days} 天</dd></div><div><dt className="subtle">一次性费用</dt><dd>{scope.nre_policy === "excluded" ? "本次排除" : scope.nre_policy === "separate" ? "单独列示" : `按 ${quantity(scope.nre_volume)} 件分摊`}</dd></div><div><dt className="subtle">币种</dt><dd>{result.currency}</dd></div></dl>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-border p-3"><p className="subtle flex items-center gap-1"><Calculator/>Build 成本候选</p><p className="mt-1 font-mono text-xl break-words">{quantity(result.build_candidate, result.currency)}</p><p className="subtle mt-1">已知分项小计 {quantity(result.known_build_subtotal, result.currency)}</p></div>
        <div className="rounded-lg border border-border p-3"><p className="subtle">单件候选</p><p className="mt-1 font-mono text-xl break-words">{quantity(result.per_product_candidate, result.currency)}</p><p className="subtle mt-1">按固定 Build 数量和单位计算</p></div>
      </div>
      {scope.nre_policy !== "excluded" && <dl className="grid gap-3 text-sm sm:grid-cols-2"><div><dt className="subtle">一次性费用候选 / 已知小计</dt><dd>{quantity(result.nre_candidate, result.currency)} / {quantity(result.known_nre_subtotal, result.currency)}</dd></div>{scope.nre_policy === "amortize" && <div><dt className="subtle">含一次性费用分摊的单件候选</dt><dd>{quantity(result.including_amortized_nre, result.currency)}</dd></div>}</dl>}
      <Issues issues={result.issues}/>
      <Issues issues={result.sensitive_items} title="敏感项与口径提示"/>
      <div className="space-y-4">{result.lines.map((line, index) => {
        const price = result.input_snapshot.prices.find(item => item.price_id === line.price_id);
        return <article key={`${line.line_id}:${index}`} className="space-y-3 border-t border-border pt-4"><h3 className="font-semibold text-sm break-words">{categoryLabels[line.category]} · {line.line_id}</h3>
          <dl className="grid gap-3 text-sm sm:grid-cols-2"><div><dt className="subtle">Build 需求数量</dt><dd>{quantity(line.quantity_for_build, line.demand_unit)}</dd></div><div><dt className="subtle">报价单位需求数量</dt><dd>{quantity(line.quantity_in_price_unit, price?.unit)}</dd></div><div><dt className="subtle">原币分项</dt><dd>{quantity(line.original_build_amount, line.original_currency)}</dd></div><div><dt className="subtle">目标币 Build 候选</dt><dd>{quantity(line.build_candidate, result.currency)}</dd></div><div><dt className="subtle">单件候选</dt><dd>{quantity(line.per_product_candidate, result.currency)}</dd></div></dl>
          {price ? <div className="rounded-lg border border-border p-3 space-y-2 text-sm"><p className="break-words">{price.stage === "quote" ? "供方报价" : "估价"} {price.price_id} · {price.subject_id}</p><p>价格 {quantity(price.amount, price.currency)} / {quantity(price.price_quantity, price.unit)}</p><p className="subtle">数量阶梯：{quantity(price.minimum_quantity, price.unit)} 至 {quantity(price.maximum_quantity, price.unit)}</p><p className="break-words">报价范围：{price.scope_assumption}</p><Source source={price.ref}/></div> : <p className="subtle">报价对象未提供。</p>}
          {line.rate_id && <p className="subtle break-words">固定汇率 {line.rate_id}</p>}
          <Issues issues={line.issues} title="本项缺项与限制"/>
        </article>;
      })}</div>
      {!result.lines.length && <p className="subtle">本结果没有成本分项，不能据此认定成本为零。</p>}
      <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-sm font-medium">固定工艺、损耗和汇率</summary><div className="mt-3 space-y-4">
        {result.input_snapshot.process ? <section className="space-y-2 text-sm"><Source source={result.input_snapshot.process.ref}/><p className="break-words">{result.input_snapshot.process.assumption}</p><ul className="space-y-2">{result.input_snapshot.process.operations.map(operation => <li key={operation.operation_id} className="break-words">{operation.operation_id} · 每合格成品 {quantity(operation.quantity_per_product, operation.unit)} · 损耗率 {quantity(operation.loss_rate)}</li>)}</ul></section> : <p className="subtle">未提供工艺快照；是否需要工艺费用由本次选定范围决定。</p>}
        <ul className="space-y-3">{result.input_snapshot.rates.map(rate => <li key={rate.rate_id} className="text-sm space-y-1"><p className="break-words">{rate.rate_id} · {rate.from_currency} → {rate.to_currency} · {quantity(rate.rate)} · {rate.purpose === "spot" ? "即期" : "预算"}</p><Source source={rate.ref}/></li>)}</ul>{!result.input_snapshot.rates.length && <p className="subtle">本次未提供直接汇率。</p>}
      </div></details>
      <details><summary className="cursor-pointer text-sm">估算假设与固定摘要</summary><ul className="mt-3 space-y-2 text-sm">{scope.assumptions.map((assumption, index) => <li key={index} className="break-words">{assumption}</li>)}</ul><p className="subtle break-all mt-3">输入 {result.input_sha256}</p><p className="subtle mt-1">{result.schema_version} · {result.algorithm}</p></details>
    </>}
  </Panel>;
}
