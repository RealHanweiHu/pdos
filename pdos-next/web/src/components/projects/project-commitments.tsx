"use client";

import { useEffect, useState } from "react";
import { Handshake } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { readProjectWork, workRecord, workSame, workUuid } from "@/lib/project-work";
import type { ProjectWorkApi, ProjectWorkView, WorkCommitment, WorkScope } from "@/lib/project-work";
import { readFulfillment } from "@/lib/commitment-fulfillment";
import type { FulfillmentCommitment, FulfillmentReview, FulfillmentView } from "@/lib/commitment-fulfillment";
import styles from "./project-commitments.module.css";

type Props = WorkScope & { api: ProjectWorkApi; readVersion: number };
type FixedCommitment = WorkCommitment & { task_revision: number; recorded_at: string };
type PairedCommitment = { commitment: FixedCommitment; projection: FulfillmentCommitment };
type CommitmentReading = { view: ProjectWorkView; fulfillment: FulfillmentView; commitments: PairedCommitment[] };
const taskStates: Record<string, string> = { proposed: "已提出", assigned: "已分派", accepted: "已承接", in_progress: "执行中", submitted: "已提交成果", completed: "已完成" };
const rawInstant = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));

/** The shared readers preserve these Snapshot fields beyond their older TS declarations. */
function fixedCommitment(value: unknown): FixedCommitment {
  if (!workRecord(value) || !Number.isSafeInteger(value.task_revision) || Number(value.task_revision) < 1 || !rawInstant(value.recorded_at) || !rawInstant(value.created_at)
    || !(value.replaces === null || workRecord(value.replaces) && workUuid(value.replaces.id) && Number.isSafeInteger(value.replaces.revision) && Number(value.replaces.revision) > 0)) throw new Error("承诺固定任务版本或登记时点未完整取得，不能用当前任务资料补齐。");
  return value as FixedCommitment;
}
export function currentProjectCommitments(view: ProjectWorkView): FixedCommitment[] {
  const current = view.commitments.filter(item => item.status === "current");
  if (new Set(current.map(item => item.id)).size !== current.length) throw new Error("当前承诺记录的身份无法核对，请重新读取。");
  return current.map(fixedCommitment);
}

/** Independently read heads must agree before any fulfillment state is published. */
export function pairProjectCommitments(view: ProjectWorkView, fulfillment: FulfillmentView): PairedCommitment[] {
  const mismatch = () => { throw new Error("承诺与履行资料的固定范围或版本未能配对，请重新读取；未配对的记录不能当作尚未核对或空列表。"); };
  if (view.project.id !== fulfillment.project.id || view.project.revision !== fulfillment.project.revision || view.product_revision !== fulfillment.product_revision) mismatch();
  const commitments = currentProjectCommitments(view), projections = fulfillment.commitments.filter(item => item.status === "current");
  const byId = new Map(projections.map(item => [item.id, item]));
  if (byId.size !== projections.length || commitments.length !== projections.length) mismatch();
  const keys = ["id", "revision", "task_id", "task_revision", "promisor_id", "recipient_id", "outcome_keys", "promised_at", "original_timezone", "calendar_id", "recorded_at", "created_at", "replaces"] as const;
  return commitments.map(commitment => {
    const projection = byId.get(commitment.id);
    if (!projection) return mismatch();
    const fixed = fixedCommitment(projection);
    if (keys.some(key => !workSame(commitment[key], fixed[key]))) mismatch();
    const task = view.tasks.find(item => item.id === commitment.task_id);
    if (!task || !["id", "version_id", "revision", "state", "title"].every(key => workSame(task[key as keyof typeof task], projection.task[key as keyof typeof projection.task]))) mismatch();
    const records = projection.fulfillment.history;
    if (records.some(record => record.state !== (record.decision === "accepted" ? "fulfilled" : "open"))) mismatch();
    return { commitment, projection };
  });
}

export function ProjectCommitments(props: Props) {
  return <ScopedProjectCommitments key={JSON.stringify([props.principalId, props.categoryId, props.productId, props.projectId, props.readVersion])} {...props} />;
}

