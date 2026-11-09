"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { CalendarBlank, Plus, Trash } from "@phosphor-icons/react";
import { browserApi } from "@/lib/browser-api";
import { Button } from "@/components/ui/button";
import {
  KIND_LABELS, WEEKDAYS, definitionBody, draftOf, draftProblems, formatInstant, rangeText, sortEntries, weekdayText, yearSummary, zonedInstant,
  type CalendarEntry, type CalendarListing, type Draft, type EntryKind, type WorkCalendar,
} from "./lib/work-calendar";
import styles from "./work-calendar.module.css";

type Api = <T>(path: string, body?: unknown) => Promise<T>;
type Editing = { calendarId: string | null; kind: "factory" | "supplier"; name: string; draft: Draft; reason: string; requestKey: string };
const blankEntry = (): CalendarEntry => ({ kind: "shutdown", start: "", end: "", label: "" });
const when = (iso: string) => new Date(iso).toLocaleString("zh-CN", { year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });

/** Settings → 工作日历 (D221). Every member reads; only a tenant administrator saves, never 小Pai. */
export function WorkCalendarSettings({ api = browserApi }: { api?: Api }) {
  const [listing, setListing] = useState<CalendarListing | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [editing, setEditing] = useState<Editing | null>(null);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  const read = useCallback(async () => {
    try { const value = await api<CalendarListing>("v1/work-calendars"); setListing(value); setError(""); setSelected(old => value.calendars.some(item => item.calendar_id === old) ? old : value.calendars[0]?.calendar_id ?? ""); }
    catch (failure) { setError((failure as Error).message); }
  }, [api]);
  useEffect(() => { void Promise.resolve().then(read); }, [read]);
  const current = listing?.calendars.find(item => item.calendar_id === selected) ?? null;
  const factory = listing?.calendars.find(item => item.kind === "factory") ?? null;

  function edit(calendar: WorkCalendar | null, kind: "factory" | "supplier" = "factory") {
    setNotice(""); setError("");
    setEditing({ calendarId: calendar?.calendar_id ?? null, kind: calendar?.kind ?? kind, name: "", draft: draftOf(calendar), reason: "", requestKey: crypto.randomUUID() });
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!editing || busy) return;
    setBusy(true); setError(""); setNotice("");
    const body = definitionBody(editing.draft, editing.reason, editing.requestKey);
    try {
      const saved = editing.calendarId
        ? await api<WorkCalendar>(`v1/work-calendars/${editing.calendarId}/versions`, { expected_revision: current?.revision, ...body })
        : await api<WorkCalendar>("v1/work-calendars", { kind: editing.kind, ...(editing.kind === "supplier" ? { name: editing.name.trim() } : {}), ...body });
      setEditing(null); setSelected(saved.calendar_id); setNotice(`已保存为${saved.label}第 ${saved.revision} 版。`);
      await read();
    } catch (failure) {
      const value = failure as Error & { code?: string };
      // A retry keeps the request key, so an unknown outcome is never saved twice.
      setError(value.code === "VERSION_CONFLICT" ? `${value.message} 你的修改还在下面，刷新后需要重新核对。` : value.message);
    } finally { setBusy(false); }
  }

  if (!listing) return <section className={styles.section} aria-label="工作日历">{error ? <div role="alert" className={styles.alert}>{error}<Button size="sm" variant="outline" onClick={() => void read()}>重新读取</Button></div> : <p role="status" className={styles.muted}>正在读取工作日历…</p>}</section>;
  return <section className={styles.section} aria-label="工作日历">
    <div className={styles.head}><div>
      <h2>工作日历</h2>
      <p>排期和自动化规则按这里算工作日。法定假日、调休上班和工厂停线登记在工厂日历；供应商停线另建供应商日历，不影响工厂日历。每次保存都是新的一版，已排定的承诺和基线不随日历改动，只有预测会按新日历重算。只有租户管理员能修改，小Pai 只能读。</p>
    </div></div>
    <p className={styles.basis} data-basis={listing.basis.basis} role="status"><CalendarBlank aria-hidden/>{listing.basis.basis === "tenant_calendar" ? `当前${listing.basis.basis_label}。` : `尚未登记工厂日历：${listing.basis.basis_label}。`}</p>
    {error && <p role="alert" className={styles.alert}>{error}</p>}
    {notice && <p role="status" className={styles.muted}>{notice}</p>}
    <nav className={styles.picker} aria-label="选择日历">
      {listing.calendars.map(item => <button type="button" key={item.calendar_id} aria-pressed={item.calendar_id === selected && !editing} onClick={() => { setSelected(item.calendar_id); setEditing(null); }}>{item.label}</button>)}
      {listing.can_manage && !factory && <Button size="sm" variant="outline" onClick={() => edit(null, "factory")} disabled={!!editing}><Plus/>建立工厂日历</Button>}
      {listing.can_manage && <Button size="sm" variant="ghost" onClick={() => edit(null, "supplier")} disabled={!!editing}><Plus/>新增供应商日历</Button>}
    </nav>
    {editing ? <Editor editing={editing} setEditing={setEditing} busy={busy} onSave={save} onCancel={() => { setEditing(null); setError(""); }}/>
      : current ? <CalendarView calendar={current} canManage={listing.can_manage} onEdit={() => edit(current)} api={api}/>
        : <p className={styles.muted}>{listing.can_manage ? "还没有登记任何日历。建立工厂日历后，排期按它扣除节假日与停线。" : "还没有登记任何日历，请联系租户管理员登记。"}</p>}
  </section>;
}

