"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";
import { rows, text, type Row } from "@/components/quality/fmea-sources";

const when = (value: unknown) => value ? new Date(text(value)).toLocaleString() : "未知";
const triggers: Record<string, string> = { human: "人工", automatic: "自动触发", propagation: "依赖传播" };
export function PortfolioForecastHistory({ projectId }: { projectId: string }) {
  const [data, setData] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function load(more = false) {
    setBusy(true); setError("");
    try {
      const next = await caseLinkRequest<Row>("planning/portfolio-forecast-history", {
        project_id: projectId, before_version: more ? data?.next_before_version : null,
      });
      setData(old => more ? { ...next, items: [...rows(old?.items), ...rows(next.items)] } : next);
    } catch (e) { setError(e instanceof Error ? e.message : "预测历史读取未完成"); }
    finally { setBusy(false); }
  }
  return <details className="mt-3 border-t pt-2">
    <summary className="cursor-pointer text-sm font-medium">保存预测历史与记录间隔</summary>
    <div className="mt-3 space-y-3 text-xs">
      <p className="text-muted-foreground">逐版回查实际保存记录。计算基准时间与保存时间分别列示；相邻保存间隔不证明两次之间来源持续有效，也不代表持续预测覆盖已达标。</p>
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>{busy ? "读取中…" : "读取／刷新预测历史"}</Button>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {data && rows(data.items).length === 0 && <p>尚无保存预测。</p>}
      {rows(data?.items).map(v => <article key={text(v.record_id)} className="space-y-2 rounded-md border p-3">
        <p className="font-medium">预测 v{text(v.version)} · {v.complete === true ? "原计算日期完整" : "原计算日期有缺项"} · {triggers[text(v.trigger)] ?? "原版未标明触发方式"}</p>
        <div className="grid gap-2 sm:grid-cols-3"><p>计算基准 {when(v.as_of)}<br />预测完工 {when(v.project_finish)}</p><p>保存于 {when(v.created_at)}<br />前次保存 {when(v.previous_saved_at)}<br />记录间隔 {v.save_interval_hours == null ? "未知／无前次" : `${Number(v.save_interval_hours).toFixed(1)} 小时`}</p><p>有预测日期 {text(v.dated_node_count)} / {text(v.node_count)} 节点<br />原关键路径节点 {text(v.saved_critical_count)} · 关键性未知 {text(v.saved_critical_unknown_count)}</p></div>
        <p className="whitespace-pre-wrap text-muted-foreground">{text(v.reason)}</p>
        <a className="inline-flex min-h-11 items-center text-primary underline" href={text(v.href)}>查看原版本、输入与计算依据</a>
      </article>)}
      {data?.next_before_version != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>读取更早预测</Button>}
    </div>
  </details>;
}
