"use client";

import { useEffect, useState, type FormEvent } from "react";
import { browserApi } from "@/lib/browser-api";
import { newPersonalPreferences, type PersonalPreferences as Values, type PreferenceCandidate, type PreferenceOptions, type PreferenceView } from "@/lib/personal-preferences";
import { Button } from "./ui/button";
import styles from "./personal-preferences.module.css";

type Api = typeof browserApi;
const endpoint = "v1/personal/preferences";
const roles = [["product", "产品"], ["engineering", "研发"], ["quality", "质量"], ["manufacturing", "制造"], ["supply", "采购与供应"], ["management", "管理与协调"], ["other", "其他"]];

function FavoriteOptions({ kind, selected, candidates, onChange, api, disabled }: { kind: "category" | "project"; selected: string[]; candidates: PreferenceCandidate[]; onChange: (ids: string[]) => void; api: Api; disabled: boolean }) {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [items, setItems] = useState<PreferenceCandidate[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    const params = new URLSearchParams({ kind, query: search });
    if (cursor) params.set("cursor", cursor);
    api<PreferenceOptions>(`${endpoint}/options?${params}`).then(value => {
      if (!active) return;
      setItems(old => cursor ? [...old, ...value.items.filter(item => !old.some(row => row.id === item.id))] : value.items);
      setNext(value.next_cursor); setError(""); setLoading(false);
    }).catch(failure => { if (active) { setError(failure instanceof Error ? failure.message : "范围读取失败。"); setLoading(false); } });
    return () => { active = false; };
  }, [kind, search, cursor, api, attempt]);
  const choices = [...candidates.filter(item => item.kind === kind), ...items].filter((item, index, all) => all.findIndex(row => row.id === item.id) === index);
  const unknown = selected.filter(id => !choices.some(item => item.id === id));
  const label = kind === "category" ? "常用品类" : "常用项目";
  return <fieldset className={styles.favorites} disabled={disabled}>
    <legend>{label} <span>已选 {selected.length}/10</span></legend>
    <div className={styles.search}><label className={styles.searchLabel}>查找{label}<input value={query} maxLength={100} onChange={event => setQuery(event.target.value)} placeholder="按名称查找"/></label><Button type="button" variant="outline" size="sm" onClick={() => { setLoading(true); setCursor(null); setSearch(query.trim()); setAttempt(n => n + 1); }}>查找</Button></div>
    <div className={styles.options}>{choices.map(item => <label key={item.id}><input type="checkbox" checked={selected.includes(item.id)} disabled={!selected.includes(item.id) && selected.length >= 10} onChange={event => onChange(event.target.checked ? [...selected, item.id] : selected.filter(id => id !== item.id))}/><span>{item.label}</span></label>)}{unknown.map((id, index) => <label key={id}><input type="checkbox" checked onChange={() => onChange(selected.filter(item => item !== id))}/><span>已保存的{kind === "category" ? "品类" : "项目"} {index + 1}（暂不可用）</span></label>)}</div>
    {loading && <p role="status">正在读取可用范围…</p>}
    {error && <p role="alert">{error} <Button type="button" size="sm" variant="outline" onClick={() => { setLoading(true); setAttempt(n => n + 1); }}>重试</Button></p>}
    {!loading && !error && !choices.length && <p>没有找到可用范围。</p>}
    {next && !error && <Button type="button" size="sm" variant="ghost" disabled={loading} onClick={() => { setLoading(true); setCursor(next); }}>读取更多{kind === "category" ? "品类" : "项目"}</Button>}
  </fieldset>;
}