function CalendarView({ calendar, canManage, onEdit, api }: { calendar: WorkCalendar; canManage: boolean; onEdit: () => void; api: Api }) {
  const year = new Date().getFullYear();
  const summaries = [year, year + 1].map(value => ({ year: value, ...yearSummary(calendar, value) }));
  return <div className={styles.view}>
    <dl className={styles.facts}>
      <div><dt>版本</dt><dd>第 {calendar.revision} 版 · {calendar.updated_by.name ?? "已停用成员"} · {when(calendar.updated_at)}</dd></div>
      <div><dt>本版原因</dt><dd>{calendar.reason}</dd></div>
      <div><dt>平常工作日</dt><dd>{weekdayText(calendar.working_weekdays)} · {calendar.timezone}</dd></div>
      <div><dt>扣除</dt><dd>{summaries.map(item => `${item.year} 年少 ${item.off} 个工作日${item.makeup ? `、调休上班 ${item.makeup} 天` : ""}`).join("；")}</dd></div>
    </dl>
    <EntryTable entries={calendar.entries}/>
    <div className={styles.actions}>{canManage && <Button size="sm" onClick={onEdit}>修改日历</Button>}</div>
    <TryIt calendar={calendar} api={api}/>
    <History key={`${calendar.calendar_id}:${calendar.revision}`} calendarId={calendar.calendar_id} api={api}/>
  </div>;
}

function EntryTable({ entries }: { entries: CalendarEntry[] }) {
  if (!entries.length) return <p className={styles.muted}>本日历没有登记假日或停线，按平常工作日计算。</p>;
  return <div className={styles.tableWrap}><table className={styles.table}>
    <thead><tr><th>类型</th><th>日期</th><th>说明</th></tr></thead>
    <tbody>{entries.map(entry => <tr key={`${entry.kind}:${entry.start}:${entry.end}:${entry.label}`}>
      <td><span className={styles.badge} data-kind={entry.kind}>{KIND_LABELS[entry.kind]}</span></td>
      <td className={styles.dates}>{rangeText(entry)}</td>
      <td>{entry.label}</td>
    </tr>)}</tbody>
  </table></div>;
}

