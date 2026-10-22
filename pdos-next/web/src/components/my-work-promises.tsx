"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { browserApi } from "@/lib/browser-api";
import { isPersonalTestStartPromisePage, mergeTestStartPromises, originalTestStartTime, personalTestStartPromisesPath, testStartWorkbenchHref, type PersonalTestStartPromise } from "@/lib/personal-test-start-promises";
import styles from "./my-work.module.css";

type Queue = { items: PersonalTestStartPromise[]; totalRecords: number | null; nextCursor: string | null; asOf: string | null; loadingMore: boolean; error: string };
const empty = (): Queue => ({ items: [], totalRecords: null, nextCursor: null, asOf: null, loadingMore: false, error: "" });
const timingLabels: Record<PersonalTestStartPromise["timing"], string> = { awaiting_start: "尚未登记实际开测", past_due_no_start_record: "承诺时点已过，未登记开测", started_on_or_before: "实际开测未晚于承诺", started_late: "实际开测晚于承诺" };
const runLabels: Record<PersonalTestStartPromise["run"]["status"], string> = { planned: "已计划", running: "进行中", results_pending: "待结果", reviewed: "已评审", disposed: "已处置" };
const shortId = (id: string) => id.length > 12 ? id.slice(0, 8) : id;

export function useMyWorkPromises(api: typeof browserApi, principalId: string, reload: number) {
  const [retry, setRetry] = useState(0);
  const scope = JSON.stringify([principalId, reload, retry]);
  const [result, setResult] = useState<Queue & { scope: string }>({ ...empty(), scope });
  const generation = useRef(0), busy = useRef(false), usedCursors = useRef(new Set<string>());
  const queue: Queue = result.scope === scope ? result : empty();
  useEffect(() => {
    let active = true;
    const own = ++generation.current;
    busy.current = true; usedCursors.current = new Set();
    void (async () => {
      const value = await api<unknown>(personalTestStartPromisesPath());
      if (!active || generation.current !== own) return;
      if (!isPersonalTestStartPromisePage(value, principalId)) throw new Error("开测承诺记录与当前本人身份不一致，或资料不完整，请重新读取。");
      const items = mergeTestStartPromises([], value.items);
      if (items.length > value.total_records || value.next_cursor === null && items.length !== value.total_records) throw new Error("开测承诺记录分页不完整，请重新读取。");
      setResult({ scope, items, totalRecords: value.total_records, nextCursor: value.next_cursor, asOf: value.as_of, loadingMore: false, error: "" });
    })().catch(failure => { if (active && generation.current === own) setResult({ ...empty(), scope, error: (failure as Error).message }); })
      .finally(() => { if (active && generation.current === own) busy.current = false; });
    return () => { active = false; };
  }, [api, principalId, scope]);

  function refresh() { generation.current++; setRetry(value => value + 1); }
  async function loadMore() {
    if (busy.current || !queue.nextCursor || queue.totalRecords === null) return;
    busy.current = true;
    const own = generation.current, cursor = queue.nextCursor;
    setResult(previous => ({ ...previous, loadingMore: true }));
    try {
      if (usedCursors.current.has(cursor)) throw new Error("开测承诺记录分页位置重复，请重新读取。");
      usedCursors.current.add(cursor);
      const value = await api<unknown>(personalTestStartPromisesPath(cursor));
      if (generation.current !== own) return;
      if (!isPersonalTestStartPromisePage(value, principalId)) throw new Error("开测承诺记录与当前本人身份不一致，或资料不完整，请重新读取。");
      if (value.total_records !== queue.totalRecords) throw new Error("开测承诺记录已有变化，请重新读取。");
      if (value.next_cursor && usedCursors.current.has(value.next_cursor)) throw new Error("开测承诺记录分页位置未推进，请重新读取。");
      const items = mergeTestStartPromises(queue.items, value.items);
      if (items.length > value.total_records || value.next_cursor === null && items.length !== value.total_records) throw new Error("开测承诺记录分页不完整，请重新读取。");
      setResult({ scope, items, totalRecords: value.total_records, nextCursor: value.next_cursor, asOf: value.as_of, loadingMore: false, error: "" });
    } catch (failure) {
      if (generation.current === own) setResult({ ...empty(), scope, error: (failure as Error).message });
    } finally { if (generation.current === own) busy.current = false; }
  }
  return { ...queue, refresh, loadMore };
}

