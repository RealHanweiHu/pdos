"use client";

import { useState } from "react";
import { ArrowClockwise, ArrowRight, Warning } from "@phosphor-icons/react";
import { PersonalSummaryInbox } from "./personal-summary-inbox";
import { Button } from "@/components/ui/button";
import { personalAttentionHref, usePersonalAttention, type AttentionQueue, type PersonalAttentionApi, type PersonalAttentionItem, type PersonalAttentionState } from "@/lib/personal-attention";
import styles from "./my-work-attention.module.css";

export const attentionQueueNames: Record<AttentionQueue, string> = { decide: "要我决定", receive: "要我接收", verify: "要我验证", external: "等外部回复" };
const responsibilities: Record<string, string> = { named_assignee: "当前承接人", named_recipient: "成果接收人", promise_recipient: "承诺接收人", named_reviewer: "具名审阅人", original_owner: "原移交负责人", named_return_owner: "退回记录的下一负责人" };
const responsibilityName = (value: string) => responsibilities[value] ?? (/^[a-z][a-z0-9_]*$/.test(value) ? "已登记的本人责任" : value);
const stages = { sent: "发送", accepted: "接收", effective: "生效" };
const stageNames: Record<string, string> = { not_recorded: "未登记", unknown: "结果未知", conflict: "回执冲突", partial: "范围不完整", succeeded: "已成功", failed: "未成功", rejected: "已拒绝" };
const workStates: Record<string, string> = { assigned: "待本人承接", submitted: "待成果验收", in_review: "待具名审阅", open: "履行待核对", offered: "已交样", accepted: "已登记接收", scheduled: "已安排", executing: "执行中", running: "测试进行中", authorized: "已授权", sent: "已登记发送", acknowledged: "已登记接收", reconciled: "已登记生效" };
function stageState(item: PersonalAttentionItem, stage: keyof typeof stages) {
  const value = item.details[`${stage}_state`] ?? item.details[stage];
  return typeof value === "string" ? value : null;
}
function AttentionCard({ item }: { item: PersonalAttentionItem }) {
  const href = personalAttentionHref(item);
  return <details className={styles.card}><summary className={styles.summary}><span>{item.title}</span><small>{item.project?.name ?? item.category.name}</small><span className={styles.state}>{workStates[item.state] ?? item.state}</span></summary><div className={styles.detailBody}>
    <p className={styles.context}>{[item.category.name, item.product?.name, item.project?.name].filter(Boolean).join(" ／ ")}</p>
    <div className={styles.heading}><h4>{item.title}</h4><span className={styles.state} title={item.state}>{workStates[item.state] ?? item.state}</span></div>
    <p className={styles.reason}>{item.reason}</p>
    <dl className={styles.facts}>
      <div><dt>当前责任人</dt><dd>{item.responsible.name ?? `未提供姓名（${item.responsible.id}）`}</dd></div>
      <div><dt>本人关系</dt><dd>{responsibilityName(item.responsibility)}</dd></div>
      {item.source.revision !== null && <div><dt>固定来源版本</dt><dd>v{item.source.revision}</dd></div>}
      {item.due_at && <div><dt>原定期限</dt><dd><time dateTime={item.due_at}>{item.due_at}</time></dd></div>}
      {item.valid_until && <div><dt>当前办理授权有效至</dt><dd><time dateTime={item.valid_until}>{item.valid_until}</time></dd></div>}
    </dl>
    {typeof item.details.coverage_count === "number" && Number.isSafeInteger(item.details.coverage_count) && item.details.coverage_count > 0 && <p className={styles.note}>待补范围 {item.details.coverage_count} 项</p>}
    {(Object.keys(stages) as (keyof typeof stages)[]).some(stage => stageState(item, stage) !== null) && <dl className={styles.stages}>{(Object.keys(stages) as (keyof typeof stages)[]).map(stage => {
      const value = stageState(item, stage);
      return value === null ? null : <div key={stage}><dt>{stages[stage]}</dt><dd>{stageNames[value] ?? value}</dd></div>;
    })}</dl>}
    {item.blocked && <p className={styles.blocked}><Warning size={14} aria-hidden="true"/><span>{item.blocked.message} <small>（{item.blocked.code}）</small></span></p>}
    {href && <a className={styles.open} href={href}>{item.target === "proposal" ? "查看原提案" : "查看原项目"}<ArrowRight size={13} aria-hidden="true"/></a>}
    <details className={styles.identity}><summary>来源与版本</summary><p>责任关系 {item.responsibility}</p>{typeof item.details.task_id === "string" && <p>稳定任务 {item.details.task_id}{typeof item.details.task_revision === "number" && Number.isSafeInteger(item.details.task_revision) && item.details.task_revision > 0 ? ` · v${item.details.task_revision}` : ""}</p>}{typeof item.details.submission_id === "string" && <p>提交记录 {item.details.submission_id}{typeof item.details.submission_revision === "number" && Number.isSafeInteger(item.details.submission_revision) && item.details.submission_revision > 0 ? ` · v${item.details.submission_revision}` : ""}</p>}<p>来源类型 {item.kind} · 稳定来源 {item.source.id}</p>{item.source.version_id && <p>固定事实 {item.source.version_id}</p>}{item.source.revision !== null && <p>来源版本 v{item.source.revision}</p>}{item.source.epoch !== null && <p>当前水位 {item.source.epoch}</p>}<p>记录时点 <time dateTime={item.recorded_at}>{item.recorded_at}</time></p></details>
  </div></details>;
}