export function PersonalPreferences({ api = browserApi }: { api?: Api }) {
  const [reading, setReading] = useState<PreferenceView | null>(null);
  const [draft, setDraft] = useState<Values>(newPersonalPreferences);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  useEffect(() => {
    let active = true;
    api<PreferenceView>(endpoint).then(value => {
      if (active) { setReading(value); setDraft(value.preferences); setError(""); }
    }).catch(failure => { if (active) setError(failure instanceof Error ? failure.message : "个人偏好读取失败。"); });
    return () => { active = false; };
  }, [api, attempt]);
  async function save(values: Values) {
    if (!reading || busy) return;
    setBusy(true); setError(""); setNotice(""); setConflict(false);
    try {
      const value = await api<PreferenceView>(endpoint, { expected_revision: reading.revision, preferences: values });
      setReading(value); setDraft(value.preferences); setNotice("已保存，将用于之后的小Pai对话。");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "保存未完成，填写内容仍保留。");
      setConflict(!!failure && typeof failure === "object" && "code" in failure && failure.code === "VERSION_CONFLICT");
    } finally { setBusy(false); }
  }
  async function refreshKeepingDraft() {
    setBusy(true);
    try { setReading(await api<PreferenceView>(endpoint)); setConflict(false); setError(""); setNotice("已读取最新版本，你的填写已保留；可核对后保存。"); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "读取失败，填写内容仍保留。"); }
    finally { setBusy(false); }
  }
  function submit(event: FormEvent) { event.preventDefault(); void save(draft); }
  if (!reading) return <section className={styles.panel} aria-label="小Pai个人偏好"><h2>小Pai个人偏好</h2>{error ? <><p role="alert">{error}</p><Button variant="outline" onClick={() => setAttempt(n => n + 1)}>重新读取偏好</Button></> : <p role="status">正在读取个人偏好…</p>}</section>;
  return <section className={styles.panel} aria-label="小Pai个人偏好">
    <h2>小Pai个人偏好</h2><p className={styles.note}>仅自己可见，可随时修改或清空。</p>
    <form onSubmit={submit}>
      <fieldset className={styles.fields} disabled={busy}>
        <label>回答语言<select value={draft.answer_language} onChange={event => setDraft(old => ({ ...old, answer_language: event.target.value as Values["answer_language"] }))}><option value="auto">跟随当前提问</option><option value="zh-CN">简体中文</option><option value="zh-TW">繁體中文</option><option value="en">English</option><option value="ja">日本語</option></select></label>
        <label>回答详略<select value={draft.response_detail} onChange={event => setDraft(old => ({ ...old, response_detail: event.target.value as Values["response_detail"] }))}><option value="brief">简洁</option><option value="balanced">适中</option><option value="detailed">详细</option></select></label>
        <label>岗位<select value={draft.role ?? ""} onChange={event => setDraft(old => ({ ...old, role: (event.target.value || null) as Values["role"] }))}><option value="">未设置</option>{roles.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label>部门<input value={draft.department ?? ""} maxLength={80} placeholder="未设置" onChange={event => setDraft(old => ({ ...old, department: event.target.value || null }))}/></label>
      </fieldset>
      <p className={styles.note}>用于调整欢迎示例和摘要重点。</p>
      <FavoriteOptions kind="category" selected={draft.favorite_category_ids} candidates={reading.navigation_candidates} api={api} disabled={busy} onChange={ids => setDraft(old => ({ ...old, favorite_category_ids: ids }))}/>
      <FavoriteOptions kind="project" selected={draft.favorite_project_ids} candidates={reading.navigation_candidates} api={api} disabled={busy} onChange={ids => setDraft(old => ({ ...old, favorite_project_ids: ids }))}/>
      <p className={styles.note}>保存后可从欢迎页直接打开这些品类和项目；聊天范围可在会话中选择。</p>
      {error && <p role="alert">{error} 填写内容仍保留。</p>}
      {conflict && <Button type="button" variant="outline" disabled={busy} onClick={() => void refreshKeepingDraft()}>读取最新设置并保留填写</Button>}
      {notice && <p role="status">{notice}</p>}
      <div className={styles.actions}><Button type="submit" disabled={busy || conflict}>{busy ? "正在保存…" : "保存偏好"}</Button><Button type="button" variant="outline" disabled={busy || conflict} onClick={() => void save(newPersonalPreferences())}>清空偏好</Button></div>
    </form>
    {!!reading.navigation_candidates.length && <nav className={styles.saved} aria-label="常用范围候选"><h3>已保存的常用范围</h3>{reading.navigation_candidates.map(item => <a key={`${item.kind}:${item.id}`} href={item.href}>{item.label}</a>)}</nav>}
    {!!reading.role_defaults.welcome_examples.length && <div className={styles.saved}><h3>已选岗位的欢迎示例</h3><ul>{reading.role_defaults.welcome_examples.map(example => <li key={example}>{example}</li>)}</ul><p className={styles.note}>摘要建议：{reading.role_defaults.summary_sections.join(" · ")}</p></div>}
  </section>;
}
