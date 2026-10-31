"use client";

import { useEffect, useState } from "react";
import { Button } from "./ui/button";
import { SimilarHistoryCards } from "./similar-history";
import { similarHistorySuggestionsPath, type SimilarHistorySuggestions } from "@/lib/similar-history";
import styles from "./similar-history.module.css";

type Props = {
  api: <T>(path: string, body?: unknown) => Promise<T>;
  productId: string; projectId?: string; kind: "issue" | "change"; title: string;
};

/** Unsaved titles are read-only search inputs, never feedback origins or business objects. */
export function SimilarHistoryTitle({ api, productId, projectId, kind, title }: Props) {
  const query = title.trim(), eligible = query.length > 0 && [...query].length <= 240;
  const [attempt, setAttempt] = useState(0);
  const key = JSON.stringify([productId, projectId ?? null, kind, query, attempt]);
  const [response, setResponse] = useState<{ key: string; reading?: SimilarHistorySuggestions; error?: string } | null>(null);
  const current = response?.key === key ? response : null;
  useEffect(() => {
    if (!eligible) return;
    let active = true;
    const timer = setTimeout(() => {
      void api<SimilarHistorySuggestions>(similarHistorySuggestionsPath(productId, kind, query, projectId)).then(reading => {
        if (!active) return;
        if (reading.anchor.kind !== `${kind}_draft` || reading.anchor.title !== query
          || reading.anchor.product_id !== productId || (projectId && reading.anchor.project_id !== projectId)) {
          setResponse({ key, error: "标题或范围已变化，请重新查找。" });
        } else setResponse({ key, reading });
      }).catch(failure => {
        if (active) setResponse({ key, error: failure instanceof Error ? failure.message : "相似历史暂不可读，请稍后重试。" });
      });
    }, 400);
    return () => { active = false; clearTimeout(timer); };
  }, [api, eligible, key, productId, projectId, kind, query]);

  if (!query) return null;
  return <aside className={styles.panel} aria-label="标题防重复提示">
    <header><h3>建立前核对相似历史</h3>{eligible && <Button type="button" size="sm" variant="ghost" onClick={() => setAttempt(value => value + 1)}>重新查找标题</Button>}</header>
    {!eligible ? <p className={styles.note}>相似历史按标题查找；请将标题缩短至240字符后再查找。</p>
      : current?.error ? <p role="alert">{current.error}</p>
        : !current?.reading ? <p role="status">正在按标题查找本人可读的历史…</p>
          : <>
            <p className={styles.note}>相似不代表重复或适用；可打开原记录核对，再决定是否建立。</p>
            {current.reading.coverage.status === "partial" && <p role="status" className={styles.note}>部分可读资料尚未完成索引或依据复核，以下仅为当前找到的记录。</p>}
            {current.reading.items.length ? <details><summary>找到 {Math.min(current.reading.items.length, 5)} 条可读相似历史</summary>
              <SimilarHistoryCards items={current.reading.items} anchorLabel="当前标题"/>
            </details> : <p className={styles.note}>当前标题没有找到可读的相似历史，不能据此判断没有重复记录。</p>}
            <p className={styles.meta}>查找于 {new Date(current.reading.as_of).toLocaleString("zh-CN")}</p>
          </>}
  </aside>;
}
