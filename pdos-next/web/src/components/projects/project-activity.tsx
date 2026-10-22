"use client";

import { ArrowRight, ArrowClockwise, Clock, Sparkle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { activityRunStates, projectActivityHref, useProjectActivity, type ProjectActivityItem } from "@/lib/project-activity";
import type { ProjectWorkApi, WorkScope } from "@/lib/project-work";
import styles from "./project-activity.module.css";

const person = (value: { id: string; name: string | null }) => value.name ? `${value.name} · ${value.id}` : value.id;
function Moment({ value }: { value: string }) { return <time dateTime={value}>{value}</time>; }
function Activity({ item, scope, onOpenRun }: { item: ProjectActivityItem; scope: WorkScope; onOpenRun?: (id: string) => void }) {
  const runEvent = item.record_kind === "run_event";
  return <li className={styles.item}>
    <div className={styles.line}><span className={styles.badge}>{runEvent ? "本人项目运行" : item.actor.kind === "ai" ? <><Sparkle size={13} aria-hidden="true"/>小Pai 实际操作</> : item.actor.kind === "human" ? "具名操作" : "已登记操作"}</span><span className={styles.clock}><Clock size={13} aria-hidden="true"/>记录于 <Moment value={item.recorded_at}/></span></div>
    <h3>{item.summary}</h3>
    {item.subject.title && item.subject.title !== item.summary && <p className={styles.title}>{item.subject.title}</p>}
    <dl className={styles.facts}>
      <dt>{runEvent ? "绑定执行身份" : "执行人"}</dt><dd>{person(item.actor)}</dd><dt>请求人</dt><dd>{person(item.requester)}</dd>
      <dt>{runEvent ? "运行与事件序号" : "固定对象"}</dt><dd>{item.subject.kind} · {item.subject.id} · {runEvent ? `事件序号 ${item.subject.revision}` : `v${item.subject.revision}`}</dd>
      {runEvent && <><dt>事件状态</dt><dd>{item.status === null ? "本事件未记录状态" : activityRunStates[item.status]}</dd></>}
      <dt>实际发生</dt><dd>{item.occurred_at ? <Moment value={item.occurred_at}/> : "未登记发生时间"}{item.original_timezone && <span> · 原时区 {item.original_timezone}</span>}</dd>
      {item.next_steps !== null && <><dt>下一步</dt><dd>{item.next_steps || "未登记"}</dd></>}
    </dl>
    <details className={styles.details}><summary>{runEvent ? "运行事件记录" : "回执、事件与固定引用"}</summary><dl className={styles.facts}><dt>{runEvent ? "记录类型" : "实际操作"}</dt><dd>{item.operation}</dd><dt>事件</dt><dd>{item.event_type} · {item.id}</dd><dt>回执</dt><dd>{item.receipt_id ?? "无业务写入回执"}</dd></dl>
      {item.task_refs.length > 0 && <ul aria-label="固定任务版本">{item.task_refs.map(ref => <li key={`${ref.id}:${ref.revision}`}>任务 {ref.id} · v{ref.revision}</li>)}</ul>}
      {item.sources.length > 0 ? <ul aria-label="来源引用">{item.sources.map((source, index) => <li key={`${source.kind}:${source.id}:${source.revision}:${index}`}>{source.kind} · {source.id} · v{source.revision}{source.position !== undefined && <> · {source.position}</>}</li>)}</ul> : <p>本条未登记原文引用。</p>}
    </details>
    <div className={styles.actions}>{item.link && <a href={projectActivityHref(scope, item.link.view)}>{item.link.label}<ArrowRight size={14} aria-hidden="true"/></a>}{item.run_id && (onOpenRun ? <Button variant="outline" onClick={() => onOpenRun(item.run_id!)}>打开本次小Pai运行</Button> : <span className={styles.run}>运行 {item.run_id}</span>)}</div>
  </li>;
}
export function ProjectActivity({ api, scope, readVersion = 0, onOpenRun }: { api: ProjectWorkApi; scope: WorkScope; readVersion?: number; onOpenRun?: (id: string) => void }) {
  const state = useProjectActivity(api, scope, readVersion);
  return <section className={styles.root} aria-label="项目动态" aria-busy={state.status === "loading" || state.loadingMore}>
    <header className={styles.heading}><div><h2>项目动态</h2><p>本项目的实际业务记录、具名回执，以及本人绑定本项目的小Pai运行。</p></div><Button variant="outline" onClick={state.refresh}><ArrowClockwise size={14} aria-hidden="true"/>刷新动态</Button></header>
    {state.status === "loading" && <p className={styles.notice} role="status">正在读取项目动态…</p>}
    {state.status === "error" && <p className={styles.error} role="alert">项目动态读取失败：{state.error}</p>}
    {state.status === "ready" && state.page && <><p className={styles.note}>读取时点 <Moment value={state.page.as_of}/> · {state.page.project.name} v{state.page.project.revision}</p>{state.page.items.length === 0 ? <p className={styles.notice}>当前权限下尚无可读的项目活动。</p> : <ol className={styles.list}>{state.page.items.map(item => <Activity key={item.id} item={item} scope={scope} onOpenRun={onOpenRun}/>)}</ol>}{state.moreError && <p className={styles.error} role="alert">加载更多失败：{state.moreError}</p>}{state.page.next_cursor && <div><Button variant="outline" disabled={state.loadingMore} onClick={() => void state.loadMore()}>{state.loadingMore ? "正在加载…" : state.moreError ? "重试加载更多" : "加载更多动态"}</Button></div>}</>}
  </section>;
}
