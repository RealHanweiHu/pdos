"use client";

import { Button } from "@/components/ui/button";
import type { Observation } from "./competitors";
import type { OpportunityRecord } from "./opportunities";
import type { SizingResult } from "./market-segments";
import { ReadingPanel } from "./product-reading-ui";

const point = (value: unknown) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value)) ? Number(value) : null;
function openRecord(id: string) {
  if (window.location.hash === `#${id}`) window.dispatchEvent(new HashChangeEvent("hashchange"));
  else window.location.hash = id;
  document.getElementById(id)?.scrollIntoView({ block: "start" });
}

export function OpportunityMap({ items }: { items: OpportunityRecord[] }) {
  const plotted = items.filter(item => point(item.importance) !== null && point(item.satisfaction) !== null);
  return <ReadingPanel title="机会分布 · 重要度 × 满意度"><div className="space-y-2 p-3.5"><p className="text-[11px] text-muted-foreground">点击一个机会查看依据与方案。坐标按已保存评分换算为百分制。</p><div className="relative ml-7 mr-5 h-56 border-b border-l bg-muted/20">
    <svg aria-hidden="true" className="absolute inset-0 size-full" preserveAspectRatio="none" viewBox="0 0 100 100">{[25,50,75].map(n => <g key={n} stroke="currentColor" className="text-border" strokeWidth="0.3" strokeDasharray="1.5 1.5"><line x1={n} x2={n} y1="0" y2="100"/><line y1={n} y2={n} x1="0" x2="100"/></g>)}</svg>
    <span className="absolute -left-7 top-0 text-[10px] text-muted-foreground">100</span><span className="absolute -bottom-5 -left-3 text-[10px] text-muted-foreground">0</span><span className="absolute -bottom-5 right-0 text-[10px] text-muted-foreground">100</span>
    <span className="absolute -left-7 top-1/2 -translate-y-1/2 [writing-mode:vertical-rl] text-[10px] text-muted-foreground">重要度</span>
    {plotted.map((item, index) => <button key={item.id} type="button" className="absolute z-10 flex size-6 -translate-x-1/2 translate-y-1/2 items-center justify-center rounded-full border border-primary/40 bg-primary/85 text-[10px] text-primary-foreground hover:bg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" style={{ left: `${Number(item.satisfaction) * 100}%`, bottom: `${Number(item.importance) * 100}%` }} aria-label={`${item.title}，重要度 ${Number(item.importance) * 100}，满意度 ${Number(item.satisfaction) * 100}，查看依据与方案`} title={item.title} onClick={() => openRecord(`opportunity-${item.id}`)}>{index + 1}</button>)}
  </div><p className="pt-3 text-center text-[10px] text-muted-foreground">满意度 →</p><div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px]">{plotted.map((item,index) => <span key={item.id}>{index + 1} · {item.title}</span>)}</div>{items.length > plotted.length && <p className="text-xs text-pending">{items.length - plotted.length} 项评分待确认，尚未绘入。</p>}{!items.length && <p className="text-xs text-muted-foreground">接受并独立应用机会候选后，在这里核对分布。</p>}</div></ReadingPanel>;
}

export function CompetitorPriceDistribution({ items, onRead }: { items: Observation[]; onRead: (item: Observation) => void }) {
  const groups = new Map<string, Observation[]>();
  for (const item of items) {
    const quote = item.price_quote;
    if (!quote || point(quote.amount) === null) continue;
    const group = [quote.currency, item.region, item.channel, quote.basis, quote.quantity, String(quote.tax_included), String(quote.shipping_included), quote.conditions].join(" · ");
    groups.set(group, [...(groups.get(group) ?? []), item]);
  }
  return <ReadingPanel title="竞品价格分布"><div className="space-y-4 p-3.5"><p className="text-[11px] text-muted-foreground">按币种、地区、渠道及报价条件分组，展示已有价格观察。单条报价保留为点值。</p>{[...groups].map(([key, rows]) => {
    const max = Math.max(...rows.map(row => Number(row.price_quote!.amount)), 1);
    const quote = rows[0].price_quote!;
    return <div className="space-y-2" key={key}><p className="text-[11px] text-muted-foreground">{quote.currency} · {rows[0].region} · {rows[0].channel} · 数量 {quote.quantity} · {quote.conditions}<br/>税费：{quote.tax_included === null ? "未知" : quote.tax_included ? "已含" : "未含"} · 运费：{quote.shipping_included === null ? "未知" : quote.shipping_included ? "已含" : "未含"}</p>{rows.map(row => <div key={row.id} className="grid grid-cols-[minmax(0,1fr)_minmax(60px,1.4fr)_auto] items-center gap-3 text-xs"><button className="truncate text-left text-primary underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring" onClick={() => onRead(row)}>{row.brand} {row.model}</button><div className="relative h-4 rounded bg-muted"><span className="absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary" style={{ left: `${Math.max(2, Math.min(98, Number(row.price_quote!.amount) / max * 100))}%` }}/></div><span className="font-mono text-[11px]">{row.price_quote!.amount} {quote.currency}</span></div>)}</div>;
  })}{!groups.size && <p className="text-xs text-muted-foreground">价格尚未知；保留来源口径后再展示。</p>}</div></ReadingPanel>;
}

