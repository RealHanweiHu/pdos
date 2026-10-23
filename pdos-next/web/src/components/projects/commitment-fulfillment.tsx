"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowClockwise, CheckCircle, ClipboardText } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { blankFulfillmentLocal, canReviewFulfillment, fulfillmentDraft, fulfillmentDraftCurrent, fulfillmentPreviewCurrent, fulfillmentStorageKey, newFulfillmentCommand, readFulfillment, restoreFulfillmentLocal, runFulfillmentRequest, type FulfillmentCommitment, type FulfillmentLocal, type FulfillmentPayload, type FulfillmentPending, type FulfillmentPrepared, type FulfillmentView } from "@/lib/commitment-fulfillment";
import type { ProjectWorkApi, WorkCheck, WorkScope, WorkSource } from "@/lib/project-work";
import styles from "./commitment-fulfillment.module.css";

type Props = { api: ProjectWorkApi; scope: WorkScope; onRefresh: () => void; readVersion?: number };
const json = (v: unknown) => JSON.stringify(v, null, 2);
const taskStates = { proposed: "待分派", assigned: "待承接", accepted: "已承接", in_progress: "进行中", submitted: "待任务验收", completed: "任务已验收" };
const resultStates = { present: "已提供", partial: "部分提供", missing: "尚缺" };
const checkStates = { accepted: "接收", rejected: "不满足", unknown: "待核实" };
function Sources({ values }: { values: WorkSource[] }) { return <details className={styles.sources}><summary>实际来源 · {values.length} 条</summary>{values.map((value, index) => <p key={`${value.id}:${value.revision}:${index}`}>{value.id} · v{value.revision}<br/>{value.position}</p>)}</details>; }

export function CommitmentFulfillment(props: Props) { const s = props.scope; return <ScopedCommitmentFulfillment key={json([s.principalId, s.categoryId, s.productId, s.projectId])} {...props}/>; }