function ScopedProjectCommitments({ api, categoryId, productId, projectId, principalId }: Props) {
  const [attempt, setAttempt] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [reading, setReading] = useState<{ api: ProjectWorkApi; attempt: number; data: CommitmentReading | null; error: string } | null>(null);
  const current = reading?.api === api && reading.attempt === attempt ? reading : null;
  const data = current?.data ?? null, error = current?.error ?? "";
  useEffect(() => {
    let active = true;
    const scope = { categoryId, productId, projectId, principalId };
    void Promise.all([readProjectWork(api, scope), readFulfillment(api, scope)]).then(([view, fulfillment]) => {
      const commitments = pairProjectCommitments(view, fulfillment);
      if (active) setReading({ api, attempt, data: { view, fulfillment, commitments }, error: "" });
    }).catch(failure => { if (active) setReading({ api, attempt, data: null, error: failure instanceof Error ? failure.message : "项目承诺资料暂不可读。" }); });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, principalId, attempt]);
  const refresh = () => { setAttempt(value => value + 1); setExpanded(false); };
  const shown = data ? expanded ? data.commitments : data.commitments.slice(0, 3) : [];
  return <section className={styles.panel} aria-label="项目关键承诺">
    <header className={styles.heading}><h2><Handshake size={15} aria-hidden="true" />关键承诺</h2><Button type="button" size="xs" variant="ghost" onClick={refresh}>刷新承诺</Button></header>
    {error ? <div className={styles.notice} role="alert"><p>关键承诺暂不可读：{error}</p><Button type="button" size="xs" variant="outline" onClick={refresh}>重新读取承诺</Button></div> : !data ? <p className={styles.notice} role="status">正在读取本项目承诺记录…</p> : <>
      <p className={styles.summary}>已读取当前版本人工任务承诺 {data.commitments.length} 条。接收人不同的记录分别保留。</p>
      {data.commitments.length === 0 ? <p className={styles.notice}>当前可读范围内尚无当前版本人工任务承诺。</p> : <div className={styles.list}>{shown.map(item => <CommitmentRow key={item.commitment.id} value={item.commitment} projection={item.projection} view={data.view} />)}</div>}
      {data.commitments.length > 3 && <Button type="button" size="xs" variant="ghost" className={styles.expand} aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? "收起承诺记录" : `展开其余 ${data.commitments.length - 3} 条当前记录`}</Button>}
      <details className={styles.readTime}><summary>承诺与履行口径</summary><p className={styles.foot}>履行只按本条固定承诺的具名核对记录展示；任务完成状态不替代履行结论。尚未具名核对不代表事实未完成。测试开测、供应与外部等其他承诺尚未汇入此面板。</p></details>
      <details className={styles.readTime}><summary>本次读取时点</summary><p>任务与承诺读集：<time dateTime={data.view.as_of}>{data.view.as_of}</time></p><p>履行读集：<time dateTime={data.fulfillment.as_of}>{data.fulfillment.as_of}</time></p></details>
    </>}
  </section>;
}

