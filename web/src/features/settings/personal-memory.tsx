"use client";

import { useEffect, useState, type FormEvent } from "react";
import { browserApi } from "@/lib/browser-api";
import {
  aliasMeaning, choicePayload, draftPayload, draftProblem, evidenceInputs, evidenceLabel, groupNotes, isCandidatesView, isNotesView, kindNames, localDay, memoryBase,
  mergedDefault, ownRelations, relationNames, requestKey, resolutionNames, scopeLabel, stanceNames, startNote, stateNames, TEXT_LIMIT,
  type Candidate, type CandidatesView, type ConflictChoice, type ConflictNote, type ConflictView, type EvidenceInput, type HistoryView, type MemoryNote, type NoteDraft,
  type NoteKind, type NotesView, type OwnerSettings, type RelationRef, type RelationType, type Resolution, type ScopeKind, type Stance,
} from "@/lib/personal-memory";
import { Button } from "../../components/ui/button";
import { ShareToProject } from "../scope-notes/share-to-project";
import styles from "./personal-memory.module.css";

type Api = typeof browserApi;
type Option = { id: string; label: string };
const scopeKindNames: Record<ScopeKind, string> = { global: "全局", category: "品类", product: "产品", proposal: "提案", project: "项目" };
const emptyDraft = (): NoteDraft => ({ kind: "convention", text: "", scope: { kind: "global", id: null }, valid_until: "", alias_term: "", alias_canonical: "", occurred_at: "", valid_from: "", evidence: [], relations: [] });
const objectKinds = ["category", "product", "proposal", "project"] as const;
type ObjectKind = typeof objectKinds[number];
const message = (failure: unknown, fallback: string) => failure instanceof Error ? failure.message : fallback;
const day = (value: string) => value.slice(0, 10);

/** Similar or contradicting old notes: the owner chooses merge, replace or keep both (P86 第 4 项). */
export function ConflictPicker({ conflicts, newer, busy, onChoose, onCancel, action = "保存" }: { conflicts: ConflictNote[]; newer: string; busy: boolean; onChoose: (choice: ConflictChoice, relation: RelationType | null) => void; onCancel: () => void; action?: string }) {
  const [resolution, setResolution] = useState<Resolution>("keep_both");
  const [relation, setRelation] = useState<RelationType | "">("");
  const historyOnly = conflicts.some(item => item.replace_effect === "history_only");
  const [target, setTarget] = useState(conflicts[0]?.note_id ?? "");
  const older = conflicts.find(item => item.note_id === target) ?? conflicts[0];
  const [merged, setMerged] = useState(() => mergedDefault(older?.text ?? "", newer));
  return <div className={styles.conflict} role="group" aria-label="相似的旧条目">
    <p className={styles.conflictTitle}>已有 {conflicts.length} 条相似或矛盾的旧条目，请选择怎么处理：</p>
    <ul className={styles.conflictList}>{conflicts.map(item => <li key={item.note_id}><span className={styles.chip}>{item.kind_label}</span><span className={styles.noteText}>{item.text}</span><span className={styles.meta}>{scopeLabel(item.scope)} · {day(item.confirmed_at)}{startNote(item) ? ` · ${startNote(item)}` : ""}</span></li>)}</ul>
    <fieldset className={styles.choices} disabled={busy}>
      <legend className="sr-only">处理方式</legend>
      {(["merge", "replace", "keep_both"] as Resolution[]).map(value => <label key={value}><input type="radio" name="memory-resolution" checked={resolution === value} onChange={() => setResolution(value)}/>{resolutionNames[value]}</label>)}
    </fieldset>
    {resolution === "merge" && <div className={styles.mergeBox}>
      {conflicts.length > 1 && <label>合并到<select value={target} onChange={event => { setTarget(event.target.value); const next = conflicts.find(item => item.note_id === event.target.value); setMerged(mergedDefault(next?.text ?? "", newer)); }}>{conflicts.map(item => <option key={item.note_id} value={item.note_id}>{item.text.slice(0, 30)}</option>)}</select></label>}
      <label>合并后的内容<textarea value={merged} maxLength={TEXT_LIMIT} rows={3} onChange={event => setMerged(event.target.value)}/></label>
      <span className={styles.counter}>{merged.length}/{TEXT_LIMIT}</span>
    </div>}
    {resolution === "replace" && <p className={styles.hint}>{historyOnly ? "这条的生效起点早于旧条目：它只记入历史，旧条目保持不变（替代按生效时间判断）。" : "旧条目在这条生效时标“已替换”，仍可在历史里查看或彻底删除。"}</p>}
    {resolution === "keep_both" && <label className={styles.inlineSelect}>同时标为<select value={relation} disabled={busy} onChange={event => setRelation(event.target.value as RelationType | "")}><option value="">不标</option><option value="conflicts">冲突（两条口径都只作背景）</option><option value="duplicates">重复</option></select></label>}
    <div className={styles.actions}>
      <Button type="button" size="sm" disabled={busy || resolution === "merge" && !merged.trim()} onClick={() => onChoose(choicePayload(resolution, conflicts, target, merged), resolution === "keep_both" && relation ? relation : null)}>{busy ? "正在保存…" : action}</Button>
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onCancel}>取消</Button>
    </div>
  </div>;
}

