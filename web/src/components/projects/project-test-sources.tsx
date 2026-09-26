"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";

export type TestPlanSource = {
  kind: "document" | "specification" | "requirement"; id: string; digest: string;
  reference_id: string; label: string; version: string; locator: string;
  status: string; excerpt: string; href: string; available?: boolean;
};
const kinds = { document: "客户文件片段", specification: "项目规格", requirement: "关联需求" } as const;
const statuses: Record<string, string> = { draft: "草稿", proposed: "待确认", approved: "已批准", rejected: "已拒绝", converted: "已转化" };
export function sourceDescription(source: TestPlanSource) {
  return `${source.label} · ${source.kind === "document" ? `文件版本 ${source.version.slice(0, 12)}` : `版本 ${source.version}`} · ${source.locator} · ${statuses[source.status] ?? source.status}`;
}

export function ProjectTestSources({ projectId, planId, selected, onChange, disabled }: {
  projectId: string; planId: string; selected: TestPlanSource[];
  onChange: (sources: TestPlanSource[]) => void; disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<TestPlanSource["kind"]>("document");
  const [items, setItems] = useState<TestPlanSource[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function load(nextKind = kind, offset = 0) {
    setOpen(true); setBusy(true); setError(null); setKind(nextKind);
    try {
      const response = await fetch(`/api/projects/${projectId}/npi/test-plans/${planId}/suggestion-sources?kind=${nextKind}&offset=${offset}`, { cache: "no-store" });
      const result = await response.json();
      if (!response.ok || !Array.isArray(result.items)) throw new Error("暂时无法读取项目依据，请重试。");
      setItems(offset ? (previous) => [...previous, ...result.items] : result.items);
      setNextOffset(result.next_offset); setTotal(result.total);
    } catch (cause) { setItems([]); setNextOffset(null); setError(cause instanceof Error ? cause.message : "读取失败。"); }
    finally { setBusy(false); }
  }
  function toggle(source: TestPlanSource, checked: boolean) {
    onChange(checked ? [...selected.filter((s) => s.reference_id !== source.reference_id), source] : selected.filter((s) => s.reference_id !== source.reference_id));
  }
  return <section aria-label="测试建议依据" className="space-y-2 rounded-lg border p-3 text-sm">
    <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium">附上项目依据（可选，已选 {selected.length}/8）</p><Button disabled={disabled || busy} variant="outline" onClick={() => void load()}>选择文件或规格</Button></div>
    <p className="text-xs text-muted-foreground">只使用你选中的片段；确认后点击“生成调整建议”才会交给 AI。机密、受限文件不在此列出。选择依据不代表批准其技术要求。</p>
    {selected.length > 0 ? <ul className="space-y-2">{selected.map((source) => <li key={source.reference_id}><span>{sourceDescription(source)}</span><button className="ml-3 min-h-11 text-primary" disabled={disabled} onClick={() => toggle(source, false)}>移除 {source.label}</button></li>)}</ul> : null}
    {open ? <div className="space-y-3">
      <label className="flex items-center gap-2">依据类型<select className="h-11 rounded-lg border bg-background px-2" value={kind} disabled={disabled || busy} onChange={(e) => void load(e.target.value as TestPlanSource["kind"])}>{Object.entries(kinds).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>
      <p className="text-xs text-muted-foreground">已显示 {items.length} / {total} 处。文件按现有解析的页或行片段列出；未解析出文字的文件需要先核对原件。</p>
      {items.map((source) => {
        const checked = selected.some((s) => s.reference_id === source.reference_id && s.digest === source.digest);
        return <div className="space-y-1 border-t pt-2" key={source.reference_id}>
          <label className="flex min-h-11 items-start gap-2"><input type="checkbox" className="mt-1" checked={checked} disabled={disabled || !source.available || (!checked && selected.length >= 8)} onChange={(e) => toggle(source, e.target.checked)} /><span>{sourceDescription(source)}</span></label>
          <details><summary className="min-h-11 cursor-pointer py-2 text-primary">查看原文 · {source.label}</summary><pre className="max-h-72 overflow-auto whitespace-pre-wrap font-sans text-xs leading-6">{source.excerpt}</pre></details>
        </div>;
      })}
      {!busy && items.length === 0 && !error ? <p>暂无可选依据。可以先在对话中说明要求，或在项目文档入口上传 PDF / Excel 并完成文字解析。</p> : null}
      {nextOffset !== null ? <Button disabled={busy || disabled} variant="outline" onClick={() => void load(kind, nextOffset)}>加载更多依据</Button> : null}
      {busy ? <p role="status">正在读取依据…</p> : null}
      {error ? <p role="alert" className="text-destructive">{error}</p> : null}
    </div> : null}
  </section>;
}
