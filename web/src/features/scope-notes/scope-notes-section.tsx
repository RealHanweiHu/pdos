"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { NotePencil, Plus, PushPin } from "@phosphor-icons/react";
import { browserApi } from "@/lib/browser-api";
import {
  actionNames, bodyPayload, commandEnvelope, commandPath, draftOf, draftProblem, emptyDraft, epistemicNames, evidenceLine, evidencePayload, flagNames, formalKey, isScopeNotesView, itemPath, kindNames,
  listPath, noteMeta, optionKey, REASON_LIMIT, relationPayload, requestKey, similarNames, sourcesPath, splitNotes, stanceNames, stateNames, STATEMENT_LIMIT,
  type AnchorKind, type Epistemic, type EvidenceDraft, type NoteDraft, type NoteKind, type Prepared, type ScopeNote, type ScopeNoteHistory, type ScopeNotesView, type SimilarChoice, type SourcesView, type Stance,
} from "@/lib/scope-notes";
import { Button } from "../../components/ui/button";
import styles from "./scope-notes.module.css";

type Api = typeof browserApi;
type Scope = { categoryId: string; productId?: string | null; anchor: { kind: AnchorKind; id: string } };
type Failure = { detail?: { reason_key?: string; similar?: ScopeNote[] } };
const message = (failure: unknown, fallback: string) => failure instanceof Error ? failure.message : fallback;
const day = (value: string) => value.slice(0, 10);

/** One command, previewed then confirmed once; the two calls share one command id and key. */
function useCommand(api: Api, scope: Scope) {
  const ids = useRef({ command: requestKey(), key: requestKey() });
  const renew = () => { ids.current = { command: requestKey(), key: requestKey() }; };
  return {
    renew,
    preview: (operation: string, payload: unknown) => api<Prepared>(commandPath(scope.categoryId, true), commandEnvelope(operation, payload, { categoryId: scope.categoryId, productId: scope.productId }, ids.current)),
    confirm: async (prepared: Prepared) => { const result = await api(commandPath(scope.categoryId), prepared.command); renew(); return result; },
  };
}

/** 可关联的来源与正式对象：服务器按读者当前权限列出；需要时才读一次。 */
function useSources(api: Api, scope: Scope, wanted: boolean) {
  const [sources, setSources] = useState<SourcesView | null>(null);
  const [failed, setFailed] = useState("");
  useEffect(() => {
    if (!wanted || sources) return;
    let live = true;
    api<SourcesView>(sourcesPath(scope.categoryId, scope.anchor.kind, scope.anchor.id))
      .then(result => { if (live) { setSources(result); setFailed(""); } })
      .catch(failure => { if (live) setFailed(message(failure, "可关联的对象读取失败。")); });
    return () => { live = false; };
  }, [api, scope.categoryId, scope.anchor.kind, scope.anchor.id, wanted, sources]);
  return { sources, failed };
}

