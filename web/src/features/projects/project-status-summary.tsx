import type { NamedProjectUpdate } from "@/lib/project-status-update";
import styles from "./project-status-summary.module.css";

export function ProjectStatusSummary({ update }: { update: NamedProjectUpdate | null | undefined }) {
  if (update === undefined) return <p className={styles.empty}>具名状态更新尚未读取。</p>;
  if (update === null) return <p className={styles.empty}>尚无具名状态更新。</p>;
  return <article className={styles.summary} aria-label="最新具名状态更新">
    <p className={styles.body}>{update.fact_summary}</p>
    <p className={styles.meta}><span>{update.actor.name ?? "姓名暂不可读"}</span><time dateTime={update.created_at}>{new Date(update.created_at).toLocaleString()}</time></p>
    <details><summary>下一步与固定引用</summary>
      <p className={styles.body}>{update.next_steps}</p>
      {update.task_refs.length ? <ul>{update.task_refs.map(ref => <li key={`${ref.id}:${ref.revision}`}>任务 {ref.id} · 固定 v{ref.revision}</li>)}</ul> : <p className={styles.empty}>未引用任务版本。</p>}
      <p className={styles.meta}>记录 {update.id} · 回执 {update.receipt_id}</p>
    </details>
  </article>;
}