export function MyWorkPromises({ queue }: { queue: ReturnType<typeof useMyWorkPromises> }) {
  return <div className={styles.promiseQueue} aria-label="我作出的开测承诺记录">
    <h3>我作出的开测承诺记录（已接测试）</h3>
    {queue.error ? <div className={styles.promiseNotice} role="alert"><p>开测承诺记录暂不可读：{queue.error}</p><Button type="button" size="xs" variant="outline" onClick={queue.refresh}>重新读取开测承诺记录</Button></div>
      : queue.totalRecords === null ? <p className={styles.promiseNotice} role="status">正在读取本人作出的开测承诺记录…</p> : <>
        <p className={styles.promiseSummary}>已加载 <b>{queue.items.length}</b> / 全部 <b>{queue.totalRecords}</b> 条记录</p>
        {queue.items.map(item => <article className={styles.promiseCard} key={item.id}>
          <div className={styles.promiseHeading}><h4>{item.project.name} · {item.build.name}</h4><span data-timing={item.timing}>{timingLabels[item.timing]}</span></div>
          <p className={styles.promiseScope}>{item.category.name} · {item.product.name}</p>
          <dl className={styles.promiseTimes}><div><dt>承诺开测</dt><dd><time dateTime={item.promise.occurred_at}>{originalTestStartTime(item.promise)}</time></dd></div><div><dt>实际开测</dt><dd>{item.actual_start ? <time dateTime={item.actual_start.occurred_at}>{originalTestStartTime(item.actual_start)}</time> : "尚未登记"}</dd></div></dl>
          <p className={styles.promiseRecipient}>接收方尚未记录</p>
          <p className={styles.promiseCoverage}>样件 {item.coverage.sample_count} · 测试项 {item.coverage.item_count} · 配对 {item.coverage.pair_count}</p>
          <p className={styles.promiseIds}>Build {shortId(item.build.id)} · 请求 {shortId(item.request.id)} · Run {shortId(item.run.id)} v{item.run.revision} · {runLabels[item.run.status]}</p>
          <p className={styles.promiseRecorded}>记录于 <time dateTime={item.recorded_at}>{new Date(item.recorded_at).toLocaleString()}</time></p>
          <details className={styles.promiseDetails}><summary>固定范围与时间原值</summary><dl><div><dt>承诺记录</dt><dd>{item.id}</dd></div>{[["品类", item.category], ["型号", item.product], ["项目", item.project], ["Build", item.build], ["请求", item.request], ["Run", item.run]].map(([label, value]) => <div key={String(label)}><dt>{String(label)}</dt><dd>{(value as { id: string }).id}</dd></div>)}<div><dt>承诺时点原值</dt><dd>{item.promise.occurred_at}</dd></div><div><dt>承诺生效时点</dt><dd>{item.promise.effective_at ?? "未单独登记"}</dd></div>{item.actual_start && <><div><dt>实际开测原值</dt><dd>{item.actual_start.occurred_at}</dd></div><div><dt>实际生效时点</dt><dd>{item.actual_start.effective_at ?? "未单独登记"}</dd></div><div><dt>开测事实接收时点</dt><dd>{item.actual_start.received_at}</dd></div></>}</dl></details>
          <a className={styles.promiseLink} href={testStartWorkbenchHref(item)}>进入测试工作台<ArrowRight size={11} aria-hidden="true"/></a><p className={styles.promiseSelection}>进入后仍需选择上述 Build、请求与 Run。</p>
        </article>)}
        {queue.totalRecords === 0 && <p className={styles.promiseNotice}>当前可读范围内没有本人作出的测试开测承诺记录。</p>}
        {queue.nextCursor && <Button type="button" size="xs" variant="outline" disabled={queue.loadingMore} onClick={() => { void queue.loadMore(); }}>{queue.loadingMore ? "正在加载记录…" : "加载更多开测承诺记录"}</Button>}
        {queue.asOf && <p className={styles.promiseAsOf}>读取于 <time dateTime={queue.asOf}>{new Date(queue.asOf).toLocaleString()}</time></p>}
      </>}
    <p className={styles.promiseLimitations}>仅展示本人作出的测试开测承诺记录，接收方尚未记录。外部等待与其他通用承诺仍未接入。</p>
  </div>;
}
