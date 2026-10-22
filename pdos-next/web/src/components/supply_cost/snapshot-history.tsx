"use client";

import { useState } from "react";
import { ClockCounterClockwise } from "@phosphor-icons/react";
import { Basis, Panel, ReadStatus, Source } from "./display";
import { availabilityLabels, freshnessLabels, poolKey, qualityLabels, quantity, recordLabels } from "./presentation";
import type { ReadState, SupplyRecordKind, SupplySnapshotView } from "./types";

export type SupplySnapshotHistoryProps = ReadState & { snapshots: SupplySnapshotView[] };
export function SupplySnapshotHistory({ snapshots, ...readState }: SupplySnapshotHistoryProps) {
  const [selectedId, setSelectedId] = useState("");
  const selected = snapshots.find(item => item.id === selectedId) ?? snapshots[0];
  return <Panel title="供给快照与差异回查" note="各版快照独立保留；当前物理池余额与全部占用分别核对，不把承诺和在途累计成实到。">
    <ReadStatus {...readState}/>
    {!selected && readState.status !== "loading" && readState.status !== "unconnected" && <p className="subtle">尚无可见供给快照。</p>}
    {selected && <>
      <label>回查版本<select value={selected.id} onChange={event => setSelectedId(event.target.value)}>{snapshots.map(item => <option key={item.id} value={item.id}>v{item.revision} · {freshnessLabels[item.freshness]} · {item.captured_at}</option>)}</select></label>
      <p className="text-sm font-medium">{freshnessLabels[selected.freshness]} · {selected.scope_complete ? "供给及占用范围完整" : "供给或占用范围待补齐"}</p>
      {selected.freshness_reasons.length > 0 && <ul className="space-y-1 text-sm">{selected.freshness_reasons.map((reason, index) => <li key={index} className="break-words">{reason}</li>)}</ul>}
      <Basis basis={selected.binding.basis}/>
      <p className="subtle"><Source source={selected.binding.manufacturing_configuration}/> · 固定制造配置</p>
      <div className="space-y-4">{(Object.keys(recordLabels) as SupplyRecordKind[]).map(kind => {
        const records = selected.records.filter(item => item.record_kind === kind);
        return <section key={kind} aria-label={recordLabels[kind]} className="border-t border-border pt-4"><h3 className="text-sm font-semibold">{recordLabels[kind]} · {records.length}</h3>{records.length === 0 ? <p className="subtle mt-2">本版未记录。</p> : <ul className="mt-2 space-y-3">{records.map((record, index) => <li key={`${record.record_id}:${index}`} className="space-y-1 text-sm"><p className="break-words">{record.material_id} · {quantity(record.quantity, record.unit)} · {record.record_id}</p><p className="subtle">{qualityLabels[record.quality]} · {availabilityLabels[record.availability]}{record.pool_id ? ` · 池 ${record.pool_id}` : " · 物理池待绑定"}</p>
          {record.record_kind === "commitment" && <><p className="text-sm break-words">供方：{record.supplier_id ?? "待提供"}</p><p className="text-sm">承诺到达：{record.expected_at ? <time dateTime={record.expected_at}>{record.expected_at}</time> : "未知"}</p></>}
          {record.record_kind === "receipt" && <p className="text-sm">实际到达：<time dateTime={record.recorded_at}>{record.recorded_at}</time></p>}
          {(record.record_kind === "in_transit" || record.record_kind === "receipt") && <p className="subtle break-words">承诺关联：{record.commitment_id ?? "未提供"}</p>}
          <Source source={record.source}/>{record.note && <p className="break-words">{record.note}</p>}</li>)}</ul>}</section>;
      })}</div>
      <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer font-medium text-sm">当前物理池视图 · {selected.pools.length}</summary><ul className="mt-3 space-y-3">{selected.pools.map((pool, index) => <li key={`${poolKey(pool.key)}:${index}`} className="space-y-1 text-sm"><p className="break-words">{poolKey(pool.key)} · {quantity(pool.quantity, pool.unit)}</p><p className="subtle">{{ commitment: "供方承诺", in_transit: "在途", on_hand: "库存", received: "实际到货" }[pool.stage]} · {qualityLabels[pool.quality]} · {availabilityLabels[pool.availability]}</p><Source source={pool.ref}/>{pool.expected_at && <p className="subtle">预计到达：<time dateTime={pool.expected_at}>{pool.expected_at}</time></p>}</li>)}</ul>{!selected.pools.length && <p className="subtle mt-3">当前物理池尚未记录。</p>}</details>
      <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer font-medium text-sm">全部占用输入 · {selected.reservations.length}</summary><p className="subtle mt-2">包括其他 Build 的有效占用，尚未提供完整范围时可用量保持未知。</p><ul className="mt-3 space-y-3">{selected.reservations.map((reservation, index) => <li key={`${reservation.reservation_id}:${index}`} className="text-sm space-y-1"><p className="break-words">{reservation.build_id} · {reservation.bom_item_id ?? "BOM项待绑定"} · {quantity(reservation.quantity, reservation.unit)}</p><p className="subtle break-words">{poolKey(reservation.pool)} · {reservation.reservation_id}</p><Source source={reservation.ref}/></li>)}</ul>{!selected.reservations.length && <p className="subtle mt-3">本版未记录占用。</p>}</details>
      <section className="space-y-3 border-t border-border pt-4" aria-label="与前版对账"><h3 className="flex items-center gap-2 font-semibold text-sm"><ClockCounterClockwise/>与前版对账</h3>{selected.reconciliation ? <>
        <p className="subtle break-words">v{selected.reconciliation.before_revision}（{selected.reconciliation.before_snapshot_id}）→ v{selected.reconciliation.after_revision}（{selected.reconciliation.after_snapshot_id}）</p>
        <ul className="space-y-3">{selected.reconciliation.deltas.map((delta, index) => <li key={`${delta.record_key}:${delta.field}:${index}`} className="text-sm"><p className="font-medium break-words">{delta.record_key} · {delta.field}</p><div className="mt-1 grid gap-2 sm:grid-cols-2"><p className="break-words">前版：{delta.before ?? "未知"}</p><p className="break-words">本版：{delta.after ?? "未知"}</p></div>{delta.difference !== null && <p className="subtle">服务器核对差值：{quantity(delta.difference, delta.unit)}</p>}</li>)}</ul>
        {!selected.reconciliation.deltas.length && <p className="subtle">服务器对账未记录字段差异。</p>}
        {selected.reconciliation.reasons.map((reason, index) => <p key={index} className="text-sm break-words">{reason}</p>)}
        <details><summary className="cursor-pointer subtle">固定对账摘要</summary><p className="subtle break-all mt-2">前版 {selected.reconciliation.before_sha256}</p><p className="subtle break-all mt-1">本版 {selected.reconciliation.after_sha256}</p></details>
      </> : <p className="subtle">本版未提供前版对账。</p>}</section>
      <details><summary className="cursor-pointer subtle">本版固定来源与摘要</summary><ul className="mt-3 space-y-2">{selected.source_refs.map((source, index) => <li key={`${source.source_id}:${source.version}:${index}`}><Source source={source}/><p className="subtle break-all">{source.sha256}</p></li>)}</ul><p className="subtle break-all mt-2">快照 {selected.sha256}</p><p className="subtle break-all mt-1">需求 {selected.binding.demand_sha256}</p></details>
    </>}
  </Panel>;
}