function ScopeField({ api, value, onChange, disabled }: { api: Api; value: NoteDraft["scope"]; onChange: (scope: NoteDraft["scope"]) => void; disabled: boolean }) {
  const [options, setOptions] = useState<{ kind: string; items: Option[]; error: string } | null>(null);
  const listed = value.kind !== "global";
  useEffect(() => {
    if (!listed) return;
    let live = true;
    // D301: products and proposals come from the memory scope options; both lists hold only what you can read now.
    const source = value.kind === "product" || value.kind === "proposal" ? "v1/personal/memory/scope-options" : "v1/personal/preferences/options";
    api<{ items: { id: string; label: string }[] }>(`${source}?kind=${value.kind}`).then(result => { if (live) setOptions({ kind: value.kind, items: result.items.map(item => ({ id: item.id, label: item.label })), error: "" }); })
      .catch(failure => { if (live) setOptions({ kind: value.kind, items: [], error: message(failure, "范围读取失败。") }); });
    return () => { live = false; };
  }, [api, value.kind, listed]);
  const current = options?.kind === value.kind ? options : null;
  return <div className={styles.scopeRow}>
    <label>作用范围<select value={value.kind} disabled={disabled} onChange={event => onChange({ kind: event.target.value as ScopeKind, id: null })}><option value="global">全局（所有对话）</option><option value="category">某个品类</option><option value="product">某个产品</option><option value="proposal">某个提案</option><option value="project">某个项目</option></select></label>
    {listed && <label>{scopeKindNames[value.kind]}<select value={value.id ?? ""} disabled={disabled || !current} onChange={event => onChange({ kind: value.kind, id: event.target.value || null })}><option value="">{current ? "请选择" : "正在读取…"}</option>{value.id && current && !current.items.some(item => item.id === value.id) && <option value={value.id}>当前所选{scopeKindNames[value.kind]}</option>}{current?.items.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>}
    {current && !current.error && current.items.length === 0 && <p role="status" className={styles.meta}>没有你当前可读的{scopeKindNames[value.kind]}。</p>}
    {current?.error && <p role="alert" className={styles.error}>{current.error}</p>}
  </div>;
}

function useObjects(api: Api, kind: ObjectKind | null) {
  const [options, setOptions] = useState<{ kind: string; items: Option[]; error: string } | null>(null);
  useEffect(() => {
    if (!kind) return;
    let live = true;
    const source = kind === "product" || kind === "proposal" ? "v1/personal/memory/scope-options" : "v1/personal/preferences/options";
    api<{ items: { id: string; label: string }[] }>(`${source}?kind=${kind}`).then(result => { if (live) setOptions({ kind, items: result.items.map(item => ({ id: item.id, label: item.label })), error: "" }); })
      .catch(failure => { if (live) setOptions({ kind, items: [], error: message(failure, "对象读取失败。") }); });
    return () => { live = false; };
  }, [api, kind]);
  return options?.kind === kind ? options : null;
}

/** 证据链接：本人可读的业务对象；已有的对话、讨论、原件等链接可查看和移除（只存引用，不存片段）。 */
function EvidenceField({ api, value, shown, onChange, disabled }: { api: Api; value: EvidenceInput[]; shown: MemoryNote["evidence"]; onChange: (links: EvidenceInput[]) => void; disabled: boolean }) {
  const [kind, setKind] = useState<ObjectKind | "">("");
  const [target, setTarget] = useState("");
  const [stance, setStance] = useState<Stance>("supports");
  const options = useObjects(api, kind || null);
  const label = (link: EvidenceInput) => {
    const known = shown?.find(item => item.source_id === link.source_id && item.source_type === link.source_type);
    if (known) return evidenceLabel(known);
    const picked = options?.items.find(item => item.id === link.source_id);
    return evidenceLabel({ source_type: link.source_type, source_kind: link.source_kind ?? null, readable: true, title: picked?.label ?? null, updated: false });
  };
  return <div className={styles.links} role="group" aria-label="证据链接">
    <span className={styles.linksTitle}>证据链接<span className={styles.meta}>（可不填；只保存出处，不保存原文）</span></span>
    {value.length > 0 && <ul className={styles.linkList}>{value.map((link, index) => <li key={`${link.source_type}:${link.source_id}:${index}`}><span className={styles.linkText}>{label(link)}</span><span className={styles.chip}>{stanceNames[link.stance]}</span><Button type="button" size="sm" variant="ghost" disabled={disabled} onClick={() => onChange(value.filter((_item, other) => other !== index))}>移除</Button></li>)}</ul>}
    {value.length < 10 && <div className={styles.linkAdd}>
      <select aria-label="依据种类" value={kind} disabled={disabled} onChange={event => { setKind(event.target.value as ObjectKind | ""); setTarget(""); }}><option value="">添加依据…</option>{objectKinds.map(item => <option key={item} value={item}>{scopeKindNames[item]}</option>)}</select>
      {kind && <select aria-label={`选择${scopeKindNames[kind]}`} value={target} disabled={disabled || !options} onChange={event => setTarget(event.target.value)}><option value="">{options ? "请选择" : "正在读取…"}</option>{options?.items.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select>}
      {kind && <select aria-label="依据的作用" value={stance} disabled={disabled} onChange={event => setStance(event.target.value as Stance)}>{(Object.keys(stanceNames) as Stance[]).map(item => <option key={item} value={item}>{stanceNames[item]}</option>)}</select>}
      {kind && <Button type="button" size="sm" variant="outline" disabled={disabled || !target} onClick={() => { onChange([...value, { source_type: "business_object", source_kind: kind, source_id: target, locator: {}, stance }]); setKind(""); setTarget(""); }}>添加</Button>}
    </div>}
    {options?.error && <p role="alert" className={styles.error}>{options.error}</p>}
  </div>;
}

/** 关系：和你自己的另一条记忆标为冲突或重复；替代通过“替换旧的”办理。 */
function RelationField({ value, others, onChange, disabled }: { value: RelationRef[]; others: MemoryNote[]; onChange: (relations: RelationRef[]) => void; disabled: boolean }) {
  const [target, setTarget] = useState("");
  const [type, setType] = useState<RelationType>("conflicts");
  const text = (id: string) => others.find(item => item.note_id === id)?.text ?? "另一条记忆";
  const free = others.filter(item => !value.some(link => link.note_id === item.note_id && link.type === type));
  if (!others.length && !value.length) return null;
  return <div className={styles.links} role="group" aria-label="关系">
    <span className={styles.linksTitle}>关系<span className={styles.meta}>（标为冲突的口径只作背景，不再约束小Pai）</span></span>
    {value.length > 0 && <ul className={styles.linkList}>{value.map(link => <li key={`${link.type}:${link.note_id}`}><span className={styles.chip}>{relationNames[link.type]}</span><span className={styles.linkText}>{text(link.note_id)}</span><Button type="button" size="sm" variant="ghost" disabled={disabled} onClick={() => onChange(value.filter(item => item !== link))}>移除</Button></li>)}</ul>}
    {others.length > 0 && value.length < 10 && <div className={styles.linkAdd}>
      <select aria-label="关系种类" value={type} disabled={disabled} onChange={event => setType(event.target.value as RelationType)}>{(Object.keys(relationNames) as RelationType[]).map(item => <option key={item} value={item}>{relationNames[item]}</option>)}</select>
      <select aria-label="关联的记忆" value={target} disabled={disabled} onChange={event => setTarget(event.target.value)}><option value="">选择你的另一条记忆…</option>{free.map(item => <option key={item.note_id} value={item.note_id}>{item.text.slice(0, 40)}</option>)}</select>
      <Button type="button" size="sm" variant="outline" disabled={disabled || !target} onClick={() => { onChange([...value, { type, note_id: target }]); setTarget(""); }}>添加</Button>
    </div>}
  </div>;
}

function NoteFields({ api, draft, setDraft, disabled, others = [], shown }: { api: Api; draft: NoteDraft; setDraft: (update: (old: NoteDraft) => NoteDraft) => void; disabled: boolean; others?: MemoryNote[]; shown?: MemoryNote["evidence"] }) {
  return <fieldset className={styles.fields} disabled={disabled}>
    <legend className="sr-only">记忆内容</legend>
    <div className={styles.kinds} role="radiogroup" aria-label="种类">{(Object.keys(kindNames) as NoteKind[]).map(kind => <label key={kind} className={styles.kind} data-checked={draft.kind === kind}><input type="radio" name="memory-kind" checked={draft.kind === kind} onChange={() => setDraft(old => ({ ...old, kind }))}/><span>{kindNames[kind].label}</span></label>)}</div>
    <p className={styles.hint}>{kindNames[draft.kind].hint}</p>
    {draft.kind === "alias" && <div className={styles.aliasRow}>
      <label>我说的词<input value={draft.alias_term ?? ""} maxLength={40} placeholder="例如：气嘴" onChange={event => setDraft(old => ({ ...old, alias_term: event.target.value }))}/></label>
      <label>指的是<input value={draft.alias_canonical ?? ""} maxLength={80} placeholder="例如：气门嘴" onChange={event => setDraft(old => ({ ...old, alias_canonical: event.target.value }))}/></label>
    </div>}
    <label className={styles.textLabel}>{draft.kind === "alias" ? "补充说明（可不填）" : "内容"}<textarea value={draft.text} maxLength={TEXT_LIMIT} rows={2} placeholder={draft.kind === "convention" ? "例如：回答先给结论，再列依据" : draft.kind === "background" ? "例如：我负责充气泵品类的成本核算" : "不填时自动写成“我说“气嘴”指气门嘴”"} onChange={event => setDraft(old => ({ ...old, text: event.target.value }))}/><span className={styles.counter}>{draft.text.length}/{TEXT_LIMIT}</span></label>
    <ScopeField api={api} value={draft.scope} disabled={disabled} onChange={scope => setDraft(old => ({ ...old, scope }))}/>
    <div className={styles.dateRow}>
      <label className={styles.dateLabel}>生效起点（可不填，从保存时起）<input type="date" value={draft.valid_from ?? ""} onChange={event => setDraft(old => ({ ...old, valid_from: event.target.value }))}/></label>
      <label className={styles.dateLabel}>有效期（可不填，默认不过期）<input type="date" value={draft.valid_until ?? ""} onChange={event => setDraft(old => ({ ...old, valid_until: event.target.value }))}/></label>
      <label className={styles.dateLabel}>事情发生的时间（可不填）<input type="date" value={draft.occurred_at ?? ""} max={localDay(new Date())} onChange={event => setDraft(old => ({ ...old, occurred_at: event.target.value }))}/></label>
    </div>
    <p className={styles.hint}>生效起点早于已有条目的旧信息，选“替换旧的”时只记入历史，不会替换现在的条目。</p>
    <EvidenceField api={api} value={draft.evidence ?? []} shown={shown} disabled={disabled} onChange={evidence => setDraft(old => ({ ...old, evidence }))}/>
    <RelationField value={draft.relations ?? []} others={others} disabled={disabled} onChange={relations => setDraft(old => ({ ...old, relations }))}/>
  </fieldset>;
}

function AddNote({ api, onSaved, disabled, others }: { api: Api; onSaved: (text: string) => void; disabled: boolean; others: MemoryNote[] }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<NoteDraft>(emptyDraft);
  const [conflicts, setConflicts] = useState<ConflictNote[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [key, setKey] = useState(requestKey);
  async function save(choice: ConflictChoice | null, relation: RelationType | null = null) {
    setBusy(true); setError("");
    const marked = relation && conflicts ? [...(draft.relations ?? []), ...conflicts.map(item => ({ type: relation, note_id: item.note_id }))] : draft.relations;
    try {
      const saved = await api<{ effect?: string; note: MemoryNote }>(`${memoryBase}/notes`, { request_key: key, note: draftPayload({ ...draft, relations: marked }), conflict: choice });
      setDraft(emptyDraft()); setConflicts(null); setOpen(false); setKey(requestKey());
      onSaved(saved?.effect === "history_only" ? "这条的生效起点早于现有条目，只记入了历史，现有条目保持不变。" : saved?.note?.state === "pending" ? "已记住，到生效起点那天才会带入对话。" : "已记住，之后的对话会按这条办理。");
    } catch (failure) {
      const detail = (failure as { detail?: { reason_key?: string; conflicts?: ConflictNote[] } }).detail;
      if (detail?.reason_key === "memory_conflict_unresolved" && detail.conflicts) { setConflicts(detail.conflicts); setKey(requestKey()); }
      else setError(message(failure, "保存未完成，填写内容仍保留。"));
    } finally { setBusy(false); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    const problem = draftProblem(draft);
    if (problem) { setError(problem); return; }
    setBusy(true); setError("");
    try {
      const found = await api<ConflictView>(`${memoryBase}/notes/conflicts`, draftPayload(draft));
      if (found.conflicts.length) { setConflicts(found.conflicts); setBusy(false); return; }
    } catch (failure) { setError(message(failure, "核对旧条目失败，请重试。")); setBusy(false); return; }
    await save(null);
  }
  if (!open) return <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={() => setOpen(true)}>添加一条记忆</Button>;
  return <form className={styles.form} onSubmit={submit} aria-label="添加记忆">
    <NoteFields api={api} draft={draft} setDraft={setDraft} disabled={busy || !!conflicts} others={others}/>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {conflicts ? <ConflictPicker conflicts={conflicts} newer={draft.text || `我说“${draft.alias_term ?? ""}”指${draft.alias_canonical ?? ""}`} busy={busy} onChoose={(choice, relation) => void save(choice, relation)} onCancel={() => setConflicts(null)}/>
      : <div className={styles.actions}><Button type="submit" size="sm" disabled={busy}>{busy ? "正在核对…" : "记住"}</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => { setOpen(false); setError(""); }}>取消</Button></div>}
  </form>;
}

function noteDraft(note: MemoryNote): NoteDraft {
  return { kind: note.kind, text: note.text, scope: { kind: note.scope.kind, id: note.scope.id }, valid_until: note.valid_until?.slice(0, 10) ?? "", alias_term: note.alias?.term ?? "", alias_canonical: note.alias?.means?.kind === "term" ? note.alias.means.text ?? "" : "",
    occurred_at: note.occurred_at ? localDay(new Date(note.occurred_at)) : "", valid_from: note.valid_from ? localDay(new Date(note.valid_from)) : "", evidence: evidenceInputs(note.evidence), relations: ownRelations(note) };
}

function NoteLinks({ note }: { note: MemoryNote }) {
  const links = note.evidence ?? [], relations = note.relations ?? [];
  if (!links.length && !relations.length) return null;
  return <ul className={styles.linkSummary} aria-label="依据与关系">
    {links.map((link, index) => <li key={`e${index}`}><span className={styles.linkKind}>依据</span>{evidenceLabel(link)}（{stanceNames[link.stance]}）</li>)}
    {relations.map(item => <li key={`${item.type}:${item.direction}:${item.note_id}`}><span className={styles.linkKind}>{item.label}</span>{item.text}</li>)}
  </ul>;
}

function NoteRow({ api, note, onChanged, readOnly, others = [] }: { api: Api; note: MemoryNote; onChanged: (text: string) => void; readOnly: boolean; others?: MemoryNote[] }) {
  const [mode, setMode] = useState<"view" | "edit" | "delete" | "history" | "share">("view");
  const [original] = useState<NoteDraft>(() => noteDraft(note));
  const [draft, setDraft] = useState<NoteDraft>(original);
  const [history, setHistory] = useState<MemoryNote[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true); setError("");
    try { await action(); setMode("view"); onChanged(done); }
    catch (failure) { setError(message(failure, "操作未完成，请刷新后重试。")); }
    finally { setBusy(false); }
  }
  async function showHistory() {
    setMode("history"); setError("");
    try { setHistory((await api<HistoryView>(`${memoryBase}/notes/${note.note_id}/history`)).versions); }
    catch (failure) { setError(message(failure, "历史读取失败。")); }
  }
  const past = note.state === "replaced" || note.state === "expired";
  return <li className={styles.row} data-state={note.state}>
    <div className={styles.rowMain}>
      <span className={styles.chip} data-kind={note.kind}>{note.kind_label}</span>
      <div className={styles.rowBody}>
        <p className={styles.noteText}>{note.kind === "alias" && note.alias ? <><strong>{note.alias.term}</strong> → {aliasMeaning(note)}</> : note.text}</p>
        {note.kind === "alias" && note.text && <p className={styles.meta}>{note.text}</p>}
        <p className={styles.meta}>{scopeLabel(note.scope)} · {note.origin === "candidate" ? "经小Pai提议、你确认" : note.origin === "merge" ? "合并" : "你本人填写"} · {note.confirmation_label ?? "本人确认"} {day(note.confirmed_at)}{startNote(note) ? ` · ${startNote(note)}` : ""}{note.valid_until ? ` · ${note.replaced_by && note.state !== "replaced" ? "将被替换于" : "有效至"} ${day(note.valid_until)}` : ""}{note.occurred_at ? ` · 发生于 ${day(note.occurred_at)}` : ""}{note.state !== "active" && <span className={styles.state} data-state={note.state}>{stateNames[note.state]}</span>}</p>
        <NoteLinks note={note}/>
      </div>
      {mode === "view" && <div className={styles.rowActions}>
        {!past && !readOnly && <Button type="button" size="sm" variant="ghost" onClick={() => setMode("edit")}>修改</Button>}
        {!past && !readOnly && note.kind !== "alias" && <Button type="button" size="sm" variant="ghost" onClick={() => setMode("share")}>分享到项目</Button>}
        <Button type="button" size="sm" variant="ghost" onClick={() => void showHistory()}>历史</Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setMode("delete")}>删除</Button>
      </div>}
    </div>
    {mode === "edit" && <form className={styles.form} onSubmit={event => { event.preventDefault(); const problem = draftProblem(draft); if (problem) { setError(problem); return; } void run(() => api(`${memoryBase}/notes/${note.note_id}/revisions`, { request_key: requestKey(), expected_revision: note.revision, note: draftPayload(draft, original) }), "已保存修改。"); }} aria-label="修改记忆">
      <NoteFields api={api} draft={draft} setDraft={setDraft} disabled={busy} others={others.filter(item => item.note_id !== note.note_id)} shown={note.evidence}/>
      <div className={styles.actions}><Button type="submit" size="sm" disabled={busy}>{busy ? "正在保存…" : "保存修改"}</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setMode("view")}>取消</Button></div>
    </form>}
    {mode === "delete" && <div className={styles.confirm} role="alertdialog" aria-label="确认删除">
      <p>删除后，这条记忆的正文和全部历史版本会立即清除，不能恢复；只留下“某时删除了一条”的记录。以往对话的运行检查点里可能仍留有带入时的副本，最迟 30 天内随检查点清除。</p>
      <div className={styles.actions}><Button type="button" size="sm" variant="destructive" disabled={busy} onClick={() => void run(() => api(`${memoryBase}/notes/${note.note_id}/deletion`, { request_key: requestKey(), expected_revision: note.revision }), "已删除，正文和历史版本已清除；以往对话检查点里的副本最迟 30 天内清除。")}>{busy ? "正在删除…" : "确认删除"}</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setMode("view")}>取消</Button></div>
    </div>}
    {mode === "share" && <ShareToProject api={api} title="分享到项目" text={note.text} kind={note.kind === "convention" ? "convention" : "concern"} sharedFrom={note.note_id} preselect={note.scope.kind === "project" ? note.scope.id : null} onDone={() => { setMode("view"); onChanged("已分享到项目：生成了一条新的团队备忘，你的个人条目保持不变。"); }} onCancel={() => setMode("view")}/>}
    {mode === "history" && <div className={styles.history}>
      {history ? <ol>{history.map(item => <li key={item.revision}><span className={styles.meta}>第 {item.revision} 版 · {day(item.confirmed_at)}{item.valid_from && day(item.valid_from) !== day(item.confirmed_at) ? ` · 自 ${day(item.valid_from)} 起` : ""}{item.state === "replaced" ? " · 已替换" : ""}</span><span>{item.text}</span></li>)}</ol> : !error && <p role="status" className={styles.meta}>正在读取历史…</p>}
      <Button type="button" size="sm" variant="ghost" onClick={() => setMode("view")}>收起历史</Button>
    </div>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
  </li>;
}

