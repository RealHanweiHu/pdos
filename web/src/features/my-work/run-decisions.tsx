"use client";

/* 要我决定 · 小Pai 运行 (D78): one card per run with its unanswered questions and pending
   candidates. A run's T0/T1 candidates can be confirmed as one package (D77, P77): all
   are selected by default, any one can be left out, each is previewed and saved on its
   own, and the result lists every item. Named (T2) and multi-step items stay in the run. */
import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, CheckCircle, Sparkle, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { proofClockCurrent } from "@/lib/proof-clock";
import { CandidateReviewBody } from "@/features/xiaopai/candidate-review";
import {
  candidateName, confirmPackage, initialSelection, previewPackage, runTitle, statusNames,
  type PackageFailure, type PackagePreview, type PackageResult, type RunDecision, type RunDecisionsApi,
} from "@/features/my-work/lib/run-decisions";
import styles from "./run-decisions.module.css";

const reviewCodes: Record<string, string> = {
  EXTERNAL_OUTCOME_UNKNOWN: "上次外部操作的结果需要核对",
  SOURCE_UNAVAILABLE: "模型服务暂不可用，可在对话中重试",
};
const separate: Record<string, string> = { separate_entry: "需在对话中逐步办理", named_decision: "具名决定，须单独办理" };
const effect = (review: Record<string, unknown>) => typeof review.effect === "string" && review.effect.trim() ? review.effect : "核对本次保存范围。";
const candidateTitle = (item: RunDecision["candidates"][number]) => {
  const payload = item.command?.payload ?? {};
  // Platform links differ by platform and reason; show both so same-named items can be told apart.
  const platform = payload.new_platform as { code?: unknown } | undefined;
  if (platform && typeof platform.code === "string") return [platform.code, payload.reason].filter(value => typeof value === "string" && value.trim()).join(" · ");
  const title = payload.title ?? payload.name ?? payload.question ?? item.summary?.title;
  return typeof title === "string" && title.trim() ? title : null;
};

type Stage =
  | { kind: "previewing" }
  | { kind: "review"; previews: PackagePreview[]; failures: PackageFailure[] }
  | { kind: "saving"; previews: PackagePreview[] }
  | { kind: "result"; result: PackageResult | null; error: string; previews: PackagePreview[] };

