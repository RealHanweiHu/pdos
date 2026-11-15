"use client";

import { useEffect, useState } from "react";
import { browserApi } from "@/lib/browser-api";
import { requestKey, type TenantPolicy, type TenantStatistics } from "@/lib/personal-memory";
import { Button } from "../../components/ui/button";
import styles from "./personal-memory.module.css";

type Api = typeof browserApi;
const path = "v1/personal/memory-policy";

/** 租户记忆策略（P86 第 9 项；团队备忘复核期限 P87 第 4 项）：管理员只看启用状态和条目数量，看不到任何条目内容。 */
export function MemoryPolicySettings({ api = browserApi }: { api?: Api }) {
  const [value, setValue] = useState<TenantStatistics | null>(null);
  const [draft, setDraft] = useState<Pick<TenantPolicy, "notes_enabled" | "proposals_enabled" | "work_state_idle_days" | "scope_note_review_days"> | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let live = true;
    api<TenantStatistics>(`${path}/statistics`).then(result => {
      if (!live) return;
      setValue(result); setDraft({ notes_enabled: result.policy.notes_enabled, proposals_enabled: result.policy.proposals_enabled, work_state_idle_days: result.policy.work_state_idle_days, scope_note_review_days: result.policy.scope_note_review_days }); setError("");
    }).catch(failure => { if (live) setError(failure instanceof Error ? failure.message : "记忆策略读取失败。"); });
    return () => { live = false; };
  }, [api, attempt]);
  async function save() {
    if (!value || !draft) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await api<TenantPolicy>(path, { expected_revision: value.policy.revision, request_key: requestKey(), ...draft });
      setNotice("已保存，之后的运行按新策略办理。"); setAttempt(n => n + 1);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "保存未完成。"); }
    finally { setBusy(false); }
  }
  if (!value || !draft) return <section className={styles.panel} aria-label="租户记忆策略"><h2>租户记忆策略</h2>{error ? <><p role="alert">{error}</p><Button size="sm" variant="outline" onClick={() => setAttempt(n => n + 1)}>重新读取</Button></> : <p role="status">正在读取记忆策略…</p>}</section>;
  return <section className={styles.panel} aria-label="租户记忆策略">
    <div className={styles.heading}><h2>租户记忆策略</h2><span className={styles.meta}>第 {value.policy.revision} 版{value.policy.default ? "（默认）" : ""}</span></div>
    <p className={styles.note}>{value.note} 当前 {value.owners_with_notes} 人共有 {value.active_notes} 条有效记忆。</p>
    {notice && <p role="status" className={styles.notice}>{notice}</p>}
    <fieldset className={styles.fields} disabled={busy}>
      <legend className="sr-only">记忆开关</legend>
      <div className={styles.setting}><label><input type="checkbox" checked={draft.notes_enabled} onChange={event => setDraft(old => old && { ...old, notes_enabled: event.target.checked })}/>允许成员使用自由文本记忆条目</label><p className={styles.meta}>关闭后条目不再带入对话、不能新增；成员仍可查看和删除自己的条目。</p></div>
      <div className={styles.setting}><label><input type="checkbox" checked={draft.proposals_enabled} onChange={event => setDraft(old => old && { ...old, proposals_enabled: event.target.checked })}/>允许小Pai在成员多次纠正后主动提议</label><p className={styles.meta}>成员说“记住……”时的提议不受这项影响；所有提议都须本人确认才写入。</p></div>
      <label className={styles.dateLabel}>工作状态闲置多少天后不再自动带入<input type="number" min={1} max={365} step={1} value={draft.work_state_idle_days} onChange={event => setDraft(old => old && { ...old, work_state_idle_days: Math.max(1, Math.min(365, Number(event.target.value) || 1)) })}/></label>
      <div className={styles.setting}><label className={styles.dateLabel}>团队备忘复核期限（天）<input type="number" min={1} max={365} step={1} value={draft.scope_note_review_days} onChange={event => setDraft(old => old && { ...old, scope_note_review_days: Math.max(1, Math.min(365, Number(event.target.value) || 1)) })}/></label><p className={styles.meta}>缺省 90 天。之后新记或修改的备忘按这个期限起算；已有备忘保持原来的复核日期。到期标“待复核”，照常带入但降为背景。</p></div>
    </fieldset>
    <p className={styles.meta}>情景向量化：{value.episode_vectors.enabled ? "已启用（当前 Embedding 配置勾选了“本人会话记录”）" : "未启用"}。在“模型配置 › Embedding”里勾选或取消“本人会话记录”，每次出站都记回执。</p>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    <div className={styles.actions}><Button type="button" size="sm" disabled={busy} onClick={() => void save()}>{busy ? "正在保存…" : "保存策略"}</Button></div>
  </section>;
}