/** 小Pai 的提议卡：点“记住”才以你本人身份写入，“忽略”即作废（P86 第 2 项）。 */
export function CandidateCard({ api, candidate, onDecided, compact = false }: { api: Api; candidate: Candidate; onDecided: (text: string) => void; compact?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [choosing, setChoosing] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [conflicts, setConflicts] = useState(candidate.conflicts);
  async function decide(decision: "adopt" | "ignore", conflict: ConflictChoice | null = null, done?: string) {
    setBusy(true); setError("");
    try {
      await api(`${memoryBase}/candidates/${candidate.candidate_id}/decision`, { request_key: requestKey(), decision, conflict });
      onDecided(done ?? (decision === "adopt" ? "已记住这条提议。" : "已忽略这条提议。"));
    } catch (failure) {
      const detail = (failure as { detail?: { reason_key?: string; conflicts?: ConflictNote[] } }).detail;
      if (detail?.reason_key === "memory_conflict_unresolved" && detail.conflicts) { setConflicts(detail.conflicts); setChoosing(true); }
      else setError(message(failure, "处理未完成，请刷新后重试。"));
    } finally { setBusy(false); }
  }
  return <article className={styles.candidate} aria-label="记忆提议">
    <p className={styles.candidateTitle}>要记住这条吗？<span className={styles.chip} data-kind={candidate.kind}>{candidate.kind_label}</span></p>
    <p className={styles.noteText}>{candidate.kind === "alias" && candidate.alias ? <><strong>{candidate.alias.term}</strong> → {candidate.alias.means.text}</> : candidate.text}</p>
    <p className={styles.meta}>{scopeLabel(candidate.scope)} · {candidate.origin === "proactive" ? "你多次纠正后小Pai提议" : "你说了“记住”"} · {day(candidate.expires_at)} 前有效</p>
    {!compact && candidate.trigger.length > 0 && <p className={styles.quote}>你的原话：{candidate.trigger.map(item => `“${item.text}”`).join("、")}</p>}
    <p className={styles.hint}>{candidate.label}</p>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {sharing ? <ShareToProject api={api} title="记为项目备忘" text={candidate.text} kind="convention" preselect={candidate.scope.kind === "project" ? candidate.scope.id : null} onDone={() => { setSharing(false); void decide("ignore", null, "已记为项目备忘；这条提议不再记入你的个人记忆。"); }} onCancel={() => setSharing(false)}/>
      : choosing && conflicts.length ? <ConflictPicker conflicts={conflicts} newer={candidate.text} busy={busy} action="记住" onChoose={choice => void decide("adopt", choice)} onCancel={() => setChoosing(false)}/>
      : <div className={styles.actions}>
        <Button type="button" size="sm" disabled={busy} onClick={() => conflicts.length ? setChoosing(true) : void decide("adopt")}>{busy ? "正在处理…" : "记住"}</Button>
        {candidate.kind !== "alias" && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setSharing(true)}>记为项目备忘</Button>}
        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void decide("ignore")}>忽略</Button>
        {conflicts.length > 0 && <span className={styles.meta}>有 {conflicts.length} 条相似的旧条目，记住前需要选择处理方式</span>}
      </div>}
  </article>;
}

