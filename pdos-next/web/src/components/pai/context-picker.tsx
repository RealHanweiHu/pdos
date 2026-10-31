"use client";

import { useEffect, useRef, useState } from "react";
import { CaretDown, Crosshair } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/browser-api";
import { readPortfolio, type PortfolioProject } from "@/lib/portfolio-reads";
import styles from "./context-picker.module.css";

export type SelectedPaiContext = { categoryId: string; categoryName: string; productId: string; projectId: string; projectName: string };

/** Explicitly selecting a project changes only this panel's next-work scope. */
export function ContextPicker({ value, onChange, compact = false, pageLabel, triggerLabel }: {
  compact?: boolean; pageLabel?: string; triggerLabel?: string;
  value: SelectedPaiContext | null | undefined; onChange: (value: SelectedPaiContext | null | undefined) => void;
}) {
  const [items, setItems] = useState<PortfolioProject[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const generation = useRef(0), panel = useRef<HTMLDetailsElement | null>(null);
  useEffect(() => () => { generation.current++; }, []);
  async function refresh() {
    const own = ++generation.current;
    setItems(null); setBusy(true); setError("");
    try {
      const portfolio = await readPortfolio(browserApi);
      if (own !== generation.current) return;
      setItems(portfolio.projects);
      if (portfolio.readErrors.length) setError(portfolio.readErrors.map(item => item.message).join("；"));
    } catch (failure) { if (own === generation.current) setError(failure instanceof Error ? failure.message : "项目范围暂不可读。"); }
    finally { if (own === generation.current) setBusy(false); }
  }
  function select(next: SelectedPaiContext | null | undefined) { onChange(next); if (panel.current) panel.current.open = false; }
  const filtered = items?.filter(item => `${item.project.name} ${item.product.name} ${item.category.name}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <details ref={panel} className={`${styles.picker}${compact ? ` ${styles.compact}` : ""}`} onToggle={event => { if (event.currentTarget.open && items === null && !busy && !error) void refresh(); }}>
    <summary>{!compact && <Crosshair size={13} aria-hidden="true"/>}<span>{triggerLabel || (value === undefined ? pageLabel || "跟随当前页面" : value === null ? "个人工作" : value.projectName)}</span>{compact && <CaretDown size={11} aria-hidden="true"/>}</summary>
    <div className={styles.panel}>
      <p>切换后显示对应的会话和资料；已有运行在原范围继续。</p>
      <button type="button" aria-pressed={value === undefined} onClick={() => select(undefined)}>跟随当前页面</button>
      <button type="button" aria-pressed={value === null} onClick={() => select(null)}>{value === null || pageLabel === "通用对话" ? "个人工作" : "移除当前对象，进入个人工作"}</button>
      <label>查找项目<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="项目、型号或品类"/></label>
      {busy && <p role="status">正在读取当前可见项目…</p>}
      {error && <p role="alert">{error}</p>}
      <div className={styles.list}>{filtered?.map(item => <button type="button" key={item.project.id} aria-pressed={value?.projectId === item.project.id} onClick={() => select({ categoryId: item.category.id, categoryName: item.category.name, productId: item.product.id, projectId: item.project.id, projectName: item.project.name })}>
        <strong>{item.project.name}</strong><small>{item.category.name} · {item.product.name}</small>
      </button>)}</div>
      {filtered?.length === 0 && <p>{query ? "没有匹配的可见项目。" : "当前没有可见项目。"}</p>}
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void refresh()}>刷新可见项目</Button>
    </div>
  </details>;
}
