"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, FileText, LockSimple } from "@phosphor-icons/react";
import type { browserApi } from "@/lib/browser-api";
import styles from "./my-work.module.css";

type Proposal = { id: string; title: string; status: string; owner_id: string; visibility?: string; entry_kind?: string; updated_at?: string; categoryId: string; categoryName: string };
const entries: Record<string, string> = { new_product: "自主新品", derivative: "派生迭代", customer_request: "客户需求" };
/** Short calendar date for 更新; an older server without the field shows a dash. */
const updated = (value?: string) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" }) : "—";
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
    {!current ? <p className={styles.queueNote} role="status">正在读取你的提案…</p> : <>{current.error && <p className={styles.queueNote} role="status">{current.error}</p>}{!current.items.length && !current.error && <p className={styles.queueNote}>暂无需要继续完善的提案。</p>}
      {current.items.length > 0 && <table className={styles.proposalTable}><thead><tr><th scope="col">提案</th><th scope="col">入口</th><th scope="col">状态</th><th scope="col">更新</th></tr></thead><tbody>
        {[...current.items].sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? "")).slice(0, 6).map(item => <tr key={item.id}>
          <td><a href={`/categories/${item.categoryId}/proposals/${item.id}`} title={`${item.title} · ${item.categoryName}`}><FileText size={14} aria-hidden="true"/><strong>{item.title}</strong>{item.visibility === "private" && <LockSimple size={12} aria-label="私有提案"/>}</a></td>
          <td>{entries[item.entry_kind ?? ""] ?? "—"}</td>
          <td><span className={styles.proposalStatus} data-status={item.status}>{item.status === "returned" ? "已退回" : "草稿"}</span></td>
          <td>{updated(item.updated_at)}</td>
        </tr>)}
      </tbody></table>}</>}
  </section>;
}