function RunCard({ api, item, focusEvent, onOpenRun, onChanged }: { api: RunDecisionsApi; item: RunDecision; focusEvent: string | null | undefined; onOpenRun: (runId: string, categoryId: string) => void; onChanged: () => void }) {
  const [selected, setSelected] = useState(() => initialSelection(item, focusEvent ?? null));
  const [stage, setStage] = useState<Stage | null>(null);
  const [error, setError] = useState("");
  const card = useRef<HTMLElement>(null), dialog = useRef<HTMLDialogElement>(null), trigger = useRef<HTMLButtonElement>(null);
  const eligible = item.candidates.filter(entry => entry.package);
  const categoryId = item.category?.id ?? "";
  useEffect(() => {
    if (focusEvent === undefined || !card.current) return;
    card.current.scrollIntoView({ block: "center" });
    card.current.focus({ preventScroll: true });
  }, [focusEvent]);
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (stage && !element.open) element.showModal();
    else if (!stage && element.open) { element.close(); trigger.current?.focus(); }
  }, [stage]);
  const label = (eventId: string, operation: string) => {
    const entry = item.candidates.find(candidate => candidate.event_id === eventId);
    const title = entry ? candidateTitle(entry) : null;
    return `${candidateName({ operation } as RunDecision["candidates"][number])}${title ? ` · ${title}` : ""}`;
  };
  const toggle = (id: string) => setSelected(old => old.includes(id) ? old.filter(value => value !== id) : [...old, id]);
  async function review() {
    setError(""); setStage({ kind: "previewing" });
    try {
      const { previews, failures } = await previewPackage(api, item, selected);
      setStage({ kind: "review", previews, failures });
    } catch (failure) { setStage(null); setError((failure as Error).message); }
  }
  async function save(previews: PackagePreview[]) {
    if (previews.some(preview => !proofClockCurrent("T1", preview.expiresAt))) { setStage(null); setError("本次核对已过期，请重新核对整包。"); return; }
    setStage({ kind: "saving", previews });
    try { setStage({ kind: "result", result: await confirmPackage(api, item, previews), error: "", previews }); }
    catch (failure) { setStage({ kind: "result", result: null, error: (failure as Error).message, previews }); }
  }
  function close() {
    const done = stage?.kind === "result";
    setStage(null);
    if (done) onChanged();
  }
  const busy = stage?.kind === "previewing" || stage?.kind === "saving";
  return <article ref={card} tabIndex={-1} className={styles.card} data-focused={focusEvent !== undefined || undefined} aria-label={`小Pai 运行：${runTitle(item.goal)}`}>
    <header className={styles.heading}>
      <Sparkle size={15} aria-hidden="true"/>
      <div><h3 title={item.goal}>{runTitle(item.goal)}</h3><p>{item.category?.name ?? "个人对话"} · <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time></p></div>
      <Button size="xs" variant="ghost" onClick={() => onOpenRun(item.run_id, categoryId)}>在对话中查看<ArrowUpRight size={12}/></Button>
    </header>
    {item.questions.length > 0 && <section className={styles.block} aria-label="待答问题">
      <h4>待答问题 <span>{item.questions.length}</span></h4>
      <ol>{item.questions.map(question => <li key={question.id || question.question}><p>{question.question}</p>{question.why && <small>{question.why}</small>}</li>)}</ol>
      <Button size="xs" variant="outline" onClick={() => onOpenRun(item.run_id, categoryId)}>回答问题</Button>
    </section>}
    {item.needs_review && <p className={styles.note}>{reviewCodes[item.error_code ?? ""] ?? "运行在等待你查看"}，请在对话中处理。</p>}
    {item.candidates.length > 0 && <section className={styles.block} aria-label="待确认候选">
      <h4>待确认候选 <span>{item.candidates.length}</span></h4>
      <ul className={styles.candidates}>{item.candidates.map(entry => {
        const title = candidateTitle(entry);
        return <li key={entry.event_id} data-preselected={focusEvent === entry.event_id || undefined}>
          {entry.package
            ? <label><input type="checkbox" checked={selected.includes(entry.event_id)} disabled={busy} onChange={() => toggle(entry.event_id)}/><span><strong>{candidateName(entry)}</strong>{title && <em>{title}</em>}</span><small>{entry.write_tier === "T1" ? "一次确认" : "小Pai 起草"}</small></label>
            : <div><span><strong>{candidateName(entry)}</strong>{title && <em>{title}</em>}</span><small>{separate[entry.separate_reason ?? ""] ?? "须单独办理"}</small></div>}
        </li>;
      })}</ul>
      {item.more_candidates && <p className={styles.note}>此运行的候选较多，只列出前 200 条，其余请在对话中查看。</p>}
      {eligible.length > 0 && <div className={styles.actions}>
        <Button ref={trigger} size="sm" disabled={busy || !selected.length} onClick={() => void review()}>{stage?.kind === "previewing" ? "正在核对…" : `核对整包（${selected.length} 项）`}</Button>
        <span>{focusEvent && eligible.some(entry => entry.event_id === focusEvent) ? "已按链接预选这一版本，其他候选可自行勾选。" : selected.length < eligible.length ? `已取消 ${eligible.length - selected.length} 项，取消的候选保留在原运行中。` : "默认全选，可取消单条。"}</span>
      </div>}
    </section>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
    <dialog ref={dialog} className={styles.dialog} aria-label="核对整包确认" onCancel={event => { event.preventDefault(); if (!busy) close(); }}>
      {stage && <div className={styles.dialogBody}>
        <header><h3>{stage.kind === "result" ? "整包确认结果" : "核对整包确认"}</h3><Button size="icon-xs" variant="ghost" aria-label="关闭" disabled={busy} onClick={close}><X/></Button></header>
        <p className={styles.dialogScope}>{runTitle(item.goal)} · {item.category?.name}</p>
        {stage.kind === "previewing" && <p role="status">正在逐条生成预览…</p>}
        {stage.kind === "review" && <>
          {stage.previews.length > 0 && <ol className={styles.previewList}>{stage.previews.map((preview, index) => <li key={preview.eventId}><strong>{label(preview.eventId, preview.operation)}</strong><p>{effect(preview.review)}</p><details className={styles.review} open={stage.previews.length === 1 || undefined}><summary>核对第 {index + 1} 项的原值、新值、来源与未定项</summary><CandidateReviewBody preview={{ command: preview.command, review: preview.review, expires_at: preview.expiresAt ?? "" }}/></details></li>)}</ol>}
          {stage.failures.length > 0 && <div className={styles.failures} role="alert"><p>以下 {stage.failures.length} 项未能生成预览，不进入本次整包：</p><ul>{stage.failures.map(failure => <li key={failure.eventId}>{label(failure.eventId, failure.operation)}：{failure.message}</li>)}</ul></div>}
          <p className={styles.note}>每项仍按自身档位分别保存并各有回执；某项失败不影响其他项，结果逐条列出。预览 10 分钟内有效。</p>
          <div className={styles.actions}><Button disabled={!stage.previews.length} onClick={() => void save(stage.previews)}><CheckCircle/>确认整包（{stage.previews.length} 项）</Button><Button variant="outline" onClick={close}>返回</Button></div>
        </>}
        {stage.kind === "saving" && <p role="status">正在逐条保存 {stage.previews.length} 项…</p>}
        {stage.kind === "result" && <>
          {stage.error ? <p role="alert">{stage.error} 已保存的候选以原运行为准，请刷新后核对。</p> : stage.result && <>
            <p role="status">已保存 {stage.result.adopted} 项{stage.result.items.length > stage.result.adopted ? `，另有 ${stage.result.items.length - stage.result.adopted} 项未保存` : ""}。</p>
            <ol className={styles.previewList}>{stage.result.items.map(entry => <li key={entry.event_id} data-status={entry.status}><strong>{label(entry.event_id, entry.operation)}</strong><span>{statusNames[entry.status]}</span>{entry.error && <p>{entry.error.message}</p>}{entry.receipt?.subject_type === "proposal" && categoryId && <a href={`/categories/${categoryId}/proposals/${entry.receipt.subject_id}`}>打开立项提案</a>}</li>)}</ol>
          </>}
          <div className={styles.actions}><Button onClick={close}>完成</Button></div>
        </>}
      </div>}
    </dialog>
  </article>;
}

export function RunDecisions({ api, runs, focus, truncated = false, unavailable = 0, onOpenRun, onChanged }: { api: RunDecisionsApi; runs: RunDecision[]; focus: { runId: string; eventId: string | null } | null; truncated?: boolean; unavailable?: number; onOpenRun: (runId: string, categoryId: string) => void; onChanged: () => void }) {
  if (!runs.length) return null;
  return <div className={styles.list} aria-label="小Pai 运行的待决定事项">
    {(truncated || unavailable > 0) && <p className={styles.note} role="status">{truncated ? "只列出最近 30 个需要你决定的运行，更早的请在小Pai历史中查看。" : ""}{unavailable > 0 ? `另有 ${unavailable} 个运行的资料当前不可读，未列出。` : ""}</p>}
    {runs.map(item => <RunCard key={`${item.run_id}:${item.reading_token}:${item.candidates.map(entry => entry.sequence).join(".")}:${focus?.runId === item.run_id ? focus.eventId ?? "" : "-"}`} api={api} item={item} focusEvent={focus?.runId === item.run_id ? focus.eventId : undefined} onOpenRun={onOpenRun} onChanged={onChanged}/>)}
  </div>;
}