export function CompetitorReadingMatrix({ items, onRead }: { items: Observation[]; onRead: (item: Observation) => void }) {
  const identity=(m:Observation["metrics"][number],line:string|null)=>m.parameter_id?`${m.parameter_id}:v${m.parameter_version}`:`legacy:${line??"space"}:${m.key}`;
  const metrics = [...new Map(items.flatMap(item => item.metrics.map(metric => [identity(metric,item.product_line_id), metric.label] as const))).entries()].slice(0, 12);
  return <ReadingPanel title="竞品对照 · 已保存观察"><div className="overflow-x-auto"><table className="w-full min-w-[600px] text-left text-xs"><thead className="bg-muted/30"><tr><th className="p-3">维度</th>{items.map(item => <th key={item.id} className="min-w-36 p-3"><Button variant="ghost" size="sm" className="h-auto whitespace-normal px-0 text-left text-xs text-primary" onClick={() => onRead(item)}>{item.brand} {item.model}</Button><span className="mt-1 block text-[11px] font-normal text-muted-foreground">{item.variant} · {item.observed_on}</span></th>)}</tr></thead><tbody><tr className="border-t"><th className="p-3 font-medium">价格</th>{items.map(item => <td className="p-3 align-top" key={item.id}>{item.price_quote ? <>{item.price_quote.amount} {item.price_quote.currency}<span className="block text-[11px] text-muted-foreground">{item.region} · {item.channel}<br/>{item.price_quote.conditions}</span></> : <span className="text-muted-foreground">未知</span>}</td>)}</tr>{metrics.map(([key,label]) => <tr key={key} className="border-t"><th className="p-3 align-top font-medium">{label}</th>{items.map(item => { const metric = item.metrics.find(value => identity(value,item.product_line_id) === key); return <td key={item.id} className="p-3 align-top">{metric && metric.nature !== "unknown" ? <>{metric.number !== null ? `${metric.number} ${metric.unit ?? ""}` : metric.text}<span className="mt-1 block text-[11px] text-muted-foreground">{({ claimed: "来源标称", measured: "实测", inferred: "推断" } as Record<string,string>)[metric.nature]} · {metric.conditions ?? "工况未记录"}</span></> : <span className="text-muted-foreground">未知</span>}</td>; })}</tr>)}</tbody></table></div><p className="border-t p-3 text-[11px] text-muted-foreground">并列展示原值；共用参数按固定版本对齐；旧指标保留为未映射。来源、单位与工况须核对后才能比较。完整可比性判定在下方“比较所选观察”。</p></ReadingPanel>;
}

export function MarketSizingIntervals({ result }: { result: SizingResult }) {
  const values = Object.entries(result.estimates);
  const max = Math.max(...values.map(([,value]) => point(value.annual_revenue?.upper) ?? 0), 1);
  return <div className="space-y-3 rounded-lg border bg-muted/20 p-3.5"><p className="text-xs font-medium">市场规模区间 · {result.horizon_year} · {result.currency}</p><p className="text-[11px] text-muted-foreground">{result.boundary}</p>{values.map(([key,value]) => { const lower = point(value.annual_revenue?.lower), upper = point(value.annual_revenue?.upper); return <div className="space-y-1" key={key}><div className="flex justify-between gap-2 text-[11px]"><span className="font-semibold">{key.toUpperCase()}</span><span>{lower === null || upper === null ? "参数未知，暂不可估计" : `${lower.toLocaleString()} – ${upper.toLocaleString()}`}</span></div><div className="relative h-3 rounded bg-muted">{lower !== null && upper !== null && <div className="absolute inset-y-0 min-w-1 rounded bg-primary/65" style={{ left: `${lower / max * 100}%`, width: `${(upper - lower) / max * 100}%` }}/>}</div></div>; })}<p className="text-[11px] text-muted-foreground">{result.interpretation}</p></div>;
}
