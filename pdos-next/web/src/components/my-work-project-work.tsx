"use client";

import { ArrowClockwise, ArrowRight, Clock } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { PersonalProjectWorkState, PersonalWorkItem, PersonalWorkQueue } from "@/lib/personal-project-work";
import styles from "./my-work-project-work.module.css";

const names: Record<PersonalWorkQueue, string> = { receive: "要我接收的项目任务", verify: "要我验收的项目成果", tasks: "我的项目任务", commitments: "我作出的承诺" };
const states: Record<PersonalWorkItem["task"]["state"], string> = { proposed: "待分派", assigned: "待本人承接", accepted: "已承接", in_progress: "实际进行中", submitted: "待成果验收", completed: "成果已验收" };
function person(item: PersonalWorkItem, identity: string) { const found = [item.assignee, item.recipient].find(v => v?.id === identity); return found?.name ?? `未提供姓名（${identity}）`; }
function promisedDate(commitment: NonNullable<PersonalWorkItem["commitment"]>) { return commitment.promised_at === null ? "未知，未承诺日期" : new Intl.DateTimeFormat("zh-CN", { timeZone: commitment.original_timezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).format(new Date(commitment.promised_at)); }

export function PersonalProjectWorkQueue({ queue, state, onOpenProject }: { queue: PersonalWorkQueue; state: PersonalProjectWorkState; onOpenProject: (categoryId: string, projectId: string) => void }) {
  return <section className={styles.queue} aria-label={names[queue]}>
    <header className={styles.heading}><h3>{names[queue]}</h3><span>{state.totalRecords === null ? "数量未取得" : `已读 ${state.items.length} / 共 ${state.totalRecords} 条`}</span></header>
    {queue === "commitments" && <p className={styles.note}>任务验收与承诺履行分开；日期状态不代表履行结论。</p>}
    {state.status === "loading" ? <p className={styles.note} role="status">正在读取本人当前可见的项目队列…</p> : state.status === "error" ? <div className={styles.error} role="alert"><p>队列读取失败：{state.error}</p><Button type="button" size="xs" variant="outline" onClick={state.retry}><ArrowClockwise aria-hidden="true"/>重新读取队列</Button></div> : <>
      {state.items.length === 0 ? <p className={styles.note}>{state.totalRecords === 0 ? "当前可读范围内暂无此类项目记录。" : "本页暂无可展示记录，队列尚未完整读取。"}</p> : <div className={styles.cards}>{state.items.map(item => <article key={item.id} className={styles.card}>
        <div className={styles.context}>{item.category.name} <span>／ {item.product.name}</span></div><div className={styles.heading}><h4>{item.task.title}</h4><span className={styles.badge}>{states[item.task.state]}</span></div><p className={styles.project}>{item.project.name} · 当前任务 v{item.task.revision}</p>
        <dl className={styles.people}><div><dt>任务执行人</dt><dd>{item.assignee ? item.assignee.name ?? `未提供姓名（${item.assignee.id}）` : "尚未指定"}</dd></div><div><dt>{queue === "commitments" ? "本条承诺接收人" : "任务成果接收人"}</dt><dd>{item.recipient ? item.recipient.name ?? `未提供姓名（${item.recipient.id}）` : "尚未指定"}</dd></div></dl>
        {item.commitment && <div className={styles.commitment}><strong>本条个人承诺</strong><p>{person(item, item.commitment.promisor_id)} → {person(item, item.commitment.recipient_id)}</p><p>成果范围：{item.commitment.outcome_keys.join("、")}</p><p><Clock size={12} aria-hidden="true"/> 承诺时间：<time dateTime={item.commitment.promised_at ?? undefined}>{promisedDate(item.commitment)}</time></p><small>原时区 {item.commitment.original_timezone} · 日历 {item.commitment.calendar_id ?? "未登记"} · 固定任务 v{item.commitment.task_revision}</small><span className={styles.timing} data-overdue={item.timing === "overdue"}>{item.timing === "overdue" ? "本条承诺已逾期" : item.timing === "pending" ? "本条承诺尚未到期" : item.timing === "unknown" ? "本条承诺日期未知" : "时效状态未提供"}</span></div>}
        <p className={styles.note}>记录原时点 {item.recorded_at}</p><Button type="button" size="xs" variant="outline" onClick={() => onOpenProject(item.category.id, item.project.id)}>进入项目办理<ArrowRight aria-hidden="true"/></Button>
        <details className={styles.identity}><summary>固定记录与任务版本</summary><p>队列记录 {item.id}</p><p>稳定任务 {item.task.id} · 当前事实 {item.task.version_id} · v{item.task.revision}</p>{item.commitment && <p>承诺 {item.commitment.id} · v{item.commitment.revision}</p>}</details>
      </article>)}</div>}
      {state.moreError && <p role="alert" className={styles.error}>后续页读取失败：{state.moreError}。已读记录保留。</p>}
      {state.nextCursor !== null && <Button type="button" variant="outline" size="sm" disabled={state.loadingMore} onClick={() => void state.loadMore()}>{state.loadingMore ? "正在读取后续页…" : state.moreError ? "重试后续页" : "读取后续页"}</Button>}
      {state.asOf && <p className={styles.note}>读回时点 {state.asOf}。队列仅提供可读记录，请进入原项目办理。</p>}
    </>}
  </section>;
}
