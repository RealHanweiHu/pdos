"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { HandArrowDown } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { browserApi } from "@/lib/browser-api";
import type { HandoverEntry, HandoverView } from "@/lib/notifications";
import { newWorkCommand, runProjectWorkRequest, workPreviewCurrent, type WorkPayload, type WorkPrepared, type WorkScope, type WorkTask } from "@/lib/project-work";
import { ObjectComments } from "@/features/projects/discussion-thread";
import styles from "./handover-items.module.css";

const STATES: Record<string, string> = { assigned: "待本人承接", accepted: "已承接", in_progress: "进行中", submitted: "待成果验收" };
type Task = HandoverEntry["tasks"][number];

function timezone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai"; } catch { return "Asia/Shanghai"; }
}

function TaskActions({ api, entry, task, principalId, onDone }: { api: typeof browserApi; entry: HandoverEntry; task: Task; principalId: string; onDone: () => void }) {
  const scope = useMemo<WorkScope>(() => ({ categoryId: entry.project.category_id, productId: entry.project.product_id, projectId: entry.project.id, principalId }), [entry, principalId]);
  const [results, setResults] = useState<Record<string, { text: string; status: string }>>(() => Object.fromEntries(task.outcomes.map(item => [item.key, { text: "", status: "present" }])));
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [prepared, setPrepared] = useState<WorkPrepared | null>(null), active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  // T1 (一次确认): the server reviews the exact material first; only the explicit confirmation saves.
  const confirm = async () => {
    if (!prepared) return;
    if (!workPreviewCurrent(prepared)) { setPrepared(null); setError("确认已过期，请重新核对。"); return; }
    setBusy(true); setError("");
    try {
      const result = await runProjectWorkRequest(api, { stage: "execute", command: prepared.command }, scope, () => undefined, () => active.current);
      if (result) { setPrepared(null); onDone(); }
    } catch (failure) { if (active.current) setError(failure instanceof Error ? failure.message : "未保存，请重试。"); }
    finally { if (active.current) setBusy(false); }
  };
  const run = async (operation: "work.task.start" | "work.task.submit") => {
    setBusy(true); setError("");
    try {
      const sources = (task.sources ?? []) as WorkPayload["sources"];
      const base = { project_id: entry.project.id, sources, reason: operation === "work.task.start" ? "交接期本人登记实际开始" : "交接期本人提交已承接任务的成果", task: { id: task.task_id, revision: task.revision }, actual_at: new Date().toISOString(), original_timezone: timezone(), calendar_id: null };
      const payload = (operation === "work.task.start" ? base : { ...base, results: task.outcomes.map(item => ({ key: item.key, text: results[item.key]?.text.trim() || item.text, status: results[item.key]?.status ?? "present", sources })) }) as unknown as WorkPayload;
      const command = newWorkCommand(scope, entry.project.product_revision, operation, payload, task as unknown as WorkTask);
      const result = await runProjectWorkRequest(api, { stage: "inputs", command }, scope, () => undefined, () => active.current);
      if (result && result.stage === "preview") setPrepared(result.prepared);
    } catch (failure) { if (active.current) setError(failure instanceof Error ? failure.message : "未提交，请重试。"); }
    finally { if (active.current) setBusy(false); }
  };
  if (prepared) return <div className={styles.submit} role="group" aria-label="确认本次办理">
    <p className={styles.note}>服务器已核对本次{prepared.command.operation === "work.task.start" ? "登记开始" : "提交成果"}的材料；确认后保存，{new Date(prepared.expires_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })} 前有效。</p>
    <div className={styles.actions}><Button size="sm" disabled={busy} onClick={() => void confirm()}>{busy ? "保存中…" : prepared.command.operation === "work.task.start" ? "确认登记开始" : "确认提交成果"}</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => setPrepared(null)}>返回修改</Button></div>
    {error && <p role="alert" className={styles.error}>{error}</p>}
  </div>;
  if (task.state === "accepted") return <div className={styles.actions}><Button size="sm" disabled={busy} onClick={() => void run("work.task.start")}>登记实际开始</Button>{error && <p role="alert" className={styles.error}>{error}</p>}</div>;
  if (task.state !== "in_progress") return <p className={styles.note}>{task.state === "submitted" ? "成果已提交，等待接收人验收；验收后交接自动完成。" : "等待负责人改派或你承接。"}</p>;
  return <form className={styles.submit} onSubmit={event => { event.preventDefault(); void run("work.task.submit"); }}>
    {task.outcomes.map(item => <label key={item.key}><span>{item.text}{item.required ? "（必需）" : ""}</span>
      <input aria-label={`${item.text} 成果说明`} placeholder="成果说明" value={results[item.key]?.text ?? ""} onChange={event => setResults(value => ({ ...value, [item.key]: { ...value[item.key], text: event.target.value } }))}/>
      <select aria-label={`${item.text} 完整性`} value={results[item.key]?.status ?? "present"} onChange={event => setResults(value => ({ ...value, [item.key]: { ...value[item.key], status: event.target.value } }))}><option value="present">已具备</option><option value="partial">部分</option><option value="missing">缺失</option></select>
    </label>)}
    <p className={styles.note}>成果依据沿用任务已固定的来源；需要补充资料请在下方评论中说明。</p>
    <div className={styles.actions}><Button size="sm" type="submit" disabled={busy}>{busy ? "提交中…" : "提交成果"}</Button></div>
    {error && <p role="alert" className={styles.error}>{error}</p>}
  </form>;
}