function Editor({ editing, setEditing, busy, onSave, onCancel }: { editing: Editing; setEditing: (value: Editing) => void; busy: boolean; onSave: (event: FormEvent) => void; onCancel: () => void }) {
  const problems = useMemo(() => draftProblems(editing.draft), [editing.draft]);
  const update = (draft: Partial<Draft>) => setEditing({ ...editing, draft: { ...editing.draft, ...draft } });
  const setEntry = (index: number, patch: Partial<CalendarEntry>) => update({ entries: editing.draft.entries.map((entry, at) => {
    if (at !== index) return entry;
    const next = { ...entry, ...patch };
    // A one-day entry follows its start date until the end is chosen separately.
    if (patch.start && (!entry.end || entry.end === entry.start)) next.end = patch.start;
    return next;
  }) });
  const title = editing.calendarId ? "修改日历" : editing.kind === "factory" ? "建立工厂日历" : "新增供应商日历";
  const ready = !problems.length && editing.reason.trim() && (editing.kind === "factory" || editing.calendarId || editing.name.trim());
  return <form className={styles.editor} onSubmit={onSave} aria-label={title}>
    <h3>{title}</h3>
    {!editing.calendarId && editing.kind === "supplier" && <label className={styles.field}>供应商名称<input required maxLength={80} value={editing.name} onChange={event => setEditing({ ...editing, name: event.target.value })} placeholder="例如：某电芯供应商"/></label>}
    <fieldset className={styles.weekdays}><legend>平常工作日</legend>{WEEKDAYS.map((label, index) => {
      const day = index + 1, checked = editing.draft.working_weekdays.includes(day);
      return <label key={day}><input type="checkbox" checked={checked} onChange={() => update({ working_weekdays: checked ? editing.draft.working_weekdays.filter(value => value !== day) : [...editing.draft.working_weekdays, day] })}/>{label}</label>;
    })}</fieldset>
    <div className={styles.entries}>
      <div className={styles.entriesHead}><span>假日、调休与停线</span><Button type="button" size="sm" variant="outline" onClick={() => update({ entries: [...editing.draft.entries, blankEntry()] })}><Plus/>添加一条</Button></div>
      {!editing.draft.entries.length && <p className={styles.muted}>没有登记。春节停线可登记为一条“停线”，起止日期覆盖整个停线期。</p>}
      {editing.draft.entries.map((entry, index) => <div className={styles.entryRow} key={index}>
        <label>类型<select value={entry.kind} onChange={event => setEntry(index, { kind: event.target.value as EntryKind })}>{(Object.keys(KIND_LABELS) as EntryKind[]).map(kind => <option key={kind} value={kind}>{KIND_LABELS[kind]}</option>)}</select></label>
        <label>开始<input type="date" required value={entry.start} onChange={event => setEntry(index, { start: event.target.value })}/></label>
        <label>结束<input type="date" required value={entry.end} min={entry.start || undefined} onChange={event => setEntry(index, { end: event.target.value })}/></label>
        <label className={styles.grow}>说明<input required maxLength={80} value={entry.label} onChange={event => setEntry(index, { label: event.target.value })} placeholder="例如：2027 春节停线"/></label>
        <Button type="button" size="icon-sm" variant="ghost" aria-label={`删除第 ${index + 1} 条`} onClick={() => update({ entries: editing.draft.entries.filter((_, at) => at !== index) })}><Trash/></Button>
      </div>)}
    </div>
    {problems.length > 0 && <ul className={styles.problems} role="alert">{problems.map(problem => <li key={problem}>{problem}</li>)}</ul>}
    <label className={styles.field}>修改原因<input required maxLength={200} value={editing.reason} onChange={event => setEditing({ ...editing, reason: event.target.value })} placeholder="例如：登记 2027 年春节停线 4 周"/></label>
    <div className={styles.actions}><Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>取消</Button><Button type="submit" disabled={busy || !ready}>{busy ? "正在保存…" : "保存为新版本"}</Button></div>
  </form>;
}

function TryIt({ calendar, api }: { calendar: WorkCalendar; api: Api }) {
  const [at, setAt] = useState(""), [days, setDays] = useState("5"), [result, setResult] = useState(""), [failed, setFailed] = useState("");
  async function run(event: FormEvent) {
    event.preventDefault();
    setResult(""); setFailed("");
    try {
      const start = zonedInstant(at, calendar.timezone);
      const value = await api<{ result: string; basis_label: string }>(`v1/work-calendars/working-days?${new URLSearchParams({ at: start, days, calendar_id: calendar.calendar_id })}`);
      setResult(`${formatInstant(value.result, calendar.timezone)}（${value.basis_label}）`);
    } catch (failure) { setFailed((failure as Error).message); }
  }
  return <form className={styles.tryIt} onSubmit={run} aria-label="试算工作日">
    <span>试算</span>
    <label>从<input type="datetime-local" required value={at} onChange={event => setAt(event.target.value)} aria-describedby="work-calendar-zone"/></label>
    <label>加<input type="number" min={0} max={366} required value={days} onChange={event => setDays(event.target.value)}/>个工作日</label>
    <Button type="submit" size="sm" variant="outline" disabled={!at}>计算</Button>
    <small id="work-calendar-zone" className={styles.zone}>按 {calendar.timezone} 时间</small>
    {result && <output>{result}</output>}
    {failed && <span role="alert" className={styles.alert}>{failed}</span>}
  </form>;
}

function History({ calendarId, api }: { calendarId: string; api: Api }) {
  const [items, setItems] = useState<WorkCalendar[] | null>(null), [open, setOpen] = useState(false), [failed, setFailed] = useState("");
  async function toggle() {
    const next = !open; setOpen(next);
    if (next && !items) {
      try { setItems((await api<{ items: WorkCalendar[] }>(`v1/work-calendars/${calendarId}/versions`)).items); setFailed(""); }
      catch (failure) { setFailed((failure as Error).message); }
    }
  }
  return <div className={styles.history}>
    <Button type="button" size="sm" variant="ghost" aria-expanded={open} onClick={() => void toggle()}>{open ? "收起版本记录" : "查看版本记录"}</Button>
    {open && (failed ? <p role="alert" className={styles.alert}>{failed}</p> : !items ? <p role="status" className={styles.muted}>正在读取版本…</p>
      : <ol className={styles.versions}>{items.map(item => <li key={item.revision}><strong>第 {item.revision} 版</strong><span>{item.updated_by.name ?? "已停用成员"} · {when(item.updated_at)} · {sortEntries(item.entries).length} 条登记</span><span>{item.reason}</span></li>)}</ol>)}
  </div>;
}
