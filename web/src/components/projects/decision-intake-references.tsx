"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import type { ReferenceReviewDraft } from "./issue-intake-references";

type Row = Record<string, unknown>;
const obj = (value: unknown): Row => isRecord(value) ? value : {};
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const text = (value: unknown): string => value == null ? "未提供" : typeof value === "object" ? JSON.stringify(value) : String(value);
const key = (value: Row) => `${value.kind}/${value.id}/${value.path_id}`;
export function DecisionIntakeReferences({ projectId, decisionId, reviews, onChange, disabled, onBusy }: {
  projectId: string; decisionId: string; reviews: ReferenceReviewDraft[]; onChange: (value: ReferenceReviewDraft[]) => void; disabled: boolean; onBusy: (value: boolean) => void;
}) {
  const [data, setData] = useState<Row | null>(null), [kind, setKind] = useState("follow_up"), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  async function load(selectedKind = kind, more = false) {
    setBusy(true); onBusy(true); setError(null);
    try {
      const query = new URLSearchParams({ kind: selectedKind });
      if (more) Object.entries(obj(data?.next)).forEach(([k, v]) => query.set(k, text(v)));
      const response = await fetch(`/api/projects/${projectId}/intake/decision-work/${decisionId}/references?${query}`, { cache: "no-store" });
      const value: unknown = await responseBody(response).catch(() => null);
      if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && typeof obj(value.detail).message === "string" ? text(obj(value.detail).message) : "业务引用暂不可读取，请稍后刷新");
      setData(old => more ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); setKind(selectedKind);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); onBusy(false); }
  }
  function update(reference: Row, patch: Partial<ReferenceReviewDraft>) { onChange(reviews.map(item => key(item.reference) === key(reference) ? { ...item, ...patch } : item)); }
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget === e.target && e.currentTarget.open && !data && !busy) void load(); }}>
    <summary className="cursor-pointer">核对实际业务引用及下游处理</summary>
    <div className="mt-2 space-y-2">
      <p>按已登记关系查找，每类分页。自由文本、其他快照及更深层影响仍需核对；查询为空不代表全部业务可撤销。所选记录保留读取版本，刷新不会替换已选依据。</p>
      <div className="flex gap-2"><select aria-label="决策引用类型" className="rounded-md border bg-background p-2" disabled={disabled || busy} value={kind} onChange={e => void load(e.target.value)}>{data ? rows(data.kinds).map(item => <option key={text(item.kind)} value={text(item.kind)}>{text(item.label)}</option>) : <option value="follow_up">决策原跟进任务</option>}</select><Button type="button" size="sm" variant="outline" disabled={disabled || busy} onClick={() => void load()}>刷新本类引用</Button></div>
      {rows(data?.items).map(item => <article key={key(item)} className="space-y-1 border-t pt-2"><p><a className="text-primary underline" href={text(item.href)}>{text(item.title)}</a> · {text(obj(item.facts).status)}</p><details><summary className="cursor-pointer">查看当前记录及关系依据</summary><dl>{Object.entries(obj(item.facts)).map(([k, value]) => <div key={k} className="whitespace-pre-wrap break-words"><dt>{k}</dt><dd>{text(value)}</dd></div>)}</dl></details><Button type="button" size="sm" variant="outline" disabled={disabled || busy || reviews.length >= 50 || reviews.some(value => key(value.reference) === key(item))} onClick={() => onChange([...reviews, { reference: item, result: "follow_up", explanation: "" }])}>纳入本次逐项核对</Button></article>)}
      {data && !rows(data.items).length && <p>本类暂无可读取的明确关系。</p>}
      {data?.next != null && <Button type="button" size="sm" variant="outline" disabled={disabled || busy} onClick={() => void load(kind, true)}>继续读取本类引用</Button>}
      {reviews.map(item => <div key={key(item.reference)} className="space-y-2 rounded-md border p-2"><p className="font-medium">已选：{text(item.reference.title)}</p><details><summary className="cursor-pointer">本次选定版本的实际记录</summary><dl>{Object.entries(obj(item.reference.facts)).map(([name, value]) => <div key={name} className="whitespace-pre-wrap break-words"><dt>{name}</dt><dd>{text(value)}</dd></div>)}</dl></details><label className="block">核对结论<select className="ml-2 rounded-md border bg-background p-2" disabled={disabled || busy} value={item.result} onChange={e => update(item.reference, { result: e.target.value as ReferenceReviewDraft["result"] })}><option value="follow_up">仍需后续处理</option><option value="unaffected">核对后无需处理</option><option value="handled">已沿原业务处理</option></select></label><label className="block">处理依据、实际结果或后续安排<textarea className="w-full rounded-md border bg-background p-2" maxLength={4000} disabled={disabled || busy} value={item.explanation} onChange={e => update(item.reference, { explanation: e.target.value })}/></label><Button type="button" size="sm" variant="outline" disabled={disabled || busy} onClick={() => onChange(reviews.filter(value => key(value.reference) !== key(item.reference)))}>移除本项选择</Button></div>)}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
