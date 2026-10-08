"use client";

import { useState } from "react";
import { useProductReading, inProductScope } from "./product-reading-context";
import { ReadingLabel } from "./product-reading-ui";
import { SourceCitations } from "./source-citations";
import type { Evidence, SourceRef, Workspace } from "./product-work-api";
import type { Fact } from "./market-segments";

type Entry = { key: string; label: string; value: string; calibration: string; kind: string; sources: SourceRef[]; warnings: string[] };
function EntryCard({ entry, base, evidence, onAuthorityLost }: { entry: Entry; base: string; evidence: Evidence[]; onAuthorityLost: (message: string) => void }) {
  const [open, setOpen] = useState(false);
  const challenged = entry.warnings.length > 0 || entry.sources.some(ref => { const source = evidence.find(item => item.id === ref.ref_id); return !source || source.reference.digest !== ref.digest || source.has_conflict || source.is_stale || source.superseded; });
  return <article className={`min-w-0 rounded-lg border p-3.5 ${challenged ? "border-pending/40 bg-pending/5" : "bg-card"}`}><p className="text-[11px] font-medium text-muted-foreground">{entry.label}</p><p className="mt-1 break-words text-base font-semibold leading-6">{entry.value}</p><p className="mt-1 text-[11px] leading-5 text-muted-foreground">{entry.calibration}</p><div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]"><span className="rounded bg-muted px-1.5 py-0.5">{entry.kind}</span><span className="text-muted-foreground">{entry.sources.length} 条来源</span><span className={challenged ? "text-pending" : "text-muted-foreground"}>{challenged ? "待复核" : entry.kind === "假设" ? "待验证" : "已保存"}</span><button type="button" aria-expanded={open} className="ml-auto min-h-8 text-primary hover:underline" onClick={() => setOpen(!open)}>{open ? "收起来源" : "来源"}</button></div>{open && <div className="mt-2 space-y-2 border-t border-dashed pt-2 text-xs">{entry.warnings.map((warning, index) => <p key={index} className="text-pending">{warning}</p>)}<SourceCitations base={base} evidence={evidence} references={entry.sources} onAuthorityLost={onAuthorityLost}/></div>}</article>;
}

export function ProductResearchEntries({ base, workspace, evidence, scope, onAuthorityLost }: { base: string; workspace: Workspace; evidence: Evidence[]; scope: string; onAuthorityLost: (message: string) => void }) {
  const reading = useProductReading();
  const entries: Entry[] = workspace.research.filter(item => item.state === "completed" && item.conclusion && (scope === "all" || (item.product_line_id ?? "") === scope)).map(item => ({ key: item.id, label: item.question, value: item.conclusion!, calibration: `${item.time_scope} · ${item.method} · 研究 v${item.version}`, kind: "研究结论", sources: item.sources, warnings: item.unresolved }));
  const addFact = (key: string, label: string, fact: Fact, calibration: string, warnings: string[]) => { if (fact.text?.trim()) entries.push({ key, label, value: fact.text, calibration: [calibration, fact.derivation_version].filter(Boolean).join(" · "), kind: ({ observed: "观察", derived: "推导", hypothesis: "假设" })[fact.fact_kind], sources: fact.sources, warnings }); };
  for (const segment of inProductScope(reading.segments, scope) ?? []) {
    addFact(`${segment.id}:jtbd`, `${segment.title} · 用户任务`, segment.job_to_be_done, `细分 v${segment.version}`, segment.source_warnings);
    for (const [field, label] of [["customer_problems", "用户问题"], ["buying_criteria", "购买判据"], ["unmet_needs", "未满足需求"]] as const) segment[field].forEach((fact, index) => addFact(`${segment.id}:${field}:${index}`, `${segment.title} · ${label}`, fact, `细分 v${segment.version}`, segment.source_warnings));
  }
  for (const item of inProductScope(reading.competitors, scope) ?? []) {
    if (item.price_quote) { const price = item.price_quote; entries.push({ key: `${item.id}:price`, label: `${item.brand} ${item.model} · 价格`, value: `${price.amount} ${price.currency}`, calibration: `${item.region} · ${item.channel} · ${price.as_of} · ${price.tax_included === true ? "含税" : price.tax_included === false ? "不含税" : "税费待确认"} · 数量 ${price.quantity}`, kind: "报价观察", sources: price.source_refs, warnings: item.source_warnings }); }
  }
  return <section className="min-w-0"><ReadingLabel>本主题词条 <span className="ml-2 font-normal text-primary">已保存成果 · 来源可核对</span></ReadingLabel>{entries.length ? <div className="grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr))]">{entries.slice(0, 60).map(entry => <EntryCard key={entry.key} entry={entry} base={base} evidence={evidence} onAuthorityLost={onAuthorityLost}/>)}</div> : <p className="rounded-lg border border-dashed p-4 text-xs leading-6 text-muted-foreground">{reading.segments === undefined || reading.competitors === undefined ? "部分专业成果暂未取得；尚未取得的内容不作结论，可在对应视图重试读取。" : "还没有可引用的研究结论、细分或价格词条。完成研究或独立应用已接受候选后，成果会出现在这里。"}</p>}{entries.length > 60 && <p className="mt-2 text-xs text-muted-foreground">显示最近范围内前60条成果，完整版本与依据可在对应专业视图核对。</p>}</section>;
}