function CommitmentRow({ value, projection, view }: { value: FixedCommitment; projection: FulfillmentCommitment; view: ProjectWorkView }) {
  const member = (id: string) => { const matches = view.members.filter(item => item.id === id); return matches.length === 1 ? matches[0].name : "姓名暂不可读"; };
  const task = view.tasks.find(item => item.id === value.task_id);
  return <article className={styles.row} aria-label={`承诺记录 ${value.id}`}>
    <div className={styles.people}><p><span>承诺人</span><strong>{member(value.promisor_id)}</strong></p><p><span>接收人</span><strong>{member(value.recipient_id)}</strong></p></div>
    <p className={styles.task}>当前任务：{task?.title ?? "任务名称暂不可读"}</p>
    <p className={styles.meta}>承诺记录 v{value.revision} · 固定任务 v{value.task_revision}{task ? ` · 当前任务 v${task.revision}` : " · 当前任务版本暂不可读"}</p>
    <div className={styles.time}><span>承诺时点</span>{value.promised_at ? <time dateTime={value.promised_at}>{value.promised_at}</time> : <strong>日期未知</strong>}</div>
    <p className={styles.meta}>约定成果 {value.outcome_keys.length} 项</p>
    <FulfillmentReading value={projection} members={view.members} />
    <details className={styles.details}><summary>固定范围与原始时点</summary><dl>
      <div><dt>本承诺固定任务</dt><dd>{value.task_id} · v{value.task_revision}</dd></div>
      <div><dt>当前任务版本</dt><dd>{task ? `v${task.revision} · ${taskStates[task.state] ?? "状态暂不可读"}` : "当前任务暂不可读"}</dd></div>
      <div><dt>承诺成果键（原值）</dt><dd><ul>{value.outcome_keys.map(key => <li key={key}><code>{key}</code></li>)}</ul></dd></div>
      <div><dt>当前任务成果说明</dt><dd><p className={styles.context}>以下仅为当前任务上下文，不是承诺时的固定成果正文。</p><ul>{value.outcome_keys.map(key => <li key={key}><code>{key}</code>：{task?.outcomes.find(outcome => outcome.key === key)?.text ?? "当前任务未提供该成果说明。"}</li>)}</ul></dd></div>
      <div><dt>承诺原时点</dt><dd>{value.promised_at ?? "日期未知"}</dd></div>
      <div><dt>原时区</dt><dd>{value.original_timezone}</dd></div>
      <div><dt>日历标识</dt><dd>{value.calendar_id ?? "未登记日历"}</dd></div>
      <div><dt>承诺登记原时点</dt><dd><time dateTime={value.recorded_at}>{value.recorded_at}</time></dd></div>
      <div><dt>记录创建原时点</dt><dd><time dateTime={value.created_at}>{value.created_at}</time></dd></div>
      <div><dt>替代原承诺</dt><dd>{value.replaces ? `${value.replaces.id} · v${value.replaces.revision}` : "未登记替代关系"}</dd></div>
      <div><dt>承诺记录标识</dt><dd>{value.id} · v{value.revision}</dd></div>
      <div><dt>承诺人标识</dt><dd>{value.promisor_id}</dd></div><div><dt>接收人标识</dt><dd>{value.recipient_id}</dd></div>
    </dl></details>
  </article>;
}

function FulfillmentReading({ value, members }: { value: FulfillmentCommitment; members: ProjectWorkView["members"] }) {
  const state = value.fulfillment, review = state.review;
  const member = (id: string) => { const matches = members.filter(item => item.id === id); return matches.length === 1 ? matches[0].name : "姓名暂不可读"; };
  const label = state.state === "fulfilled" ? "已具名核对履行" : review ? "已退回 · 履行保持开放" : "尚未具名核对";
  return <div className={styles.fulfillment}>
    <p className={styles.fulfillmentState} data-state={state.state}>{label}</p>
    {review ? <p className={styles.meta}>核对人：{member(review.actor_id)} · 核对 v{review.revision}<span>登记时点：<time dateTime={review.recorded_at}>{review.recorded_at}</time></span></p> : <p className={styles.context}>当前没有具名履行结论，不代表承诺事实未完成。</p>}
    {review && <details className={styles.reviewHistory}><summary>具名核对与历史（{state.history.length} 条）</summary>
      <p className={styles.context}>以下记录由本条承诺的履行读集返回，未提供每次核对固定的任务、提交和承诺引用；不能用当前材料回填历史。</p>
      {state.history.map(record => <ReviewRecord key={record.id} value={record} current={record.id === review.id && record.revision === review.revision} actor={member(record.actor_id)} />)}
    </details>}
  </div>;
}
function ReviewRecord({ value, current, actor }: { value: FulfillmentReview; current: boolean; actor: string }) {
  const checkLabels = { accepted: "接收", rejected: "未接收", unknown: "待核对" };
  return <section className={styles.review} aria-label={`履行核对记录 ${value.id}`}>
    <h4>核对 v{value.revision} · {value.decision === "accepted" ? "接收履行" : "退回"}{current ? " · 当前核对" : " · 历史核对"}</h4>
    <p>具名核对人：{actor}</p><p>核对登记原时点：<time dateTime={value.recorded_at}>{value.recorded_at}</time></p>
    <ul>{value.checks.map(check => <li key={check.key}><code>{check.key}</code> · {checkLabels[check.decision]}：{check.reason}</li>)}</ul>
    <details className={styles.details}><summary>核对与回执标识</summary><p>核对记录 {value.id} · v{value.revision}</p><p>具名人员 {value.actor_id}</p><p>回执 {value.receipt_id}</p></details>
  </section>;
}