function ProactiveSetting({ api, settings, onSaved }: { api: Api; settings: OwnerSettings; onSaved: (value: OwnerSettings) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function change(off: boolean) {
    setBusy(true); setError("");
    try { onSaved(await api<OwnerSettings>(`${memoryBase}/settings`, { expected_revision: settings.revision, request_key: requestKey(), proactive_off: off })); }
    catch (failure) { setError(message(failure, "设置未保存，请刷新后重试。")); }
    finally { setBusy(false); }
  }
  return <div className={styles.setting}>
    <label><input type="checkbox" checked={!settings.proactive_off} disabled={busy || !settings.proposals_enabled} onChange={event => void change(!event.target.checked)}/>允许小Pai在我对同一件事纠正两次以上时主动提议（每个会话最多一次）</label>
    <p className={styles.meta}>{settings.proposals_enabled ? settings.effect : "管理员已在本租户关闭小Pai的主动提议。"}</p>
    {error && <p role="alert" className={styles.error}>{error}</p>}
  </div>;
}

export function PersonalMemory({ api = browserApi }: { api?: Api }) {
  const [view, setView] = useState<{ notes: NotesView; candidates: CandidatesView; settings: OwnerSettings } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let live = true;
    Promise.all([api<NotesView>(`${memoryBase}/notes`), api<CandidatesView>(`${memoryBase}/candidates`), api<OwnerSettings>(`${memoryBase}/settings`)]).then(([notes, candidates, settings]) => {
      if (!live) return;
      if (!isNotesView(notes) || !isCandidatesView(candidates)) { setError("记忆内容暂不可读。"); return; }
      setView({ notes, candidates, settings }); setError("");
    }).catch(failure => { if (live) setError(message(failure, "我的记忆读取失败。")); });
    return () => { live = false; };
  }, [api, attempt]);
  const refresh = (text: string) => { setNotice(text); setAttempt(n => n + 1); };
  if (!view) return <section className={styles.panel} aria-label="我的记忆"><h2>我的记忆</h2>{error ? <><p role="alert">{error}</p><Button variant="outline" size="sm" onClick={() => setAttempt(n => n + 1)}>重新读取</Button></> : <p role="status">正在读取我的记忆…</p>}</section>;
  const groups = groupNotes(view.notes.notes);
  const linkable = [...groups.convention, ...groups.alias, ...groups.background];
  const pending = view.candidates.items.filter((item: Candidate) => item.status === "pending");
  const enabled = view.notes.enabled;
  return <section className={styles.panel} aria-label="我的记忆">
    <div className={styles.heading}><h2>我的记忆</h2><span className={styles.meta}>{view.notes.active_count}/{view.notes.limit} 条</span></div>
    <p className={styles.note}>仅你本人可见。小Pai只能提议，你确认后才会写入；记忆不是业务事实，也不授予任何权限，和业务数据冲突时以业务数据为准。</p>
    {!enabled && <p role="status" className={styles.disabled}>管理员已在本租户关闭自由文本记忆：已有条目不再带入对话，你仍可以查看和删除。</p>}
    {notice && <p role="status" className={styles.notice}>{notice}</p>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {pending.length > 0 && <div className={styles.block}><h3>待你确认的提议（{pending.length}）</h3>{pending.map(item => <CandidateCard key={item.candidate_id} api={api} candidate={item} onDecided={refresh}/>)}</div>}
    <div className={styles.block}><AddNote api={api} disabled={!enabled || view.notes.active_count >= view.notes.limit} onSaved={refresh} others={linkable}/>{view.notes.active_count >= view.notes.limit && <p className={styles.meta}>已达 {view.notes.limit} 条上限，请先删除或合并旧条目。</p>}</div>
    {(["convention", "alias", "background"] as const).map(kind => groups[kind].length > 0 && <div key={kind} className={styles.block}>
      <h3>{kindNames[kind].label}<span className={styles.meta}>{kind === "background" ? "只作背景" : kind === "alias" ? "只影响你的检索" : "约束说法与做法"}</span></h3>
      <ul className={styles.list}>{groups[kind].map(note => <NoteRow key={`${note.note_id}:${note.revision}`} api={api} note={note} readOnly={!enabled} onChanged={refresh} others={linkable}/>)}</ul>
    </div>)}
    {!groups.convention.length && !groups.alias.length && !groups.background.length && <p className={styles.empty}>还没有记忆条目。你可以在这里添加，或在对话里说“记住……”。</p>}
    {groups.past.length > 0 && <details className={styles.past}><summary>已替换或已过期（{groups.past.length}）</summary><ul className={styles.list}>{groups.past.map(note => <NoteRow key={`${note.note_id}:${note.revision}`} api={api} note={note} readOnly onChanged={refresh}/>)}</ul></details>}
    {view.notes.deleted_count > 0 && <p className={styles.meta}>已删除 {view.notes.deleted_count} 条（正文已清除）。</p>}
    <ProactiveSetting api={api} settings={view.settings} onSaved={settings => { setView(old => old && { ...old, settings }); setNotice("设置已保存。"); }}/>
  </section>;
}