export function PersonalAttentionQueue({ queue, state }: { queue: AttentionQueue; state: PersonalAttentionState }) {
  return <section className={styles.queue} aria-label={attentionQueueNames[queue]}>
    <header className={styles.heading}><h3>{attentionQueueNames[queue]}</h3><span className={styles.count}>{state.totalRecords === null ? "数量未取得" : `已读 ${state.items.length} / 共 ${state.totalRecords} 条`}</span></header>
    {state.status === "loading" ? <p className={styles.note} role="status">正在读取本人当前可见的注意项…</p> : state.status === "error" ? <div className={styles.error} role="alert"><p>注意项读取失败：{state.error}</p><Button type="button" size="xs" variant="outline" onClick={state.retry}><ArrowClockwise aria-hidden="true"/>重新读取注意项</Button></div> : <>
      {state.items.length > 0 ? <div className={styles.cards}>{state.items.map(item => <AttentionCard key={item.id} item={item}/>)}</div> : <p className={styles.note}>{state.totalRecords === 0 ? "当前可读范围内暂无此类注意项。" : "本页暂无可展示记录，队列尚未完整读取。"}</p>}
      {state.moreError && <p className={styles.error} role="alert">后续页读取失败：{state.moreError}。已读记录保留。</p>}
      {state.nextCursor !== null && <Button type="button" variant="outline" size="sm" disabled={state.loadingMore} onClick={() => void state.loadMore()}>{state.loadingMore ? "正在读取后续页…" : state.moreError ? "重试后续页" : "读取后续页"}</Button>}
      {state.asOf && <details className={styles.readInfo}><summary>读取信息</summary><p className={styles.note}>读回时点 {state.asOf}。请在原对象查看当前资料并办理。</p></details>}
    </>}
  </section>;
}

export function PersonalAttention({ api, principalId, reload }: { api: PersonalAttentionApi; principalId: string; reload: number }) {
  const decide = usePersonalAttention(api, principalId, reload, "decide");
  const receive = usePersonalAttention(api, principalId, reload, "receive");
  const verify = usePersonalAttention(api, principalId, reload, "verify");
  const external = usePersonalAttention(api, principalId, reload, "external");
  const [selected, setSelected] = useState<AttentionQueue | "summaries">("decide");
  const queues = { decide, receive, verify, external };
  return <div className={styles.groups}><nav className={styles.filters} aria-label="待办类型">{(Object.keys(attentionQueueNames) as AttentionQueue[]).map(queue => <button type="button" key={queue} aria-pressed={selected === queue} onClick={() => setSelected(queue)}>{attentionQueueNames[queue]}<span>{queues[queue].totalRecords ?? "—"}</span></button>)}<button type="button" aria-pressed={selected === "summaries"} onClick={() => setSelected("summaries")}>我的摘要</button></nav>{selected === "summaries" ? <PersonalSummaryInbox api={api} principalId={principalId}/> : <PersonalAttentionQueue queue={selected} state={queues[selected]}/>}</div>;
}
