"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ArrowRight } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { browserApi } from "@/lib/browser-api";
import { isPersonalG0Page, mergePersonalG0, personalG0Href, personalG0Path, type PersonalG0Review } from "@/lib/personal-g0-reviews";
import styles from "./my-work.module.css";

export type PersonalG0Queue = {
  items: PersonalG0Review[]; totalPending: number | null; nextCursor: string | null;
  asOf: string | null; loadingMore: boolean; error: string;
};
const empty = (): PersonalG0Queue => ({ items: [], totalPending: null, nextCursor: null, asOf: null, loadingMore: false, error: "" });

export function useMyWorkG0(api: typeof browserApi, principalId: string, reload: number) {
  const [retry, setRetry] = useState(0);
  const scope = JSON.stringify([principalId, reload, retry]);
  const [result, setResult] = useState<PersonalG0Queue & { scope: string }>({ ...empty(), scope });
  const generation = useRef(0), busy = useRef(false), usedCursors = useRef(new Set<string>());
  const queue: PersonalG0Queue = result.scope === scope ? result : empty();
  useEffect(() => {
    let active = true;
    const own = ++generation.current;
    busy.current = true; usedCursors.current = new Set();
    void (async () => {
      const value = await api<unknown>(personalG0Path());
      if (!active || generation.current !== own) return;
      if (!isPersonalG0Page(value, principalId)) throw new Error("G0 队列与当前本人身份不一致，或资料不完整，请重新读取。");
      const items = mergePersonalG0([], value.items);
      if (items.length > value.total_pending || value.next_cursor === null && items.length !== value.total_pending) throw new Error("G0 队列分页不完整，请重新读取。");
      setResult({ scope, items, totalPending: value.total_pending, nextCursor: value.next_cursor, asOf: value.as_of, loadingMore: false, error: "" });
    })().catch(failure => { if (active && generation.current === own) setResult({ ...empty(), scope, error: (failure as Error).message }); })
      .finally(() => { if (active && generation.current === own) busy.current = false; });
    return () => { active = false; };
  }, [api, principalId, scope]);

  function refresh() { generation.current++; setRetry(value => value + 1); }
  async function loadMore() {
    if (busy.current || !queue.nextCursor || queue.totalPending === null) return;
    busy.current = true;
    const own = generation.current, cursor = queue.nextCursor;
    setResult(previous => ({ ...previous, loadingMore: true }));
    try {
      if (usedCursors.current.has(cursor)) throw new Error("G0 分页位置重复，请重新读取队列。");
      usedCursors.current.add(cursor);
      const value = await api<unknown>(personalG0Path(cursor));
      if (generation.current !== own) return;
      if (!isPersonalG0Page(value, principalId)) throw new Error("G0 队列与当前本人身份不一致，或资料不完整，请重新读取。");
      if (value.total_pending !== queue.totalPending) throw new Error("待评审的 G0 队列已有变化，请重新读取。");
      if (value.next_cursor && usedCursors.current.has(value.next_cursor)) throw new Error("G0 分页位置未推进，请重新读取队列。");
      const items = mergePersonalG0(queue.items, value.items);
      if (items.length > value.total_pending || value.next_cursor === null && items.length !== value.total_pending) throw new Error("G0 队列分页不完整，请重新读取。");
      setResult({ scope, items, totalPending: value.total_pending, nextCursor: value.next_cursor, asOf: value.as_of, loadingMore: false, error: "" });
    } catch (failure) {
      if (generation.current === own) setResult({ ...empty(), scope, error: (failure as Error).message });
    } finally { if (generation.current === own) busy.current = false; }
  }
  return { ...queue, refresh, loadMore };
}

export function MyWorkG0({ queue }: { queue: ReturnType<typeof useMyWorkG0> }) {
  return <section className={styles.g0Queue} aria-label="待我决定的G0评审">
    {queue.error ? <div className={styles.emptyCard} role="alert"><p>G0 决定队列暂不可读：{queue.error}</p><Button type="button" size="xs" variant="outline" onClick={queue.refresh}>重新读取 G0 队列</Button></div>
      : queue.totalPending === null ? <p className={styles.emptyCard} role="status">正在读取本人待决定的 G0 评审…</p> : <>
        <p className={styles.g0Summary}>已加载 <b>{queue.items.length}</b> / 全部 <b>{queue.totalPending}</b> 项 G0 评审</p>
        {queue.items.map(item => <article className={styles.workcard} key={item.proposal_id}>
          <div className={styles.cardTop}><div className={styles.g0Title}><p>G0 立项评审待我决定</p><h3>{item.title}</h3></div><span className={styles.pending}>待决定</span></div>
          <div className={styles.cardMeta}><span>{item.category.name}</span><span>负责人：{item.owner.name ?? "姓名未提供"}</span><span>当前提案 v{item.proposal_revision}</span></div>
          <div className={styles.cardMeta}><span>固定提交 v{item.submission.revision}</span><span>提交于 <time dateTime={item.submission.submitted_at}>{new Date(item.submission.submitted_at).toLocaleString()}</time></span></div>
          <div className={styles.cardActions}><Link className={styles.g0Link} href={personalG0Href(item)} prefetch={false}>打开 G0 评审包<ArrowRight size={12} aria-hidden="true"/></Link></div>
        </article>)}
        {queue.totalPending === 0 && <p className={styles.emptyCard}>当前没有需要本人具名决定的 G0 立项评审。</p>}
        {queue.nextCursor && <Button type="button" size="xs" variant="outline" disabled={queue.loadingMore} onClick={() => { void queue.loadMore(); }}>{queue.loadingMore ? "正在加载 G0…" : "加载更多 G0 评审"}</Button>}
        {queue.asOf && <p className={styles.g0AsOf}>G0 队列读取于 <time dateTime={queue.asOf}>{new Date(queue.asOf).toLocaleString()}</time></p>}
      </>}
  </section>;
}
