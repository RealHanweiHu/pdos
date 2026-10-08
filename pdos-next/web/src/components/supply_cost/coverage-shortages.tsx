"use client";

import { useState } from "react";
import { Package, ShieldCheck } from "@phosphor-icons/react";
import { Basis, Issues, Panel, ReadStatus, Source } from "./display";
import { freshnessLabels, poolKey, quantity, readiness } from "./presentation";
import type { CoverageView, ProjectionRecord, ReadState } from "./types";

export type CoverageShortagesProps = ReadState & { projections: ProjectionRecord<CoverageView>[] };
export function CoverageShortages({ projections, ...readState }: CoverageShortagesProps) {
  const [selectedId, setSelectedId] = useState("");
  const selected = projections.find(item => item.id === selectedId) ?? projections[0];
  const result = selected?.result;
  return <Panel title="齐套与缺项" note="已占用齐套核对本 Build 的实到/现货；库存候选不产生占用，也不批准 Build 开始。">
    <ReadStatus {...readState}/>
    {!selected && readState.status !== "loading" && readState.status !== "unconnected" && <p className="subtle">尚无固定供给与权威需求的计算结果。</p>}
    {selected && result && <>
      <label>计算历史<select value={selected.id} onChange={event => setSelectedId(event.target.value)}>{projections.map(item => <option value={item.id} key={item.id}>v{item.revision} · {freshnessLabels[item.freshness]} · {item.created_at}</option>)}</select></label>
      <p className="text-sm font-medium">{freshnessLabels[selected.freshness]}{selected.freshness !== "current" ? " · 下列结果只描述当时固定输入" : ""}</p>
      {selected.freshness_reasons.map((reason, index) => <p className="text-sm break-words" key={index}>{reason}</p>)}
      <Basis basis={result.input_snapshot.basis}/>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-border p-3"><p className="subtle flex gap-1 items-center"><ShieldCheck/>已占用实物</p><p className="mt-1 font-semibold">{readiness(result.secured_ready, "本范围已齐套")}</p></div>
        <div className="rounded-lg border border-border p-3"><p className="subtle">关键件已占用</p><p className="mt-1 font-semibold">{readiness(result.critical_secured_ready, "关键件满足")}</p></div>
        <div className="rounded-lg border border-border p-3"><p className="subtle flex gap-1 items-center"><Package/>未分配库存候选</p><p className="mt-1 font-semibold">{readiness(result.potential_ready, "此候选满足")}</p></div>
      </div>
      <p className="subtle">计算时点：<time dateTime={result.input_snapshot.as_of}>{result.input_snapshot.as_of}</time> · {result.input_snapshot.supply_scope_complete ? "占用范围完整" : "占用范围待补齐"}</p>
      <p className="text-sm">库存候选采用固定分配顺序；缺项不证明其他替代分配不可行。替代资格须来自服务器已核验的精确范围。</p>
      <Issues issues={result.issues}/>
      <div className="space-y-4">{result.lines.map(line => <article key={line.demand.item_id} className="space-y-3 border-t border-border pt-4">
        <h3 className="font-semibold text-sm break-words">{line.demand.material_id ?? "物料待确认"} · {line.demand.item_id}{line.demand.critical ? " · 关键件" : ""}</h3>
        <p className="text-sm">固定需求：{quantity(line.demand.required_quantity, line.demand.unit)}</p>
        <dl className="grid gap-3 text-sm sm:grid-cols-2"><div><dt className="subtle">已占用实物 · {readiness(line.secured_ready, "满足")}</dt><dd>已知 {quantity(line.known_secured_quantity, line.demand.unit)} · 缺口 {quantity(line.secured_gap, line.demand.unit)}</dd></div><div><dt className="subtle">库存候选 · {readiness(line.potential_ready, "此候选满足")}</dt><dd>已知 {quantity(line.known_potential_quantity, line.demand.unit)} · 缺口 {quantity(line.potential_gap, line.demand.unit)}</dd></div></dl>
        <Issues issues={[...line.demand.issues, ...line.issues]} title="本项依据与缺项"/>
        {line.uses.length > 0 && <details><summary className="cursor-pointer subtle">物理池使用依据 · {line.uses.length}</summary><ul className="mt-3 space-y-3">{line.uses.map((use, index) => <li key={`${poolKey(use.pool)}:${use.reservation_id}:${index}`} className="text-sm space-y-1"><p className="break-words">{poolKey(use.pool)} · {use.kind === "secured" ? "明确占用" : "未分配候选"}</p><p>需求单位 {quantity(use.quantity_in_demand_unit, line.demand.unit)} · 池单位数量 {use.quantity_in_pool_unit}</p>{use.reservation_id && <p className="subtle break-words">占用 {use.reservation_id}</p>}{use.qualification_id && <p className="subtle break-words">服务器提供的替代资格 {use.qualification_id}</p>}</li>)}</ul></details>}
      </article>)}</div>
      {!result.lines.length && <p className="subtle">本结果没有可核对需求，齐套保持未确定。</p>}
      <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-sm font-medium">物理池余额及全部占用核对 · {result.pools.length}</summary><ul className="mt-3 space-y-4">{result.pools.map((pool, index) => <li key={`${poolKey(pool.key)}:${index}`} className="space-y-2 text-sm"><p className="font-medium break-words">{poolKey(pool.key)}</p><p>余额 {quantity(pool.quantity, pool.unit)} · 全部占用 {quantity(pool.reserved_quantity, pool.unit)}</p><p>本 Build 已占用 {quantity(pool.own_secured_quantity, pool.unit)} · 未分配可用 {quantity(pool.unreserved_usable_quantity, pool.unit)}</p><Source source={pool.source}/><Issues issues={pool.issues} title="池限制"/></li>)}</ul></details>
      <details><summary className="cursor-pointer subtle">固定计算依据</summary><p className="mt-2"><Source source={result.input_snapshot.supply_snapshot}/></p><p className="subtle break-all mt-2">输入 {result.input_sha256}</p><p className="subtle mt-1">{result.schema_version} · {result.algorithm}</p></details>
    </>}
  </Panel>;
}
