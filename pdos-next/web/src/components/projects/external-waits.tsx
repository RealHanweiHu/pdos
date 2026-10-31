"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowClockwise, Plus, Warning, X } from "@phosphor-icons/react";
import { WorkSourcePicker } from "./work-source-picker";
import { Button } from "@/components/ui/button";
import { availableExternalWaitActions, blankExternalWaitLocal, externalWaitStorageKey, isExternalCalendarRef, newExternalWaitCommand, parseExternalWaitPayload, readExternalWaits, restoreExternalWaitLocal, runExternalWaitRequest, type ExternalWaitAction, type ExternalWaitEvent, type ExternalWaitLocal, type ExternalWaitPayload, type ExternalWaitPending, type ExternalWaitRecord, type ExternalWaitSnapshot, type ExternalWaitView } from "@/lib/external-waits";
import { parseWorkSources, workSame, type ProjectWorkApi, type WorkRef, type WorkScope, type WorkSource } from "@/lib/project-work";
import styles from "./external-waits.module.css";

type Props = { api: ProjectWorkApi; scope: WorkScope; readVersion?: number; onRefresh?: () => void | Promise<void> };
export const externalWaitActionNames: Record<ExternalWaitAction, string> = { create: "新建外部等待", details: "维护检查与关闭条件", initiate: "登记已发起材料", delivery: "登记送达核对", commitment: "登记对方声明承诺", reply: "登记对方回复", close: "关闭内部等待", reopen: "重新打开内部等待", transfer_request: "请求责任接收", transfer_accept: "本人接受跟进责任", transfer_cancel: "撤销责任接收请求" };
const deliveryNames = { effective: "本人核对为有效送达", unverified: "送达尚待核对", conflict: "送达材料存在冲突" };
const replyNames = { partial: "部分回复", received: "已收到回复声明", conflict: "回复材料存在冲突", unknown: "回复内容或结果未知" };
const clockNames: Record<ExternalWaitSnapshot["clock"]["status"], string> = { closed: "内部等待已关闭，计时已停", delivery_unknown: "有效送达尚未确定，响应计时未知", delivery_conflict: "送达存在冲突，响应计时未知", calendar_unknown: "尚未采用实际工作日历，工作响应时长未知", calendar_unavailable: "已采用日历当前不可用，工作响应时长未知", running: "按已登记有效送达与所采用日历计时" };
const pretty = (value: unknown) => JSON.stringify(value, null, 2);
const zone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const unknownTime = (value: string | null | undefined) => value ?? "未知，未登记时间";
function blankDraft(wait?: ExternalWaitSnapshot): Record<string, string> { return { title: wait?.title ?? "", target: wait?.target ?? "", request: wait?.request_content ?? "", closure: wait?.closure_condition ?? "", blocking: String(wait?.blocking ?? false), nextCheck: wait?.next_check_at ?? "", timezone: wait?.original_timezone ?? zone(), calendar: wait?.calendar ? pretty(wait.calendar) : "", milestoneId: wait?.milestone?.id ?? "", milestoneRevision: wait?.milestone ? String(wait.milestone.revision) : "", buildId: wait?.build?.id ?? "", buildRevision: wait?.build ? String(wait.build.revision) : "", replaces: "", waitRevision: wait ? String(wait.revision) : "", transferRequestId: wait?.transfer?.request_id ?? "", at: "", text: "", promisedAt: "", deliveryStatus: "unverified", replyStatus: "unknown", closeResult: "", toId: "", sources: "[]", reason: "" }; }
function sameCalendar(a: unknown, b: unknown) { return isExternalCalendarRef(a) && isExternalCalendarRef(b) && workSame({ ...a, resource_id: a.resource_id ?? null }, { ...b, resource_id: b.resource_id ?? null }); }
function reference(id: string, revision: string): WorkRef | null { if (!id && !revision) return null; return { id, revision: Number(revision) }; }
function payload(local: ExternalWaitLocal, wait: ExternalWaitSnapshot | undefined, scope: WorkScope): ExternalWaitPayload {
  const d = local.draft, schedule = { next_check_at: d.nextCheck || null, original_timezone: d.timezone, calendar: d.calendar ? JSON.parse(d.calendar) : null };
  let record: ExternalWaitRecord;
  switch (local.action) {
    case "create": record = { action: "create", ...schedule, title: d.title, target: d.target, request_content: d.request, closure_condition: d.closure, blocking: d.blocking === "true", milestone: reference(d.milestoneId, d.milestoneRevision), build: reference(d.buildId, d.buildRevision), replaces: d.replaces ? JSON.parse(d.replaces) : null }; break;
    case "details": record = { action: "details", ...schedule, title: d.title, closure_condition: d.closure, blocking: d.blocking === "true" }; break;
    case "initiate": record = { action: "initiate", at: d.at || null, text: d.text, original_timezone: d.timezone }; break;
    case "delivery": record = { action: "delivery", at: d.at || null, text: d.text, original_timezone: d.timezone, status: d.deliveryStatus as "effective" | "unverified" | "conflict" }; break;
    case "commitment": record = { action: "commitment", promised_at: d.promisedAt || null, text: d.text, original_timezone: d.timezone }; break;
    case "reply": record = { action: "reply", at: d.at || null, text: d.text, original_timezone: d.timezone, status: d.replyStatus as "partial" | "received" | "conflict" | "unknown" }; break;
    case "close": record = { action: "close", result: d.closeResult }; break;
    case "reopen": record = { action: "reopen" }; break;
    case "transfer_request": record = { action: "transfer_request", to_id: d.toId }; break;
    case "transfer_accept": case "transfer_cancel": record = { action: local.action, request_id: d.transferRequestId ?? "" }; break;
  }
  return parseExternalWaitPayload({ project_id: scope.projectId, wait: local.action === "create" ? null : wait && { id: wait.id, revision: wait.revision }, sources: parseWorkSources(d.sources ?? "[]"), reason: d.reason, record }, scope);
}
function EventView({ label, event, name }: { label: string; event: ExternalWaitEvent | null; name: (id: string) => string }) {
  return <div className={styles.event}><strong>{label}</strong>{event ? <><p>{event.text}</p><p className={styles.note}>所记发生时间 {unknownTime(event.at)} · 原时区 {event.original_timezone} · {event.time_basis === "source_claim" ? "来源声称时间" : "人工登记时间"}</p><p className={styles.note}>登记人 {name(event.actor_id)} · 服务器留存时点 {event.recorded_at}</p></> : <p className={styles.note}>尚无此类登记。</p>}</div>;
}
export function ExternalWaits(props: Props) { return <ScopedExternalWaits key={JSON.stringify([props.scope.principalId, props.scope.categoryId, props.scope.productId, props.scope.projectId])} {...props}/>; }
function ScopedExternalWaits({ api, scope, readVersion = 0, onRefresh }: Props) {
  const { categoryId, productId, projectId, principalId } = scope, storageKey = externalWaitStorageKey(scope);
  const [editorOpen, setEditorOpen] = useState(false);
  const [local, setLocal] = useState<ExternalWaitLocal>(() => ({ ...blankExternalWaitLocal(scope), draft: blankDraft() }));
  const localRef = useRef(local), epoch = useRef(0), alive = useRef(false), lock = useRef(false);
  const [hydrated, setHydrated] = useState(false), [storageOk, setStorageOk] = useState(false), [busy, setBusy] = useState(false), [denied, setDenied] = useState(false);
  const [attempt, setAttempt] = useState(0), [notice, setNotice] = useState(""), [error, setError] = useState("");
  const [reading, setReading] = useState<{ api: ProjectWorkApi; attempt: number; version: number; data: ExternalWaitView | null; error: string } | null>(null);
  const currentRead = reading?.api === api && reading.attempt === attempt && reading.version === readVersion;
  const data = currentRead ? reading.data : null, readError = currentRead ? reading.error : "";
  const selected = data?.waits.find(wait => wait.id === local.selectedId), canWrite = data?.members.some(member => member.id === principalId && member.can_write) === true;
  const editable = hydrated && storageOk && !!data && !denied && !busy && !local.pending && canWrite;
  let replaces: unknown = null; try { replaces = local.draft.replaces ? JSON.parse(local.draft.replaces) : null; } catch { replaces = false; }
  const replacementCurrent = !local.draft.replaces || data?.waits.some(wait => workSame(replaces, { id: wait.id, revision: wait.revision }));
  const selectedCurrent = !!selected && String(selected.revision) === local.draft.waitRevision && (!["transfer_accept", "transfer_cancel"].includes(local.action) || selected.transfer?.request_id === local.draft.transferRequestId);
  const mayAct = local.action === "create" ? canWrite && replacementCurrent : selectedCurrent && availableExternalWaitActions(selected!, principalId, data?.project.owner_id ?? "").includes(local.action);
  const members = data?.members ?? [], name = (id: string) => members.find(member => member.id === id)?.name ?? id;
  function persist(value: ExternalWaitLocal) { localStorage.setItem(storageKey, JSON.stringify(value)); localRef.current = value; setLocal(value); setStorageOk(true); }
  function saveEvent(value: ExternalWaitLocal) { try { persist(value); return true; } catch { setStorageOk(false); setNotice("本机保存失败，已停止业务提交。请恢复本机存储并保留原请求。"); return false; } }
  function change(field: string, value: string) { saveEvent({ ...localRef.current, receipt: null, completed: null, draft: { ...localRef.current.draft, [field]: value } }); }
  const clearPrivate = useCallback((message: string) => {
    let removed = true; try { localStorage.removeItem(storageKey); } catch { removed = false; }
    const value = { ...blankExternalWaitLocal({ categoryId, productId, projectId, principalId }), draft: blankDraft() }; localRef.current = value; setLocal(value); setDenied(true); setError(message); setNotice(removed ? "访问已失效，已清除本机私有等待材料。" : "访问已失效，已隐藏私有等待材料；本机存储无法清除，请恢复后处理。");
  }, [storageKey, categoryId, productId, projectId, principalId]);
  useEffect(() => {
    const generation = ++epoch.current; alive.current = true; lock.current = false;
    void Promise.resolve().then(() => { if (!alive.current || generation !== epoch.current) return; try { const raw = localStorage.getItem(storageKey), saved = raw ? restoreExternalWaitLocal(JSON.parse(raw), { categoryId, productId, projectId, principalId }) : null, value = saved ?? { ...blankExternalWaitLocal({ categoryId, productId, projectId, principalId }), draft: blankDraft() }; localRef.current = value; setLocal(value); setStorageOk(true); setHydrated(true); setBusy(false); if (saved?.pending) setNotice("已恢复原等待登记请求。刷新不会自动提交，请明确核对或按原请求重放。"); } catch { setStorageOk(false); setHydrated(true); setNotice("本机等待草稿暂不可读取，已停止业务写入。"); } });
    return () => { alive.current = false; epoch.current = generation + 1; lock.current = false; };
  }, [api, storageKey, categoryId, productId, projectId, principalId]);
  useEffect(() => {
    let active = true;
    void readExternalWaits(api, { categoryId, productId, projectId, principalId }).then(value => { if (active) { setReading({ api, attempt, version: readVersion, data: value, error: "" }); setDenied(false); } }).catch(failure => { if (active) { const message = failure instanceof Error ? failure.message : "等待资料暂不可读取"; setReading({ api, attempt, version: readVersion, data: null, error: message }); if ([401, 403].includes((failure as { status?: number })?.status ?? 0)) clearPrivate(message); } });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, principalId, attempt, readVersion, clearPrivate]);
  async function run(pending: ExternalWaitPending) {
    if (lock.current || !alive.current || !storageOk || denied) return;
    lock.current = true; setBusy(true); setError(""); const generation = epoch.current, active = () => alive.current && generation === epoch.current;
    try {
      const result = await runExternalWaitRequest(api, pending, { categoryId, productId, projectId, principalId }, step => { if (active()) persist({ ...localRef.current, pending: step, receipt: null, completed: null }); }, active);
      if (!active() || !result) return;
      persist({ ...localRef.current, pending: null, receipt: result.receipt, completed: result.command }); setNotice("已取得真实等待登记回执，正在读回当前版本。"); setAttempt(value => value + 1);
      try { await onRefresh?.(); } catch { if (active()) setNotice("业务已保存；外层列表待刷新，请保留现有回执，勿再次提交。"); }
    } catch (failure) { if (active()) { const message = failure instanceof Error ? failure.message : "等待登记失败"; if ([401, 403].includes((failure as { status?: number })?.status ?? 0)) clearPrivate(message); else { setError(message); setNotice(localRef.current.pending?.stage === "execute" ? "保存结果尚待核实。原请求、编号和材料已保留，请显式按原请求重放。" : "材料尚未核对完成，原请求已保留，可重新核对。"); } } }
    finally { if (active()) { lock.current = false; setBusy(false); } }
  }
  function start() { if (!editable || !mayAct || !data) return; try { const material = payload(local, selected, { categoryId, productId, projectId, principalId });
    if ((material.record.action === "create" || material.record.action === "details") && material.record.calendar && !data.available_calendars.some(calendar => sameCalendar(calendar.ref, material.record.action === "create" || material.record.action === "details" ? material.record.calendar : null)) && !(local.action === "details" && selected?.calendar && sameCalendar(selected.calendar, material.record.calendar))) throw new Error("所选日历当前没有实际项目来源，请重新选择当前可用日历或明确未知。");
    const command = newExternalWaitCommand({ categoryId, productId, projectId, principalId }, data.product_revision, material), pending: ExternalWaitPending = { stage: "inputs", command }; if (saveEvent({ ...localRef.current, pending, receipt: null, completed: null })) void run(pending); } catch (failure) { setError(failure instanceof Error ? failure.message : "请核对等待登记材料。"); } }
  function choose(action: ExternalWaitAction, wait?: ExternalWaitSnapshot, replacement = false) { if (!editable) return; setEditorOpen(true); const draft = blankDraft(wait); if (replacement && wait) draft.replaces = pretty({ id: wait.id, revision: wait.revision }); saveEvent({ ...localRef.current, action, selectedId: action === "create" ? "" : wait?.id ?? "", draft, pending: null, receipt: null, completed: null }); setError(""); }
  const d = local.draft, scheduled = ["create", "details"].includes(local.action), timed = ["create", "details", "initiate", "delivery", "commitment", "reply"].includes(local.action);
  const calendarIsAvailable = !d.calendar || data?.available_calendars.some(calendar => { try { const ref = JSON.parse(d.calendar); return isExternalCalendarRef(ref) && sameCalendar(calendar.ref, ref); } catch { return false; } });
  return <section className={styles.root} aria-label="外部等待与跟进">
    <header className={styles.heading}><div><h3>外部等待与跟进</h3></div><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setAttempt(value => value + 1)}><ArrowClockwise aria-hidden="true"/>刷新外部等待</Button></header>
    
    {notice && <p className={styles.notice} role="status">{notice}</p>}{error && <p className={styles.error} role="alert">{error}</p>}
    {!storageOk && hydrated && <Button type="button" variant="outline" onClick={() => saveEvent(localRef.current)}>重试等待草稿本机保存</Button>}
    {readError ? <p className={styles.error} role="alert">外部等待读取失败：{readError}。请刷新重试。</p> : !data ? <p className={styles.note} role="status">正在读取本项目外部等待…</p> : !denied && <>
      <div className={styles.heading}><p className={styles.note}>{data.project.name} · 已读 {data.waits.length} 条 · 时点 {data.as_of}</p><Button type="button" size="sm" variant="outline" disabled={!editable} onClick={() => choose("create")}><Plus aria-hidden="true"/>新建外部等待</Button></div>
      {data.waits.length === 0 ? <p className={styles.note}>当前可读范围内尚无外部等待。</p> : <div className={styles.cards}>{data.waits.map(wait => <article className={styles.card} key={wait.id}>
        <header className={styles.heading}><h4>{wait.title}</h4><span className={styles.badge}>{wait.state === "open" ? "内部等待进行中" : "内部等待已关闭"} · v{wait.revision}</span></header>
        <dl className={styles.facts}><div><dt>等待对象</dt><dd>{wait.target}</dd></div><div><dt>当前跟进责任人</dt><dd>{name(wait.responsible_id)}</dd></div><div><dt>原请求</dt><dd>{wait.request_content}</dd></div><div><dt>关闭条件</dt><dd>{wait.closure_condition}</dd></div><div><dt>下次内部检查</dt><dd>{unknownTime(wait.next_check_at)} · {wait.original_timezone}</dd></div><div><dt>阻塞关键进展</dt><dd>{wait.blocking ? "是，已登记阻塞" : "否，未登记阻塞"}</dd></div></dl>
        <div className={styles.clock}><strong>{clockNames[wait.clock.status]}</strong><p>有效送达起点 {unknownTime(wait.clock.response_started_at)}</p><p>{wait.clock.working_minutes === null ? "工作响应时长未知" : `累计工作响应时长 ${wait.clock.working_minutes.toLocaleString("zh-CN", { maximumSignificantDigits: 12 })} 分钟`} · {wait.clock.calendar_label ?? "实际采用日历未知"}</p>{wait.state === "closed" ? <p>内部等待已关闭，内部检查与声明时限提示已停止。</p> : <><p>{wait.clock.check_due === true ? "已到下次内部检查时间" : wait.clock.check_due === false ? "尚未到下次内部检查时间" : "下次内部检查时效未知"}</p><p>{wait.clock.claimed_commitment_due === true ? "对方声明的承诺时间已过" : wait.clock.claimed_commitment_due === false ? "对方声明的承诺时间尚未到" : "对方声明承诺的时效未知"}</p></>}</div>
        <EventView label="已发起材料" event={wait.initiation} name={name}/><EventView label={wait.delivery ? deliveryNames[wait.delivery.status] : "送达核对"} event={wait.delivery} name={name}/>
        <div className={styles.event}><strong>对方声明承诺</strong>{wait.counterparty_commitment ? <><p>{wait.counterparty_commitment.text}</p><p className={styles.note}>对方声明时间 {unknownTime(wait.counterparty_commitment.promised_at)} · 原时区 {wait.counterparty_commitment.original_timezone}</p><p className={styles.note}>登记人 {name(wait.counterparty_commitment.actor_id)} · 服务器留存时点 {wait.counterparty_commitment.recorded_at}</p></> : <p className={styles.note}>尚未登记对方声明；时间未知。</p>}</div>
        <EventView label={wait.reply ? replyNames[wait.reply.status] : "对方回复材料"} event={wait.reply} name={name}/>
        {wait.last_closure && <p className={styles.event}>最近关闭记录：{wait.last_closure.result} · 登记人 {name(wait.last_closure.actor_id)} · {wait.last_closure.recorded_at}</p>}
        {wait.transfer && <p className={styles.transfer}><Warning size={14} aria-hidden="true"/>正在请求 {name(wait.transfer.to_id)} 接收跟进责任；本人接受前，责任仍由 {name(wait.transfer.from_id)} 承担。请求时点 {wait.transfer.requested_at}</p>}
        <div className={styles.actions}>{availableExternalWaitActions(wait, principalId, data.project.owner_id).map(action => <Button key={action} type="button" size="sm" variant="outline" disabled={!editable} onClick={() => choose(action, wait)}>{externalWaitActionNames[action]}</Button>)}<Button type="button" size="sm" variant="outline" disabled={!editable} onClick={() => choose("create", wait, true)}>按原等待新建替代</Button></div>
        <details className={styles.details}><summary>固定身份、锚点与历史</summary><p>等待 {wait.id} · 当前事实 {wait.version_id} · v{wait.revision}</p><p>固定里程碑 {wait.milestone ? `${wait.milestone.id} · v${wait.milestone.revision}` : "未关联"} · 固定 Build {wait.build ? `${wait.build.id} · v${wait.build.revision}` : "未关联"}</p>{wait.replaces && <p>替代原等待 {wait.replaces.id} · v{wait.replaces.revision}。原等待保留独立状态与材料。</p>}{wait.calendar && <p>采用日历 {wait.calendar.calendar_key} · {wait.calendar.calendar_version} · 工作时区 {String(data.available_calendars.find(calendar => sameCalendar(calendar.ref, wait.calendar))?.calendar.timezone ?? "当前不可取得")} · 登记原时区 {wait.original_timezone}</p>}{wait.clock.reasons.length > 0 && <p>时效依据：{wait.clock.reasons.join("、")}</p>}{wait.history.map(history => <p key={history.id}>v{history.revision} · {externalWaitActionNames[history.action]} · {name(history.actor_id)} · {history.created_at}<small>回执 {history.receipt_id}</small></p>)}</details>
      </article>)}</div>}
      {editorOpen && !local.pending && <section className={styles.formPanel} aria-label="外部等待登记表单"><div className={styles.heading}><h4>{externalWaitActionNames[local.action]}{selected && ` · ${selected.title}`}</h4><Button type="button" size="icon-xs" variant="ghost" aria-label="收起等待编辑" onClick={()=>setEditorOpen(false)}><X/></Button></div><fieldset className={styles.form} disabled={!editable || !mayAct}>
        {local.action === "create" && <>{d.replaces && <p className={styles.note}>本次新建替代 {d.replaces}；原送达、对方声明和回复保留在原等待。请核对新的对象、请求和锚点。</p>}<label>等待对象<textarea value={d.target ?? ""} onChange={event => change("target", event.target.value)}/></label><label>原请求内容<textarea value={d.request ?? ""} onChange={event => change("request", event.target.value)}/></label><details><summary>固定业务锚点（可空）</summary><div className={styles.reference}><label>里程碑标识<input value={d.milestoneId ?? ""} onChange={event => change("milestoneId", event.target.value)}/></label><label>里程碑版本<input inputMode="numeric" value={d.milestoneRevision ?? ""} onChange={event => change("milestoneRevision", event.target.value)}/></label><label>Build 标识<input value={d.buildId ?? ""} onChange={event => change("buildId", event.target.value)}/></label><label>Build 版本<input inputMode="numeric" value={d.buildRevision ?? ""} onChange={event => change("buildRevision", event.target.value)}/></label></div></details></>}
        {scheduled && <><label>等待标题<input maxLength={200} value={d.title ?? ""} onChange={event => change("title", event.target.value)}/></label><label>内部关闭条件<textarea value={d.closure ?? ""} onChange={event => change("closure", event.target.value)}/></label><label className={styles.inline}><input type="checkbox" checked={d.blocking === "true"} onChange={event => change("blocking", String(event.target.checked))}/>此等待阻塞关键进展</label><label>下次内部检查时间（未知留空，含时区）<input value={d.nextCheck ?? ""} onChange={event => change("nextCheck", event.target.value)} placeholder="2030-10-20T09:00:00+08:00"/></label><label>明确采用的实际工作日历<select value={d.calendar ?? ""} onChange={event => change("calendar", event.target.value)}><option value="">未知，暂不采用日历</option>{!calendarIsAvailable && <option value={d.calendar}>原采用日历当前不可用（保留原引用）</option>}{data.available_calendars.map((calendar, index) => <option key={index} value={pretty(calendar.ref)}>{calendar.label} · {calendar.ref.calendar_key}/{calendar.ref.calendar_version} · {String(calendar.calendar.timezone)}</option>)}</select><small>只采用本项目实际计划或资源中的日历；这不代表对方已认可同一日历。</small></label></>}
        {["initiate", "delivery", "reply"].includes(local.action) && <label>材料所记发生时间（未知留空，含时区）<input value={d.at ?? ""} onChange={event => change("at", event.target.value)}/></label>}
        {local.action === "delivery" && <><label>送达核对结论<select value={d.deliveryStatus ?? "unverified"} onChange={event => change("deliveryStatus", event.target.value)}><option value="unverified">尚待核对</option><option value="effective">本人依据原件确认有效送达</option><option value="conflict">原件存在冲突</option></select></label><p className={styles.note}>登记有效送达须填写真实发生时间并核对实际原件；仅有原件引用不等于已有效送达。</p></>}
        {local.action === "commitment" && <><label>对方声明的承诺时间（未知留空，含时区）<input value={d.promisedAt ?? ""} onChange={event => change("promisedAt", event.target.value)}/></label><p className={styles.note}>这里留存对方声称的承诺，不据此确认到货或正式业务接收。</p></>}
        {local.action === "reply" && <label>回复材料情况<select value={d.replyStatus ?? "unknown"} onChange={event => change("replyStatus", event.target.value)}><option value="unknown">内容或结果未知</option><option value="partial">部分回复</option><option value="received">已收到回复声明</option><option value="conflict">材料存在冲突</option></select></label>}
        {["initiate", "delivery", "commitment", "reply"].includes(local.action) && <label>本次材料内容<textarea value={d.text ?? ""} onChange={event => change("text", event.target.value)}/></label>}
        {timed && <label>原时区（IANA）<input value={d.timezone ?? ""} onChange={event => change("timezone", event.target.value)}/></label>}
        {local.action === "close" && <label>内部等待关闭结果<textarea value={d.closeResult ?? ""} onChange={event => change("closeResult", event.target.value)}/><small>只关闭内部跟进状态，正式业务事实仍在各自原对象登记。</small></label>}
        {local.action === "reopen" && <p className={styles.note}>重新打开本条内部等待；原送达、对方声明、回复和关闭历史继续保留。</p>}
        {local.action === "transfer_request" && <label>请求接收跟进责任的人<select value={d.toId ?? ""} onChange={event => change("toId", event.target.value)}><option value="">请选择可写成员</option>{members.filter(member => member.can_write && member.id !== selected?.responsible_id).map(member => <option key={member.id} value={member.id}>{member.name}</option>)}</select><small>请求不会立即转移责任，须由目标本人明确接受。</small></label>}
        {["transfer_accept", "transfer_cancel"].includes(local.action) && <p className={styles.note}>{local.action === "transfer_accept" ? "本人接受后，跟进责任才转到本人。" : "撤销本条待接收请求；当前责任人保持不变。"}固定请求 {d.transferRequestId || "当前请求尚未取得"}</p>}
        <label>本次登记理由<textarea value={d.reason ?? ""} onChange={event => change("reason", event.target.value)}/></label><WorkSourcePicker api={api} scope={scope} disabled={!editable || !mayAct} value={(() => {try {return JSON.parse(d.sources ?? "[]") as WorkSource[];} catch {return [];}})()} onChange={sources=>change("sources",pretty(sources))}/><details className={styles.details}><summary>来源引用详情</summary><p className={styles.note}>引用已登记原件的准确 id、revision、kind: artifact 与 position。</p><textarea aria-label="等待登记实际来源 JSON" value={d.sources ?? "[]"} onChange={event => change("sources", event.target.value)}/></details><Button type="button" disabled={!editable || !mayAct} onClick={start}>保存本次等待登记</Button>
      </fieldset>{!canWrite && <p className={styles.note}>当前本人没有本项目写入资格，可查看现有可读等待。</p>}{!mayAct && canWrite && <p className={styles.note}>当前等待版本、状态或本人责任不允许此动作，请重新选择当前记录。</p>}</section>}
    </>}
    {local.pending && !denied && <section className={styles.pending} aria-label="已保留的等待原请求"><h4>{local.pending.stage === "execute" ? "等待登记保存结果待核实" : "等待登记材料尚待核对"}</h4><p>原请求已保留，重新打开不会自动提交。</p><Button type="button" disabled={busy || !storageOk} onClick={() => void run(local.pending!)}>{local.pending.stage === "execute" ? "按原请求核对等待保存结果" : "重新核对等待原请求"}</Button>{local.pending.stage === "inputs" && <Button type="button" variant="outline" disabled={busy || !storageOk} onClick={() => saveEvent({ ...localRef.current, pending: null })}>返回等待编辑</Button>}</section>}
    {local.receipt && !denied && <p className={styles.success}>已保存：{externalWaitActionNames[local.completed?.payload.record.action ?? local.action]} · 等待 {local.receipt.result.wait_id} · 回执 {local.receipt.id}。刷新只读回结果。</p>}
  </section>;
}
