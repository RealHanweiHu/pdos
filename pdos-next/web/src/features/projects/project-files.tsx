"use client";

import { useEffect, useState } from "react";
import { ArrowClockwise, FileText, MagnifyingGlass } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { browserApi } from "@/lib/browser-api";
import { parseStateNames, type OriginalFile } from "@/lib/original-security";
import styles from "./project-files.module.css";

export function ProjectFiles({ api, categoryId, productId, productName, manageHref }: { api: typeof browserApi; categoryId: string; productId: string; productName: string; manageHref: string }) {
  const [query, setQuery] = useState("");
  const [attempt, setAttempt] = useState(0);
  const key = `${categoryId}:${productId}:${attempt}`;
  const [reading, setReading] = useState<{ key: string; api: typeof browserApi; items: OriginalFile[]; error: string } | null>(null);
  const current = reading?.key === key && reading.api === api ? reading : null;
  useEffect(() => {
    let active = true;
    void api<{ product: { id: string }; originals: OriginalFile[] }>(`v1/categories/${categoryId}/products/${productId}/workspace`).then(value => {
      if (value.product.id !== productId || !Array.isArray(value.originals)) throw new Error("文件范围无法核对，请刷新。");
      if (active) setReading({ key, api, items: value.originals, error: "" });
    }).catch(failure => { if (active) setReading({ key, api, items: [], error: failure.message }); });
    return () => { active = false; };
  }, [api, categoryId, productId, key]);
  const items = current?.items.filter(item => `${item.title} ${item.filename}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) ?? [];
  return <section className={styles.files} aria-label="项目可用文件">
    <div className={styles.toolbar}><label className={styles.search}><MagnifyingGlass size={14}/><input type="search" aria-label="搜索项目文件" placeholder="搜索文件" value={query} onChange={event => setQuery(event.target.value)}/></label><a href={manageHref}>上传与管理</a><Button size="xs" variant="ghost" aria-label="刷新文件" onClick={() => setAttempt(value => value + 1)}><ArrowClockwise/></Button></div>
    <p className={styles.note}>来自 {productName} 的共享原件，按你的当前权限显示。</p>
    {!current ? <p role="status" className={styles.empty}>正在读取文件…</p> : current.error ? <p role="alert" className={styles.empty}>{current.error}</p> : !items.length ? <p className={styles.empty}>{query ? "没有符合条件的文件。" : "尚无可读文件。可上传原件，再用于项目任务和评审。"}</p> : <div className={styles.list}>{items.map(item => <details key={item.id} className={styles.row}><summary><FileText size={15}/><strong>{item.title || item.filename}</strong><span>{parseStateNames[item.status] ?? "状态待核对"}</span><small>{item.byte_count < 1024 ? `${item.byte_count} B` : `${Math.ceil(item.byte_count / 1024)} KB`}</small></summary><div className={styles.detail}><p>{item.filename}</p><span>{item.visibility === "private" ? "私有原件" : item.visibility === "category" ? "品类共享" : "按原件授权"}</span><a href={manageHref}>查看原件、来源与下载</a></div></details>)}</div>}
  </section>;
}