function ScopedCommitmentFulfillment({ api, scope, onRefresh, readVersion = 0 }: Props) {
  const { categoryId, productId, projectId, principalId } = scope, storageKey = fulfillmentStorageKey(scope);
  const [local, setLocal] = useState<FulfillmentLocal>(() => blankFulfillmentLocal(scope));
  const localRef = useRef(local), epoch = useRef(0), alive = useRef(false), lock = useRef(false);
  const [hydrated, setHydrated] = useState(false), [storageOk, setStorageOk] = useState(false), [busy, setBusy] = useState(false), [denied, setDenied] = useState(false);
  const [attempt, setAttempt] = useState(0), [notice, setNotice] = useState(""), [error, setError] = useState(""), [prepared, setPrepared] = useState<FulfillmentPrepared | null>(null);
  const [reading, setReading] = useState<{ api: ProjectWorkApi; attempt: number; version: number; data: FulfillmentView | null; error: string } | null>(null);
  const data = reading?.api === api && reading.attempt === attempt && reading.version === readVersion && !denied ? reading.data : null;
  const readError = reading?.api === api && reading.attempt === attempt && reading.version === readVersion ? reading.error : "";
  const draft = local.draft, selected = data?.commitments.find(row => row.id === draft?.commitment.id);
  const current = !!draft && !!selected && fulfillmentDraftCurrent(draft, selected, scope);
  const editable = hydrated && storageOk && !!data && !denied && !busy && !local.pending && !prepared;

  function persist(value: FulfillmentLocal) { localStorage.setItem(storageKey, json(value)); localRef.current = value; setLocal(value); setStorageOk(true); }
  function saveEvent(value: FulfillmentLocal) { try { persist(value); return true; } catch { setStorageOk(false); setNotice("本机保存失败，已停止提交。请恢复存储后重试，原请求不可丢弃。"); return false; } }
  function change(value: Partial<FulfillmentPayload>) { if (localRef.current.draft) saveEvent({ ...localRef.current, draft: { ...localRef.current.draft, ...value }, receipt: null, completed: null }); }
  function updateCheck(key: string, value: Partial<WorkCheck>) { if (localRef.current.draft) change({ checks: localRef.current.draft.checks.map(row => row.key === key ? { ...row, ...value } : row) }); }
  const clearPrivate = useCallback((message: string) => {
    epoch.current++; lock.current = false; setBusy(false);
    let removed = true; try { localStorage.removeItem(storageKey); } catch { removed = false; }
    const empty = blankFulfillmentLocal({ categoryId, productId, projectId, principalId }); localRef.current = empty; setLocal(empty); setPrepared(null); setReading(null); setDenied(true); setError(message);
    setNotice(removed ? "访问已失效，已清除本机私有履行材料。" : "访问已失效，已隐藏私有材料；本机存储无法清除，请勿继续使用旧材料。");
  }, [storageKey, categoryId, productId, projectId, principalId]);
  useEffect(() => {
    const generation = ++epoch.current; alive.current = true; lock.current = false;
    void Promise.resolve().then(() => { if (!alive.current || epoch.current !== generation) return; try { const raw = localStorage.getItem(storageKey), saved = raw ? restoreFulfillmentLocal(JSON.parse(raw), { categoryId, productId, projectId, principalId }) : null; const value = saved ?? blankFulfillmentLocal({ categoryId, productId, projectId, principalId }); localRef.current = value; setLocal(value); setStorageOk(true); setHydrated(true); setBusy(false); setPrepared(null); if (saved?.pending) setNotice("已恢复原履行核对请求。刷新不会自动提交，请明确核对或按原请求重放。"); } catch { setStorageOk(false); setHydrated(true); setNotice("本机履行草稿暂不可读取，已停止业务写入。"); } });
    return () => { alive.current = false; epoch.current = generation + 1; lock.current = false; };
  }, [api, storageKey, categoryId, productId, projectId, principalId]);
  useEffect(() => { let active = true; void readFulfillment(api, { categoryId, productId, projectId, principalId }).then(value => { if (active) { setReading({ api, attempt, version: readVersion, data: value, error: "" }); setDenied(false); } }).catch(failure => { if (active) { setReading({ api, attempt, version: readVersion, data: null, error: (failure as Error).message }); if ([401, 403].includes((failure as Error & { status?: number }).status ?? 0)) clearPrivate((failure as Error).message); } }); return () => { active = false; }; }, [api, categoryId, productId, projectId, principalId, attempt, readVersion, clearPrivate]);

  async function run(pending: FulfillmentPending) {
    if (lock.current || !alive.current || !storageOk || denied) return;
    lock.current = true; setBusy(true); setError(""); const generation = epoch.current, active = () => alive.current && epoch.current === generation;
    try {
      const result = await runFulfillmentRequest(api, pending, scope, step => { if (active()) persist({ ...localRef.current, pending: step, receipt: null, completed: null }); }, active);
      if (!active() || !result) return;
      if (result.stage === "preview") { setPrepared(result.prepared); setNotice("材料已核对，尚未保存履行决定。请核对并明确确认。"); }
      else { persist({ ...localRef.current, draft: null, pending: null, receipt: result.receipt, completed: result.command }); setPrepared(null); setNotice("已取得履行核对回执，正在只读回当前记录。"); setAttempt(value => value + 1); onRefresh(); }
    } catch (failure) { if (active()) { const err = failure as Error & { status?: number }; if ([401, 403].includes(err.status ?? 0)) clearPrivate(err.message); else { setError(err.message); setNotice(localRef.current.pending?.stage === "execute" ? "保存结果尚待核实。请保留原请求并明确核对，勿新建重复决定。" : "本次办理未完成，已保留原请求供核对。"); } } }
    finally { if (active()) { lock.current = false; setBusy(false); } }
  }
  function choose(row: FulfillmentCommitment) { if (!editable) return; try { const next = { ...localRef.current, draft: fulfillmentDraft(row, scope), receipt: null, completed: null }; if (saveEvent(next)) { setError(""); setNotice(""); } } catch (failure) { setError((failure as Error).message); } }
  function start() { if (!editable || !current || !draft || !selected || !data) return; try { const command = newFulfillmentCommand(scope, data.product_revision, draft, selected), pending: FulfillmentPending = { stage: "inputs", command }; if (saveEvent({ ...localRef.current, pending, receipt: null, completed: null })) void run(pending); } catch (failure) { setError((failure as Error).message); } }
  function confirm() { if (!prepared || busy) return; if (!fulfillmentPreviewCurrent(prepared)) { setError("本次确认已过期，请重新核对原请求。"); return; } const pending: FulfillmentPending = { stage: "execute", command: prepared.command }; if (saveEvent({ ...localRef.current, pending, receipt: null, completed: null })) void run(pending); }
  const allPresent = !!selected && selected.outcome_keys.every(key => selected.submission?.results.find(row => row.key === key)?.status === "present");
  return <section className={`${styles.root} project-canvas`} aria-label="承诺履行核对">
    <header className={styles.heading}><div><p className={styles.eyebrow}>个人承诺 · 接收者逐条核对</p><h2>承诺履行</h2></div><Button variant="outline" size="sm" disabled={busy} onClick={() => setAttempt(value => value + 1)}><ArrowClockwise aria-hidden="true"/>刷新履行记录</Button></header>
    <p className={styles.note}>任务验收与承诺履行分开。每位承诺接收者核对自己的成果范围；任务已验收或日期已过都不代表承诺已履行。</p>
    {notice && <p className={styles.notice} role="status">{notice}</p>}{error && <p className={styles.error} role="alert">{error}</p>}
    {!data && !readError && !denied && <p role="status">正在读取承诺履行记录…</p>}
    {readError && <p className={styles.error} role="alert">承诺履行读取失败：{readError}。请刷新重试。</p>}
    {data && <><p className={styles.note}>{data.project.name} · 读取于 {data.as_of}</p>{data.commitments.length === 0 ? <p className={styles.note}>尚无可读承诺记录。</p> : <div className={styles.cards}>{data.commitments.map(row => <article className={styles.card} key={row.id}>
      <header className={styles.heading}><h3>{row.task.title}</h3><span className={styles.badge}>{row.fulfillment.state === "fulfilled" ? "已核对履行" : "待履行"} · {row.status === "current" ? "当前承诺" : "已被续版"}</span></header>
      <dl className={styles.facts}><dt>承诺人</dt><dd>{row.promisor_id}</dd><dt>本条承诺接收人</dt><dd>{row.recipient_id}{row.recipient_id === principalId ? "（本人）" : ""}</dd><dt>承诺版本</dt><dd>{row.id} · v{row.revision}</dd><dt>承诺时间</dt><dd>{row.promised_at ?? "未知 / 未登记"} · {row.original_timezone}</dd><dt>任务当前状态</dt><dd>{taskStates[row.task.state]} · v{row.task.revision}</dd></dl>
      <p className={styles.note}>承诺成果：{row.outcome_keys.join("、")}。可选成果一旦纳入本条承诺，也须核对。</p>
      {row.submission ? <><p className={styles.note}>原成果提交 {row.submission.id} · v{row.submission.revision}<br/>提交人 {row.submission.actor_id} · 实际 {row.submission.time.actual_at}（{row.submission.time.original_timezone}）· 登记 {row.submission.time.recorded_at}</p>{row.submission.results.map(result => <div className={styles.result} key={result.key}><strong>{result.key} · {resultStates[result.status]}{row.outcome_keys.includes(result.key) ? " · 本条承诺内" : " · 承诺范围外"}</strong><p>{result.text}</p><Sources values={result.sources}/></div>)}</> : <p className={styles.note}>尚无实际成果提交，不能核对履行。</p>}
      <Sources values={row.sources}/>
      {row.fulfillment.history.length > 0 && <details className={styles.history}><summary>履行核对历史 · {row.fulfillment.history.length} 条</summary>{row.fulfillment.history.map(value => <div key={value.id}><p>{value.decision === "accepted" ? "接收履行" : "退回，保持待履行"} · v{value.revision} · {value.recorded_at}</p><p>核对人 {value.actor_id} · 回执 {value.receipt_id}</p><ul>{value.checks.map(check => <li key={check.key}>{check.key}：{checkStates[check.decision]} · {check.reason}</li>)}</ul></div>)}</details>}
      {canReviewFulfillment(row, scope) ? <Button size="sm" variant="outline" disabled={!editable} onClick={() => choose(row)}><ClipboardText aria-hidden="true"/>核对本条承诺</Button> : <p className={styles.note}>{row.fulfillment.state === "fulfilled" ? "本条承诺已有具名履行记录。" : "仅当前承诺的接收者可在实际成果提交后核对，服务端判定当前办理条件。"}</p>}
    </article>)}</div>}
    {draft && !local.receipt && !denied && <section className={styles.panel} aria-label="本次履行核对表"><h3>核对本条承诺的全部成果</h3><p className={styles.note}>固定承诺 {draft.commitment.id} v{draft.commitment.revision} · 任务 v{draft.task.revision} · 原提交 {draft.submission.id} v{draft.submission.revision}</p>{!current && <p className={styles.error}>固定材料或办理条件已变化，请从当前承诺重新选择。旧核对不会套用新提交。</p>}<fieldset className={styles.form} disabled={!editable || !current}>
      <label>履行决定<select value={draft.decision} onChange={event => change({ decision: event.target.value as FulfillmentPayload["decision"] })}><option value="returned">退回补齐，保持待履行</option><option value="accepted" disabled={!allPresent}>接收本条承诺履行</option></select></label>{!allPresent && <p className={styles.note}>尚有承诺成果未完整提供，不能接收履行。</p>}
      {draft.checks.map(check => { const result = selected?.submission?.results.find(row => row.key === check.key); return <div className={styles.result} key={check.key}><h4>{check.key} · {result ? resultStates[result.status] : "原提交未提供"}</h4><p>{result?.text ?? "缺少本项实际成果。"}</p><label>成果 {check.key} 核对<select value={check.decision} onChange={event => updateCheck(check.key, { decision: event.target.value as WorkCheck["decision"] })}><option value="unknown">待核实</option><option value="accepted">满足并接收</option><option value="rejected">不满足</option></select></label><label>成果 {check.key} 核对依据<textarea value={check.reason} onChange={event => updateCheck(check.key, { reason: event.target.value })}/></label></div>; })}
      <label>办理理由<textarea value={draft.reason} onChange={event => change({ reason: event.target.value })}/></label><Sources values={draft.sources}/><p className={styles.note}>履行核对时间由服务器登记，无需补造实际完成日期。接收须每项成果实际已提供且全部核对接收；退回须保留至少一项未接收。</p><Button type="button" onClick={start}>核对此次履行材料</Button>
    </fieldset></section>}
    </>}
    {local.pending && !denied && <section className={styles.pending} aria-label="履行原请求"><h3>{local.pending.stage === "execute" ? "履行保存结果待核实" : "本次履行材料尚待确认"}</h3><p>已保留同一原请求、版本和请求编号。重新打开页面不会自动提交。</p><Button disabled={busy || !storageOk} onClick={() => void run(local.pending!)}>{local.pending.stage === "execute" ? "按原请求核对履行保存结果" : "重新核对原履行请求"}</Button>{local.pending.stage !== "execute" && !prepared && <Button variant="outline" disabled={busy || !storageOk} onClick={() => saveEvent({ ...localRef.current, pending: null })}>返回编辑</Button>}</section>}
    {prepared && !denied && <section className={styles.preview} role="dialog" aria-modal="false" aria-label="确认承诺履行核对"><h3>确认本条承诺履行核对</h3><p>本人 {principalId} · {prepared.command.payload.decision === "accepted" ? "接收本条承诺履行" : "退回，保持待履行"}</p><p>仅处理载明的承诺与原提交，不替其他接收者作决定。</p><details open><summary>固定载荷与服务器核对</summary><pre>{json({ payload: { ...prepared.command.payload, confirmation_token: undefined }, review: prepared.review })}</pre></details><p className={styles.note}>确认截止 {prepared.expires_at}</p><div className={styles.actions}><Button disabled={busy || !storageOk} onClick={confirm}><CheckCircle aria-hidden="true"/>确认保存履行核对</Button><Button variant="outline" disabled={busy || !storageOk} onClick={() => { if (saveEvent({ ...localRef.current, pending: null })) setPrepared(null); }}>返回编辑</Button></div></section>}
    {local.receipt && !denied && <p className={styles.success}>已保存具名履行核对 · 回执 {local.receipt.id}。刷新只读回记录。</p>}
  </section>;
}