/** P56: after removal, only the person's own unhanded items stay visible and actionable here. */
export function HandoverItems({ api, principalId }: { api: typeof browserApi; principalId: string }) {
  const [view, setView] = useState<HandoverView | null>(null), [error, setError] = useState(""), [open, setOpen] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { setView(await api<HandoverView>("v1/personal/handover")); setError(""); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "交接事项暂不可读。"); }
  }, [api]);
  useEffect(() => { void Promise.resolve().then(load); }, [load]);
  if (error) return <p role="alert" className={styles.error}>{error}</p>;
  if (!view || view.items.length === 0) return null;
  return <section className={styles.card} aria-label="交接中的事项">
    <header><HandArrowDown size={16} aria-hidden="true"/><h2>交接中的事项</h2></header>
    <p className={styles.note}>{view.scope_note}</p>
    {view.items.map(entry => <div key={entry.project.id} className={styles.project}>
      <h3>{entry.project.name}</h3>
      <p className={styles.note}>你已于 {entry.project.left_at ? new Date(entry.project.left_at).toLocaleDateString("zh-CN") : "近期"} 移出本项目；交接完成后此项目对你不再可见。负责人：{entry.project.owner_name}。</p>
      <ul className={styles.items}>{entry.items.map(item => <li key={`${item.kind}:${item.subject_id}`}>
        <button type="button" aria-expanded={open === item.subject_id} disabled={!item.task_id} onClick={() => setOpen(value => value === item.subject_id ? null : item.subject_id)}>
          <span className={styles.kind}>{item.kind_label}</span><span className={styles.label}>{item.label}</span><span className={styles.state}>{STATES[item.state] ?? item.state}</span>
        </button>
        {open === item.subject_id && item.task_id && (() => {
          const task = entry.tasks.find(row => row.task_id === item.task_id);
          return task ? <div className={styles.detail}>
            <p>{task.goal}</p>
            {item.kind === "work_task" ? <TaskActions api={api} entry={entry} task={task} principalId={principalId} onDone={() => void load()}/> : <p className={styles.note}>这是你作出的承诺；任务验收或负责人取消后交接完成。</p>}
            <ObjectComments api={api} scope={{ categoryId: entry.project.category_id, productId: entry.project.product_id, projectId: entry.project.id }} subjectType="work_task" subjectId={task.task_id}/>
          </div> : null;
        })()}
      </li>)}</ul>
    </div>)}
  </section>;
}
