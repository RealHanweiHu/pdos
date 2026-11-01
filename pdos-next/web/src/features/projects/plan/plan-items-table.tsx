"use client";

import { useMemo, useState } from "react";
import { MagnifyingGlass } from "@phosphor-icons/react";
import { planStatusLabels, planStatusOrder, type PlanItem, type PlanItemStatus } from "@/lib/plan-progress";

type StatusFilter = "all" | PlanItemStatus;

export function PlanItemsTable({ items }: { items: PlanItem[] }) {
  const [status, setStatus] = useState<StatusFilter>("all");
  const [group, setGroup] = useState("all");
  const [query, setQuery] = useState("");
  const groups = useMemo(() => Array.from(new Map(items.map((item) => [item.group, item.groupLabel])).entries()), [items]);
  const counts = useMemo(() => {
    const byStatus: Record<StatusFilter, number> = { all: items.length, done: 0, partial: 0, todo: 0, blocked: 0 };
    for (const item of items) byStatus[item.status] += 1;
    return byStatus;
  }, [items]);
  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return items.filter((item) =>
      (status === "all" || item.status === status)
      && (group === "all" || item.group === group)
      && (!keyword || [item.id, item.title, item.summary, item.dependencies, item.responsibility, item.groupLabel].join("\n").toLowerCase().includes(keyword)));
  }, [items, status, group, query]);

  return <div>
    <div className="flex flex-wrap items-center gap-2">
      <div role="group" aria-label="按状态筛选" className="flex flex-wrap gap-1.5">
        <button type="button" className="plan-filter" aria-pressed={status === "all"} onClick={() => setStatus("all")}>全部 {counts.all}</button>
        {planStatusOrder.filter((entry) => counts[entry] > 0 || entry !== "blocked").map((entry) => (
          <button key={entry} type="button" className="plan-filter" aria-pressed={status === entry} onClick={() => setStatus(entry)}>{planStatusLabels[entry]} {counts[entry]}</button>
        ))}
      </div>
      <label className="!mb-0 w-auto shrink-0 text-[13px] font-medium">
        <span className="sr-only">按分组筛选</span>
        <select name="plan-group" className="w-auto max-w-[240px]" value={group} onChange={(event) => setGroup(event.target.value)}>
          <option value="all">全部分组</option>
          {groups.map(([id, label]) => <option key={id} value={id}>{id} · {label}</option>)}
        </select>
      </label>
      <label className="!mb-0 min-w-[180px] flex-1 text-[13px] font-medium">
        <span className="sr-only">搜索条目</span>
        <div className="flex items-center gap-2"><MagnifyingGlass size={15} className="shrink-0 text-[var(--text-subtle)]" aria-hidden="true" /><input name="plan-search" className="min-w-0" placeholder="搜索编号、标题或摘要…" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
      </label>
    </div>
    <p className="subtle mt-3" role="status">显示 {filtered.length} / {items.length} 项</p>
    <div className="mt-1 divide-y divide-border">
      {filtered.map((item) => <article key={item.id} className="py-3.5">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="plan-badge"><span className="plan-dot" data-status={item.status} aria-hidden="true" />{planStatusLabels[item.status]}</span>
          <span className="plan-id">{item.id}</span>
          <p className="min-w-0 flex-1 text-[13px] font-medium">{item.title}</p>
          <span className="subtle">{item.group} · {item.groupLabel}</span>
        </div>
        <p className="subtle mt-1.5">依赖：{item.dependencies || "—"} · 责任：{item.responsibility || "—"}</p>
        {item.summary && <details className="mt-1"><summary className="cursor-pointer text-xs text-[var(--text-subtle)]">当前摘要</summary><p className="mt-1.5 text-[13px] leading-relaxed">{item.summary}</p></details>}
      </article>)}
      {filtered.length === 0 && <p className="py-8 text-center text-[13px] text-[var(--text-subtle)]">没有符合当前筛选的条目。</p>}
    </div>
  </div>;
}
