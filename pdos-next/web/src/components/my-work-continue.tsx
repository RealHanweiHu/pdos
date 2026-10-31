"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, FileText } from "@phosphor-icons/react";
import type { browserApi } from "@/lib/browser-api";
import styles from "./my-work.module.css";

type Proposal = { id: string; title: string; status: string; owner_id: string; categoryId: string; categoryName: string };
export function MyWorkContinue({ api, principalId, reload }: { api: typeof browserApi; principalId: string; reload: number }) {
  const [reading, setReading] = useState<{ api: typeof browserApi; principalId: string; reload: number; items: Proposal[]; error: string } | null>(null);
  const current = reading?.api === api && reading.principalId === principalId && reading.reload === reload ? reading : null;
  useEffect(() => {
    let live = true;
    void (async () => {
      const categories = await api<{ id: string; name: string }[]>("v1/categories");
      const outcomes = await Promise.allSettled(categories.map(async category => {
        const items: Proposal[] = [], seen = new Set<string>();
        let cursor: string | null = null;
        do {
          const page: { items: Proposal[]; next_cursor: string | null } = await api(`v1/categories/${category.id}/proposals?page_size=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
          if (!live) return [];
          items.push(...page.items.filter(item => item.owner_id === principalId && ["draft","returned"].includes(item.status)).map(item => ({ ...item, categoryId: category.id, categoryName: category.name })));
          cursor = page.next_cursor;
          if (cursor && seen.has(cursor)) throw new Error("提案分页未推进，请刷新。");
          if (cursor) seen.add(cursor);
        } while (cursor);
        return items;
      }));
      if (live) setReading({ api, principalId, reload, items: outcomes.flatMap(result => result.status === "fulfilled" ? result.value : []), error: outcomes.some(result => result.status === "rejected") ? "部分品类提案暂不可读，可刷新后重试。" : "" });
    })().catch(failure => { if (live) setReading({ api, principalId, reload, items: [], error: failure.message }); });
    return () => { live = false; };
  }, [api, principalId, reload]);
  return <section aria-label="继续完善提案" className={styles.continueSection}>
    <div className={styles.sectionHeading}><h2>继续提案</h2><Link className={styles.meta} href="/?area=category&focus=proposals" onClick={event => {
      if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      window.history.pushState(null, "", "/?area=category&focus=proposals");
      window.dispatchEvent(new PopStateEvent("popstate"));
    }}>全部提案<ArrowRight size={12}/></Link></div>
    {!current ? <p className={styles.queueNote} role="status">正在读取你的提案…</p> : <>{current.error && <p className={styles.queueNote} role="status">{current.error}</p>}{!current.items.length && !current.error && <p className={styles.queueNote}>暂无需要继续完善的提案。</p>}{current.items.slice(0,6).map(item => <a key={item.id} className={styles.continueRow} href={`/categories/${item.categoryId}/proposals/${item.id}`}><FileText size={14}/><strong>{item.title}</strong><span>{item.categoryName}</span><span>{item.status === "returned" ? "已退回" : "草稿"}</span><ArrowRight size={13}/></a>)}</>}
  </section>;
}
