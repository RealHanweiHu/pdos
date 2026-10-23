"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowClockwise, CheckCircle, ClipboardText } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { blankRiskLocal, canRecordRisk, newRiskCommand, readProjectRisks, restoreRiskLocal, riskDraft, riskDraftCurrent, riskPreviewCurrent, riskStorageKey, runRiskRequest, type ProjectRisk, type ProjectRiskView, type RiskDraft, type RiskLocal, type RiskPending, type RiskPrepared } from "@/lib/project-risks";
import { workRecord, type ProjectWorkApi, type WorkScope } from "@/lib/project-work";
import styles from "./project-risks.module.css";

type Props = { api: ProjectWorkApi; scope: WorkScope; onRefresh: () => void; readVersion?: number };
const json = (v: unknown) => JSON.stringify(v, null, 2);
const taskStates = { proposed: "待分派", assigned: "待承接", accepted: "已承接", in_progress: "进行中", submitted: "待成果验收", completed: "任务已验收" };
const states = { open: "内部跟进中", closed: "内部跟进已关闭", unknown: "跟进状态未知" };

export function ProjectRisks(props: Props) { const s = props.scope; return <ScopedProjectRisks key={json([s.principalId, s.categoryId, s.productId, s.projectId])} {...props}/>; }

function ScopedProjectRisks({ api, scope, onRefresh, readVersion = 0 }: Props) {
  const { categoryId, productId, projectId, principalId } = scope, storageKey = riskStorageKey(scope);
  const [local, setLocal] = useState<RiskLocal>(() => blankRiskLocal(scope));
  const localRef = useRef(local), epoch = useRef(0), alive = useRef(false), lock = useRef(false);
  const [hydrated, setHydrated] = useState(false), [storageOk, setStorageOk] = useState(false), [busy, setBusy] = useState(false), [denied, setDenied] = useState(false);
  const [attempt, setAttempt] = useState(0), [notice, setNotice] = useState(""), [error, setError] = useState(""), [prepared, setPrepared] = useState<RiskPrepared | null>(null);
  const [reading, setReading] = useState<{ api: ProjectWorkApi; attempt: number; version: number; data: ProjectRiskView | null; error: string } | null>(null);
  const data = reading?.api === api && reading.attempt === attempt && reading.version === readVersion && !denied ? reading.data : null;
  const readError = reading?.api === api && reading.attempt === attempt && reading.version === readVersion ? reading.error : "";
  const draft = local.draft, selected = data?.risks.find(row => row.id === draft?.risk.id);
  const current = !!draft && !!selected && riskDraftCurrent(draft, selected, scope);
  const preparedRow = data?.risks.find(row => row.id === prepared?.command.payload.risk.id);
  const preparedCurrent = !!prepared && !!preparedRow && !!data && prepared.command.expected_revision === data.product_revision && riskDraftCurrent(prepared.command.payload, preparedRow, scope);
  const before = prepared && workRecord(prepared.review.before) ? prepared.review.before : null, after = prepared && workRecord(prepared.review.after) ? prepared.review.after : null;
  const editable = hydrated && storageOk && !!data && !denied && !busy && !local.pending && !prepared;
  const name = (id: string) => data?.members.find(row => row.id === id)?.name ?? id;

  function persist(value: RiskLocal) { localStorage.setItem(storageKey, json(value)); localRef.current = value; setLocal(value); setStorageOk(true); }
  function saveEvent(value: RiskLocal) { try { persist(value); return true; } catch { setStorageOk(false); setNotice("本机保存失败，已停止提交。请恢复存储后重试，原请求不可丢弃。"); return false; } }
  function change(value: Partial<RiskDraft>) { if (localRef.current.draft) saveEvent({ ...localRef.current, draft: { ...localRef.current.draft, ...value }, receipt: null, completed: null }); }
  const clearPrivate = useCallback((message: string) => {
    epoch.current++; lock.current = false; setBusy(false);
    let removed = true; try { localStorage.removeItem(storageKey); } catch { removed = false; }
    const empty = blankRiskLocal({ categoryId, productId, projectId, principalId }); localRef.current = empty; setLocal(empty); setPrepared(null); setReading(null); setDenied(true); setError(message);
    setNotice(removed ? "访问已失效，已清除本机私有风险跟进材料。" : "访问已失效，已隐藏私有材料；本机存储无法清除，请勿继续使用旧材料。");
  }, [storageKey, categoryId, productId, projectId, principalId]);
  useEffect(() => {
    const generation = ++epoch.current; alive.current = true; lock.current = false;
    void Promise.resolve().then(() => { if (!alive.current || epoch.current !== generation) return; try { const raw = localStorage.getItem(storageKey), saved = raw ? restoreRiskLocal(JSON.parse(raw), { categoryId, productId, projectId, principalId }) : null; const value = saved ?? blankRiskLocal({ categoryId, productId, projectId, principalId }); localRef.current = value; setLocal(value); setStorageOk(true); setHydrated(true); setBusy(false); setPrepared(null); if (saved?.pending) setNotice("已恢复原风险跟进请求。刷新不会自动提交，请明确核对或按原请求重放。"); } catch { setStorageOk(false); setHydrated(true); setNotice("本机风险跟进草稿暂不可读取，已停止业务写入。"); } });
    return () => { alive.current = false; epoch.current = generation + 1; lock.current = false; };
  }, [api, storageKey, categoryId, productId, projectId, principalId]);
  useEffect(() => { let active = true; void readProjectRisks(api, { categoryId, productId, projectId, principalId }).then(value => { if (active) { setReading({ api, attempt, version: readVersion, data: value, error: "" }); setDenied(false); } }).catch(failure => { if (active) { setReading({ api, attempt, version: readVersion, data: null, error: (failure as Error).message }); if ([401, 403].includes((failure as Error & { status?: number }).status ?? 0)) clearPrivate((failure as Error).message); } }); return () => { active = false; }; }, [api, categoryId, productId, projectId, principalId, attempt, readVersion, clearPrivate]);

  async function run(pending: RiskPending) {
    if (lock.current || !alive.current || !storageOk || denied) return;
    lock.current = true; setBusy(true); setError(""); const generation = epoch.current, active = () => alive.current && epoch.current === generation;
    try {
      const result = await runRiskRequest(api, pending, scope, step => { if (active()) persist({ ...localRef.current, pending: step, receipt: null, completed: null }); }, active);
      if (!active() || !result) return;
      if (result.stage === "preview") { setPrepared(result.prepared); setNotice("材料已核对，尚未保存风险跟进结果。请核对并明确确认。"); }
      else { persist({ ...localRef.current, draft: null, pending: null, receipt: result.receipt, completed: result.command }); setPrepared(null); setNotice("已取得风险跟进回执，正在只读回当前记录。"); setAttempt(value => value + 1); onRefresh(); }
    } catch (failure) { if (active()) { const err = failure as Error & { status?: number }; if ([401, 403].includes(err.status ?? 0)) clearPrivate(err.message); else { setError(err.message); setNotice(localRef.current.pending?.stage === "execute" ? "保存结果尚待核实。请保留原请求并明确核对，勿新建重复记录。" : "本次办理未完成，已保留原请求供核对。"); } } }
    finally { if (active()) { lock.current = false; setBusy(false); } }
  }
  function choose(row: ProjectRisk) { if (!editable) return; try { const next = { ...localRef.current, draft: riskDraft(row, scope), receipt: null, completed: null }; if (saveEvent(next)) { setError(""); setNotice(""); } } catch (failure) { setError((failure as Error).message); } }
  function start() { if (!editable || !current || !draft || !selected || !data) return; try { const command = newRiskCommand(scope, data.product_revision, draft, selected), pending: RiskPending = { stage: "inputs", command }; if (saveEvent({ ...localRef.current, pending, receipt: null, completed: null })) void run(pending); } catch (failure) { setError((failure as Error).message); } }
  function confirm() { if (!prepared || busy || !preparedCurrent) return; if (!riskPreviewCurrent(prepared)) { setError("本次确认已过期，请重新核对原请求。"); return; } const pending: RiskPending = { stage: "execute", command: prepared.command }; if (saveEvent({ ...localRef.current, pending, receipt: null, completed: null })) { setPrepared(null); void run(pending); } }
  return <section className={`${styles.root} project-canvas`} aria-label="风险独立跟进">
    <header className={styles.heading}><div><p className={styles.eyebrow}>G0 风险 · 原具名跟进人登记</p><h2>风险跟进</h2></div><Button variant="outline" size="sm" disabled={busy} onClick={() => setAttempt(value => value + 1)}><ArrowClockwise aria-hidden="true"/>刷新风险跟进</Button></header>
    <p className={styles.note}>内部跟进关闭与重开由原具名跟进人登记，不代表专业风险接受或放行。关联任务的成果验收不会自动关闭风险；原跟进期限也不是个人承诺。</p>
    {notice && <p className={styles.notice} role="status">{notice}</p>}{error && <p className={styles.error} role="alert">{error}</p>}
    {!data && !readError && !denied && <p role="status">正在读取风险跟进记录…</p>}
    {readError && <p className={styles.error} role="alert">风险跟进读取失败：{readError}。请刷新重试。</p>}
    {data && <><p className={styles.note}>{data.project.name} · 读取于 {data.as_of}</p>{data.risks.length === 0 ? <p className={styles.note}>尚无可读 G0 风险。</p> : <div className={styles.cards}>{data.risks.map(row => <article className={styles.card} key={row.id}>
      <header className={styles.heading}><h3>{row.title}</h3><span className={styles.badge}>{states[row.state]}</span></header>
      {row.note && <p>{row.note}</p>}
      <dl className={styles.facts}><dt>原具名跟进人</dt><dd>{name(row.responsible_id)}{row.responsible_id === principalId ? "（本人）" : ""}</dd><dt>原跟进期限</dt><dd>{row.due_date}</dd><dt>G0 固定事项</dt><dd>{row.id} · 决议 {row.decision_id}</dd><dt>原事项来源</dt><dd>{row.source.kind === "question" ? "问题" : "规格"} · {row.source.id}</dd><dt>当前跟进记录</dt><dd>{row.state === "unknown" ? "未知，请先恢复资料" : row.current ? `${row.current.id} · v${row.current.revision}` : "尚未登记跟进结果"}</dd><dt>关联任务</dt><dd>{row.task ? `${taskStates[row.task.state]} · v${row.task.revision} · ${row.task.id}` : "未关联任务"}</dd></dl>
      {row.summary && <p>最近跟进结果：{row.summary}</p>}
      {row.blocked && <p className={styles.error} role="status">{row.blocked.message}（{row.blocked.code}）</p>}
      {row.history.length > 0 && <details className={styles.history}><summary>风险跟进历史 · {row.history.length} 条</summary>{row.history.map(value => <div key={value.id}><p>{value.action === "close" ? "关闭内部跟进" : "重开内部跟进"} · v{value.revision} · {value.created_at}</p><p>{value.summary}</p><p>登记人 {name(value.actor_id)} · 回执 {value.receipt_id}</p></div>)}</details>}
      {canRecordRisk(row, scope) ? <Button size="sm" variant="outline" disabled={!editable} onClick={() => choose(row)}><ClipboardText aria-hidden="true"/>{row.state === "closed" ? "重开本条风险跟进" : "登记本条风险跟进结果"}</Button> : <p className={styles.note}>{row.state === "unknown" ? "状态未知时不能据此办理关闭或重开。" : "由原 G0 具名跟进人办理；服务端核对当前资料和权限。"}</p>}
    </article>)}</div>}
    {draft && !local.receipt && !denied && <section className={styles.panel} aria-label="本次风险跟进表"><h3>{draft.action === "close" ? "关闭本条内部跟进" : "重开本条内部跟进"}</h3><p className={styles.note}>固定 G0 风险 {draft.risk.id} · 决议 {draft.risk.decision_id} · 原跟进版本 {draft.current ? `${draft.current.id} v${draft.current.revision}` : "尚无登记"}</p>{!current && <p className={styles.error}>风险状态、固定材料或办理条件已变化，请从当前风险重新选择。旧结果不会套用新版本。</p>}<fieldset className={styles.form} disabled={!editable || !current}>
      <label>{draft.action === "close" ? "关闭跟进结果与依据" : "重开跟进原因与下一步"}<textarea value={draft.summary} onChange={event => change({ summary: event.target.value })}/></label>
      <label>办理理由<textarea value={draft.reason} onChange={event => change({ reason: event.target.value })}/></label>
      <details className={styles.sources}><summary>高级：原件来源引用</summary><p>填写已登记 artifact 的准确版本和原文位置。G0 事项本身不会替代结果依据。</p><label>结果依据来源 JSON<textarea value={draft.sources} onChange={event => change({ sources: event.target.value })} spellCheck={false}/></label><p className={styles.note}>格式：[{`{"kind":"artifact","id":"原件 UUID","revision":1,"position":"准确原文位置"}`}]</p></details>
      <p className={styles.note}>只登记本条内部跟进状态；不形成专业批准、风险接受或产品放行。</p><Button type="button" onClick={start}>核对此次风险跟进材料</Button>
    </fieldset></section>}
    </>}
    {local.pending && !denied && <section className={styles.pending} aria-label="风险跟进原请求"><h3>{local.pending.stage === "execute" ? "风险跟进保存结果待核实" : "本次风险跟进尚待确认"}</h3><p>已保留同一原风险、版本、内容与请求编号。重新打开页面不会自动提交。</p><Button disabled={busy || !storageOk} onClick={() => void run(local.pending!)}>{local.pending.stage === "execute" ? "按原请求核对风险跟进保存结果" : "重新核对原风险跟进请求"}</Button>{local.pending.stage !== "execute" && !prepared && <Button variant="outline" disabled={busy || !storageOk} onClick={() => saveEvent({ ...localRef.current, pending: null })}>返回编辑</Button>}</section>}
    {prepared && !denied && <section className={styles.preview} role="dialog" aria-modal="false" aria-label="确认风险跟进登记"><h3>确认本条风险跟进登记</h3><p>本人 {name(principalId)} · {prepared.command.payload.action === "close" ? "关闭内部跟进" : "重开内部跟进"}</p><p>本次记录不代表专业风险接受或放行。</p><dl className={styles.facts}><dt>登记前</dt><dd>{before?.state === "closed" ? "内部跟进已关闭" : before?.state === "open" || prepared.review.before === null ? "内部跟进中" : "见服务器核对"}{typeof before?.summary === "string" ? ` · ${before.summary}` : " · 尚无结果登记"}</dd><dt>登记后</dt><dd>{after?.state === "closed" ? "内部跟进已关闭" : after?.state === "open" ? "内部跟进中" : "见服务器核对"}{typeof after?.summary === "string" ? ` · ${after.summary}` : ""}</dd></dl>{!preparedCurrent && <p className={styles.error}>当前资料尚未核实或版本已变化。不能确认旧内容，请刷新核对并重新选择。</p>}<details open><summary>固定载荷与服务器核对</summary><pre>{json({ payload: { ...prepared.command.payload, confirmation_token: undefined }, review: prepared.review })}</pre></details><p className={styles.note}>确认截止 {prepared.expires_at}</p><div className={styles.actions}><Button disabled={busy || !storageOk || !preparedCurrent} onClick={confirm}><CheckCircle aria-hidden="true"/>确认保存风险跟进</Button><Button variant="outline" disabled={busy || !storageOk} onClick={() => { if (saveEvent({ ...localRef.current, pending: null })) setPrepared(null); }}>返回编辑</Button></div></section>}
    {local.receipt && !denied && <p className={styles.success}>已保存具名风险跟进 · 回执 {local.receipt.id}。刷新只读回记录。</p>}
  </section>;
}