function Fields({ draft, setDraft, view, editing, disabled, sources, sourcesFailed }: { draft: NoteDraft; setDraft: (update: (old: NoteDraft) => NoteDraft) => void; view: ScopeNotesView; editing: boolean; disabled: boolean; sources: SourcesView | null; sourcesFailed: string }) {
  const formalHere = draft.kind === "decision_context";
  const here = formalKey(view.anchor.kind, view.anchor.id);
  const formal = sources?.formal ?? [];
  return <fieldset className={styles.fields} disabled={disabled}>
    <legend className="sr-only">备忘内容</legend>
    {!editing && <div className={styles.kinds} role="radiogroup" aria-label="种类">{(Object.keys(kindNames) as NoteKind[]).map(kind => <label key={kind} className={styles.kind} data-checked={draft.kind === kind}><input type="radio" name={`scope-note-kind-${view.anchor.id}`} checked={draft.kind === kind} onChange={() => setDraft(old => ({ ...old, kind, formal: kind === "decision_context" ? old.formal : "" }))}/><span>{kindNames[kind].label}</span></label>)}</div>}
    <p className={styles.hint}>{kindNames[draft.kind].hint}</p>
    <label>内容<textarea value={draft.statement} maxLength={STATEMENT_LIMIT} rows={3} placeholder={draft.kind === "convention" ? "例如：本项目样件编号按 项目-批次-序号" : draft.kind === "concern" ? "例如：客户评审必问跌落测试" : draft.kind === "decision_context" ? "例如：噪音放宽 3dB 是电话里同意的，正式变更待补" : "例如：最近三批气嘴来料毛刺偏多"} onChange={event => setDraft(old => ({ ...old, statement: event.target.value }))}/></label>
    <span className={styles.counter}>{draft.statement.length}/{STATEMENT_LIMIT}</span>
    <div className={styles.pair}>
      <label>可信状态<select value={draft.epistemic} onChange={event => setDraft(old => ({ ...old, epistemic: event.target.value as Epistemic }))}>{(Object.keys(epistemicNames) as Epistemic[]).map(value => <option key={value} value={value}>{epistemicNames[value]}</option>)}</select></label>
      <label>生效日期（可不填，默认现在）<input type="date" value={draft.valid_from} onChange={event => setDraft(old => ({ ...old, valid_from: event.target.value }))}/></label>
    </div>
    {draft.epistemic === "verified" && <p className={styles.hint}>“已核实”须已关联一条业务记录，或有两个相互独立的来源；否则保存会被拒绝。</p>}
    {view.customers?.length ? <label>客户标签（可不选）<select value={draft.customer} onChange={event => setDraft(old => ({ ...old, customer: event.target.value }))}><option value="">不加客户标签</option>{view.customers.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
      : (view.anchor.kind === "category" || view.anchor.kind === "product") && <label>客户标签（可不填）<input value={draft.customer} maxLength={80} placeholder="填了以后，只在同一客户的提案和项目里带入" onChange={event => setDraft(old => ({ ...old, customer: event.target.value }))}/></label>}
    <div className={styles.checks}>
      <label><input type="checkbox" checked={draft.pinned} onChange={event => setDraft(old => ({ ...old, pinned: event.target.checked }))}/>置顶（优先带入小Pai 上下文）</label>
      <label><input type="checkbox" checked={draft.discussion} onChange={event => setDraft(old => ({ ...old, discussion: event.target.checked }))}/>这只是讨论中的说法，团队还没约定</label>
    </div>
    {formalHere && <label>正式记录（决定或对象的当前版本）<select value={draft.formal} onChange={event => setDraft(old => ({ ...old, formal: event.target.value }))}>
      <option value="">不关联正式记录</option>
      {!formal.some(option => optionKey(option) === here) && <option value={here}>这个{view.anchor.kind_label}{view.anchor.title ? `：${view.anchor.title}` : ""}</option>}
      {draft.formal && !formal.some(option => optionKey(option) === draft.formal) && draft.formal !== here && <option value={draft.formal}>当前关联的对象</option>}
      {formal.map(option => <option key={optionKey(option)} value={optionKey(option)}>{option.type_label}：{option.title ?? "当前不可读"}{option.version ? `（第 ${option.version} 版）` : ""}</option>)}
    </select></label>}
    {formalHere && sourcesFailed && <p className={styles.hint}>{sourcesFailed} 仍可关联这个{view.anchor.kind_label}本身。</p>}
    {formalHere && !draft.formal && <p className={styles.hint}>不关联正式记录时，这条会标“未形成正式决定”。</p>}
  </fieldset>;
}

function SimilarPicker({ similar, busy, onChoose, onCancel }: { similar: ScopeNote[]; busy: boolean; onChoose: (choice: SimilarChoice) => void; onCancel: () => void }) {
  const [choice, setChoice] = useState<SimilarChoice>("keep");
  return <div className={styles.similar} role="group" aria-label="相似的备忘">
    <p className={styles.strong}>已有 {similar.length} 条相似或矛盾的备忘，请选择怎么处理：</p>
    <ul>{similar.map(item => <li key={item.note_id}><span className={styles.chip} data-kind={item.kind}>{item.kind_label}</span><span className={styles.text}>{item.statement}</span><span className={styles.meta}>{item.anchor.kind_label} · {noteMeta(item)}</span></li>)}</ul>
    <fieldset className={styles.choices} disabled={busy}><legend className="sr-only">处理方式</legend>{(Object.keys(similarNames) as SimilarChoice[]).map(value => <label key={value}><input type="radio" name="scope-note-similar" checked={choice === value} onChange={() => setChoice(value)}/>{similarNames[value]}</label>)}</fieldset>
    {choice === "supersede" && <p className={styles.hint}>按生效时间判断：新条目生效更晚时旧条目进历史；补录的更早信息只进历史，不替代现有条目。</p>}
    <div className={styles.actions}><Button type="button" size="sm" disabled={busy} onClick={() => onChoose(choice)}>{busy ? "正在核对…" : "继续"}</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={onCancel}>返回修改</Button></div>
  </div>;
}

/** 确认卡：服务器给出的实际内容、受众和进入哪个区；点“确认保存”才写入（T1 一次确认）。 */
function ReviewCard({ prepared, busy, onConfirm, onBack, action }: { prepared: Prepared; busy: boolean; onConfirm: () => void; onBack: () => void; action: string }) {
  const review = prepared.review;
  return <div className={styles.review} role="group" aria-label="确认保存">
    <p className={styles.strong}>{review.effect}</p>
    {review.statement && <p className={styles.text}>{review.kind_label && <span className={styles.chip}>{review.kind_label}</span>} {review.statement}</p>}
    <dl>
      {review.audience && <><dt>谁能看到</dt><dd>{review.audience.text}</dd></>}
      {review.zone && <><dt>小Pai 怎么用</dt><dd>{review.zone === "constraint" ? "作为约定约束做法和表达，不能当依据引用。" : "只作背景，不能当依据引用。"}</dd></>}
      {review.formal_status === "no_formal_decision" && <><dt>正式记录</dt><dd>未关联，将标“未形成正式决定”。</dd></>}
      {review.customer && <><dt>客户标签</dt><dd>{review.customer}（只在同一客户的提案和项目里带入）</dd></>}
      {review.review_days && <><dt>复核</dt><dd>{review.review_days} 天后标“待复核”。</dd></>}
      {review.evidence_added ? <><dt>证据</dt><dd>补充 {review.evidence_added} 条链接；内容和确认状态不变。</dd></> : null}
    </dl>
    <div className={styles.actions}><Button type="button" size="sm" disabled={busy} onClick={onConfirm}>{busy ? "正在保存…" : action}</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={onBack}>返回修改</Button></div>
  </div>;
}

/** 新建或修改一条备忘：填写 → 服务器预览（相似条目、受众）→ 确认一次。 */
export function NoteForm({ api, scope, view, note, initial, sharedFrom, onDone, onCancel }: { api: Api; scope: Scope; view: ScopeNotesView; note?: ScopeNote; initial?: Partial<NoteDraft>; sharedFrom?: string; onDone: (text: string) => void; onCancel: () => void }) {
  const [draft, setDraft] = useState<NoteDraft>(() => note ? draftOf(note) : { ...emptyDraft(), ...initial });
  const [similar, setSimilar] = useState<ScopeNote[] | null>(null);
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const command = useCommand(api, scope);
  const ref = useRef(requestKey());
  const { sources, failed } = useSources(api, scope, draft.kind === "decision_context");
  async function preview(choice: SimilarChoice | null) {
    const problem = draftProblem(draft);
    if (problem) { setError(problem); return; }
    setBusy(true); setError("");
    const body = bodyPayload(draft);
    const payload = note
      ? { anchor: scope.anchor, note: { id: note.note_id, revision: note.revision }, body }
      : { anchor: scope.anchor, body, ...(choice && similar ? relationPayload(choice, similar) : {}), ...(sharedFrom ? { shared_from_note: sharedFrom } : {}), request_ref: ref.current };
    try { setPrepared(await command.preview("scope_note.save", payload)); setSimilar(null); }
    catch (failure) {
      const detail = (failure as Failure).detail;
      if (detail?.reason_key === "scope_note_similar_unresolved" && detail.similar) { setSimilar(detail.similar); command.renew(); }
      else setError(message(failure, "核对未完成，填写内容仍保留。"));
    } finally { setBusy(false); }
  }
  async function confirm() {
    if (!prepared) return;
    setBusy(true); setError("");
    try { await command.confirm(prepared); onDone(note ? "已保存修改，旧版本保留在历史里。" : "已保存，团队成员可以看到这条备忘。"); }
    catch (failure) { setPrepared(null); command.renew(); setError(message(failure, "保存未完成，填写内容仍保留，请重新核对。")); }
    finally { setBusy(false); }
  }
  return <form className={styles.form} aria-label={note ? "修改备忘" : "记一条备忘"} onSubmit={(event: FormEvent) => { event.preventDefault(); void preview(null); }}>
    <Fields draft={draft} setDraft={setDraft} view={view} editing={!!note} disabled={busy || !!prepared || !!similar} sources={sources} sourcesFailed={failed}/>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {prepared ? <ReviewCard prepared={prepared} busy={busy} action="确认保存" onConfirm={() => void confirm()} onBack={() => { setPrepared(null); command.renew(); }}/>
      : similar ? <SimilarPicker similar={similar} busy={busy} onChoose={choice => void preview(choice)} onCancel={() => setSimilar(null)}/>
      : <div className={styles.actions}><Button type="submit" size="sm" disabled={busy}>{busy ? "正在核对…" : "下一步：核对受众"}</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={onCancel}>取消</Button></div>}
  </form>;
}

const blankEvidence = (): EvidenceDraft => ({ key: "", stance: "supports", where: "", quote: "" });

/** 补充证据：从服务器列出的来源里选，预览后确认一次（scope_note.observation.record，证据模式）；内容和确认状态不变。 */
function EvidenceForm({ api, scope, note, onDone, onCancel }: { api: Api; scope: Scope; note: ScopeNote; onDone: (text: string) => void; onCancel: () => void }) {
  const { sources, failed } = useSources(api, scope, true);
  const [items, setItems] = useState<EvidenceDraft[]>(() => [blankEvidence()]);
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const command = useCommand(api, scope);
  const options = sources?.sources ?? [];
  const groups = [...new Set(options.map(option => option.type_label))];
  const update = (index: number, change: Partial<EvidenceDraft>) => setItems(old => old.map((item, at) => at === index ? { ...item, ...change } : item));
  async function preview() {
    const chosen = items.filter(item => item.key);
    if (!chosen.length) { setError("请至少选一个来源。"); return; }
    setBusy(true); setError("");
    try { setPrepared(await command.preview("scope_note.observation.record", evidencePayload(note, chosen, options))); }
    catch (failure) { command.renew(); setError(message(failure, "核对未完成，所选内容仍保留。")); }
    finally { setBusy(false); }
  }
  async function confirm() {
    if (!prepared) return;
    setBusy(true); setError("");
    try { await command.confirm(prepared); onDone("已补充证据，历史里可以看到每条链接。"); }
    catch (failure) { setPrepared(null); command.renew(); setError(message(failure, "保存未完成，请重新核对。")); }
    finally { setBusy(false); }
  }
  return <form className={styles.form} aria-label="补充证据" onSubmit={(event: FormEvent) => { event.preventDefault(); void preview(); }}>
    <p className={styles.hint}>{sources?.note ?? "只列你现在能读到的对象；保存时服务器按当前权限逐条再核对。"}</p>
    {!sources && !failed && <p role="status" className={styles.meta}>正在读取可关联的对象…</p>}
    {failed && <p role="alert" className={styles.error}>{failed}</p>}
    {sources && !options.length && <p className={styles.empty}>这个范围里暂时没有你能关联的对象。</p>}
    {sources && options.length > 0 && <fieldset className={styles.fields} disabled={busy || !!prepared}>
      <legend className="sr-only">证据来源</legend>
      {items.map((item, index) => <div key={index} className={styles.evidenceItem}>
        <label>来源<select value={item.key} onChange={event => update(index, { key: event.target.value })}>
          <option value="">选择一个对象</option>
          {groups.map(group => <optgroup key={group} label={group}>{options.filter(option => option.type_label === group).map(option => <option key={optionKey(option)} value={optionKey(option)}>{option.title ?? "当前不可读"}{option.version ? `（第 ${option.version} 版）` : ""}</option>)}</optgroup>)}
        </select></label>
        <div className={styles.pair}>
          <label>立场<select value={item.stance} onChange={event => update(index, { stance: event.target.value as Stance })}>{(Object.keys(stanceNames) as Stance[]).map(value => <option key={value} value={value}>{stanceNames[value]}</option>)}</select></label>
          <label>位置（可不填）<input value={item.where} maxLength={80} placeholder="例如：第 3 页、第 2 轮、表 4" onChange={event => update(index, { where: event.target.value })}/></label>
        </div>
        <label>摘录（可不填；只存摘要，不存原文）<textarea rows={2} maxLength={2000} value={item.quote} onChange={event => update(index, { quote: event.target.value })}/></label>
        {items.length > 1 && <Button type="button" size="xs" variant="ghost" onClick={() => setItems(old => old.filter((_item, at) => at !== index))}>去掉这条</Button>}
      </div>)}
      {items.length < 10 && <Button type="button" size="xs" variant="ghost" onClick={() => setItems(old => [...old, blankEvidence()])}><Plus size={12} aria-hidden/>再加一条</Button>}
    </fieldset>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {prepared ? <ReviewCard prepared={prepared} busy={busy} action="确认补充" onConfirm={() => void confirm()} onBack={() => { setPrepared(null); command.renew(); }}/>
      : <div className={styles.actions}><Button type="submit" size="sm" disabled={busy || !options.length}>{busy ? "正在核对…" : "下一步：核对"}</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={onCancel}>取消</Button></div>}
  </form>;
}

function Row({ api, scope, view, note, onChanged }: { api: Api; scope: Scope; view: ScopeNotesView; note: ScopeNote; onChanged: (text: string) => void }) {
  const [mode, setMode] = useState<"view" | "edit" | "stop" | "history" | "evidence">("view");
  const [history, setHistory] = useState<ScopeNoteHistory | null>(null);
  const [action, setAction] = useState<"retire" | "withdraw">("retire");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const command = useCommand(api, scope);
  const live = note.state === "active" && view.can_write;
  async function showHistory() {
    setMode("history"); setError("");
    try { setHistory(await api<ScopeNoteHistory>(itemPath(scope.categoryId, note.note_id))); }
    catch (failure) { setError(message(failure, "历史读取失败。")); }
  }
  async function stop() {
    if (!reason.trim()) { setError("请写明原因。"); return; }
    setBusy(true); setError("");
    try {
      const prepared = await command.preview("scope_note.retire", { note: { id: note.note_id, revision: note.revision }, action, reason: reason.trim() });
      await command.confirm(prepared);
      onChanged(action === "retire" ? "已停用，版本历史保留。" : "已撤回，记录和原因保留。");
    } catch (failure) { command.renew(); setError(message(failure, "操作未完成，请刷新后重试。")); }
    finally { setBusy(false); }
  }
  return <li className={styles.row} data-state={note.state}>
    <div className={styles.rowMain}>
      <span className={styles.chip} data-kind={note.kind}>{note.kind_label}</span>
      <div className={styles.rowBody}>
        <p className={styles.text}>{note.pinned && <PushPin size={12} weight="fill" aria-label="置顶" className={styles.pin}/>}{note.statement}</p>
        <p className={styles.meta}>{noteMeta(note)}
          {note.state !== "active" && <span className={styles.state} data-tone="muted">{stateNames[note.state]}</span>}
          {note.state === "active" && <span className={styles.state} data-tone={note.zone === "constraint" ? "primary" : "muted"}>{note.zone === "constraint" ? "约束做法" : "只作背景"}</span>}
          {note.flags.map(flag => <span key={flag} className={styles.state} data-tone="primary">{flagNames[flag]}</span>)}
        </p>
        {note.formal && <p className={styles.meta}>正式记录：{note.formal.title ?? "当前不可读"} 第 {note.formal.version} 版{note.formal.updated ? "（已有新版本）" : ""}</p>}
        {note.reason && note.state !== "active" && <p className={styles.meta}>原因：{note.reason}</p>}
      </div>
      {mode === "view" && <div className={styles.rowActions}>
        {live && <Button type="button" size="sm" variant="ghost" onClick={() => setMode("edit")}>修改</Button>}
        {live && <Button type="button" size="sm" variant="ghost" onClick={() => setMode("evidence")}>补充证据</Button>}
        <Button type="button" size="sm" variant="ghost" onClick={() => void showHistory()}>历史</Button>
        {live && <Button type="button" size="sm" variant="ghost" onClick={() => setMode("stop")}>停用</Button>}
      </div>}
    </div>
    {mode === "edit" && <NoteForm api={api} scope={scope} view={view} note={note} onDone={onChanged} onCancel={() => setMode("view")}/>}
    {mode === "evidence" && <EvidenceForm api={api} scope={scope} note={note} onDone={onChanged} onCancel={() => setMode("view")}/>}
    {mode === "stop" && <div className={styles.confirm} role="alertdialog" aria-label="停用或撤回备忘">
      <fieldset className={styles.choices} disabled={busy}><legend className="sr-only">处理方式</legend>
        <label><input type="radio" name={`scope-note-stop-${note.note_id}`} checked={action === "retire"} onChange={() => setAction("retire")}/>停用（不再适用）</label>
        <label><input type="radio" name={`scope-note-stop-${note.note_id}`} checked={action === "withdraw"} onChange={() => setAction("withdraw")}/>撤回（内容不成立）</label>
      </fieldset>
      <label className={styles.reason}>原因<input value={reason} maxLength={REASON_LIMIT} disabled={busy} placeholder={action === "retire" ? "例如：项目已结束" : "例如：客户没有这样说过"} onChange={event => setReason(event.target.value)}/></label>
      <p>确认后，这条备忘不再带入任何人的小Pai 上下文。备忘是业务记录，不会删除，版本历史和原因保留。</p>
      <div className={styles.actions}><Button type="button" size="sm" variant="destructive" disabled={busy} onClick={() => void stop()}>{busy ? "正在办理…" : action === "retire" ? "确认停用" : "确认撤回"}</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => { setMode("view"); setError(""); }}>取消</Button></div>
    </div>}
    {mode === "history" && <div className={styles.history}>
      {history ? <><ol>{history.versions.map(item => <li key={item.revision}><span className={styles.meta}>第 {item.revision} 版 · {actionNames[item.action] ?? item.action} · {item.by?.name ?? "成员"} · {day(item.recorded_at)} · {item.confirmation_label}{item.reason ? ` · 原因：${item.reason}` : ""}</span><span>{item.statement}</span></li>)}</ol>
        <div className={styles.evidence}><p className={styles.meta}>证据链接 {history.note.evidence_count} 条 · 来源权威性按证据由服务器算出，不存引文原文。</p>
          {history.note.evidence?.length ? <ul>{history.note.evidence.map(link => <li key={link.id} data-readable={link.title !== null}><span className={styles.meta}>{evidenceLine(link)}</span></li>)}</ul> : null}</div></> : !error && <p role="status" className={styles.meta}>正在读取历史…</p>}
      <Button type="button" size="sm" variant="ghost" onClick={() => setMode("view")}>收起历史</Button>
    </div>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
  </li>;
}

/** 驾驶舱、提案页、品类页共用的“团队备忘”区：查看、保存确认、停用或撤回、历史。 */
export function ScopeNotesSection({ api = browserApi, categoryId, productId = null, anchor, readVersion = 0 }: { api?: Api; categoryId: string; productId?: string | null; anchor: { kind: AnchorKind; id: string }; readVersion?: number }) {
  const [view, setView] = useState<ScopeNotesView | null>(null);
  const [past, setPast] = useState<ScopeNote[] | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const scope: Scope = { categoryId, productId, anchor };
  useEffect(() => {
    let live = true;
    api<ScopeNotesView>(listPath(categoryId, anchor.kind, anchor.id)).then(result => {
      if (!live) return;
      if (!isScopeNotesView(result)) { setError("团队备忘暂不可读。"); return; }
      setView(result); setPast(null); setError("");
    }).catch(failure => { if (live) setError(message(failure, "团队备忘读取失败。")); });
    return () => { live = false; };
  }, [api, categoryId, anchor.kind, anchor.id, attempt, readVersion]);
  const refresh = (text: string) => { setNotice(text); setAdding(false); setAttempt(n => n + 1); };
  async function showPast() {
    try { setPast(splitNotes((await api<ScopeNotesView>(listPath(categoryId, anchor.kind, anchor.id, true))).notes).past); }
    catch (failure) { setError(message(failure, "历史备忘读取失败。")); }
  }
  if (!view) return <section className={styles.section} aria-label="团队备忘"><div className={styles.head}><h3><NotePencil size={14} aria-hidden/> 团队备忘</h3></div>{error ? <><p role="alert" className={styles.error}>{error}</p><Button variant="outline" size="sm" onClick={() => setAttempt(n => n + 1)}>重新读取</Button></> : <p role="status" className={styles.meta}>正在读取团队备忘…</p>}</section>;
  return <section className={styles.section} aria-label="团队备忘">
    <div className={styles.head}>
      <h3><NotePencil size={14} aria-hidden/> 团队备忘<small>{view.notes.length} 条</small></h3>
      {view.can_write && !adding && <Button type="button" size="xs" variant="ghost" onClick={() => setAdding(true)}><Plus size={12} aria-hidden/>记一条</Button>}
    </div>
    <p className={styles.note}>挂在这个{view.anchor.kind_label}上，随它的受众可见。备忘不是业务事实，不能作为判据或依据；和业务数据冲突时以业务数据为准。</p>
    {notice && <p role="status" className={styles.notice}>{notice}</p>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {adding && <NoteForm api={api} scope={scope} view={view} onDone={refresh} onCancel={() => setAdding(false)}/>}
    {view.notes.length ? <ul className={styles.list}>{view.notes.map(note => <Row key={`${note.note_id}:${note.revision}`} api={api} scope={scope} view={view} note={note} onChanged={refresh}/>)}</ul>
      : !adding && <p className={styles.empty}>还没有团队备忘。{view.can_write ? "团队约定、客户关注点、决策背景可以记在这里。" : "你对这个范围只有读取权限。"}</p>}
    {view.inactive_count > 0 && <details className={styles.past} onToggle={event => { if ((event.target as HTMLDetailsElement).open && !past) void showPast(); }}>
      <summary>已停用、撤回或被替代（{view.inactive_count}）</summary>
      {past ? <ul className={styles.list}>{past.map(note => <Row key={`${note.note_id}:${note.revision}`} api={api} scope={scope} view={view} note={note} onChanged={refresh}/>)}</ul> : <p role="status" className={styles.meta}>正在读取…</p>}
    </details>}
  </section>;
}
