"use client";

/* 程序性汇总与修订候选审核（记忆 M3, P88 第 3、4 项）：管理员逐条采纳或驳回。采纳只生成草稿版本，
   不激活——提示词仍须 A/B 通过与具名评审，技能包仍须 golden-case 与具名启用、资格重审。
   系统规则只能停用或恢复，不能改写。 */
import { useEffect, useState } from "react";
import { browserApi } from "@/lib/browser-api";
import { Button } from "../../components/ui/button";
import styles from "./personal-memory.module.css";

type Api = typeof browserApi;
const base = "v1/personal/memory-policy";

export type RevisionItem = {
  candidate_id: string;
  target: { kind: "skill_package" | "prompt"; key: string; version: string };
  reason: string; reason_label: string; signal_count: number; threshold: number;
  signal_sources: Record<string, number>; sample_run_ids: string[];
  status: "open" | "adopted" | "rejected";
  draft: { draft_version?: string; base_version?: string; activation?: string; prepare_with?: string } | null;
  window: { start: string; end: string };
};
export type RevisionPage = {
  items: RevisionItem[];
  summary: { target: RevisionItem["target"]; reason: string; reason_label: string; signal_count: number; run_count: number; reaches_threshold: boolean }[];
  threshold: number; window_days: number; never_changed: string[]; tool_errors: string; note: string;
};
export type RulesPage = {
  skill: { key: string; state: string; note: string };
  rules: { key: string; label: string; enabled: boolean; calls_model: boolean }[];
};

const targetName = (target: RevisionItem["target"]) => `${target.kind === "prompt" ? "提示词" : "技能包"} ${target.key} ${target.version}`;
export const statusLabels = { open: "待审核", adopted: "已采纳（草稿待准备）", rejected: "已驳回" } as const;

export function SkillRevisions({ api = browserApi }: { api?: Api }) {
  const [page, setPage] = useState<RevisionPage | null>(null);
  const [rules, setRules] = useState<RulesPage | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    Promise.all([api<RevisionPage>(`${base}/skill-revisions`), api<RulesPage>(`${base}/system-rules`)]).then(([revisions, preset]) => {
      if (live) { setPage(revisions); setRules(preset); setError(""); }
    }).catch(failure => { if (live) setError(failure instanceof Error ? failure.message : "修订候选读取失败。"); });
    return () => { live = false; };
  }, [api, attempt]);
  async function act(key: string, path: string, body: Record<string, unknown>) {
    setBusy(key); setError("");
    try { await api(path, { request_key: globalThis.crypto.randomUUID(), ...body }); setAttempt(n => n + 1); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "没有办理成功。"); }
    finally { setBusy(""); }
  }
  if (!page || !rules) return <section className={styles.panel} aria-label="修订候选审核"><h2>修订候选审核</h2>{error ? <><p role="alert">{error}</p><Button size="sm" variant="outline" onClick={() => setAttempt(n => n + 1)}>重新读取</Button></> : <p role="status">正在读取修订候选…</p>}</section>;
  return <section className={styles.panel} aria-label="修订候选审核">
    <div className={styles.heading}><h2>修订候选审核</h2><span className={styles.meta}>近 {page.window_days} 天 · 同类达到 {page.threshold} 次生成候选</span></div>
    <p className={styles.note}>{page.note} 永远不改：{page.never_changed.join("、")}。{page.tool_errors}</p>
    {page.items.length === 0 && <p className={styles.meta}>暂无修订候选。</p>}
    {page.items.map(item => <div key={item.candidate_id} className={styles.setting}>
      <p><strong>{targetName(item.target)}</strong> · {item.reason_label} · {item.signal_count} 次（{Object.entries(item.signal_sources).filter(([, n]) => n).map(([kind, n]) => `${kind === "run_feedback" ? "运行反馈" : kind === "retrieval_feedback" ? "排除来源" : kind} ${n}`).join("，")}）</p>
      <p className={styles.meta}>{statusLabels[item.status]} · 样例运行 {item.sample_run_ids.length} 个{item.draft?.draft_version ? ` · 草稿 ${item.draft.base_version} → ${item.draft.draft_version}；准备：${item.draft.prepare_with}；激活：${item.draft.activation}` : ""}</p>
      {item.status === "open" && <div className={styles.actions}>
        <Button size="sm" disabled={!!busy} onClick={() => void act(item.candidate_id, `${base}/skill-revisions/${item.candidate_id}/decision`, { decision: "adopt" })}>采纳为草稿</Button>
        <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => void act(item.candidate_id, `${base}/skill-revisions/${item.candidate_id}/decision`, { decision: "reject" })}>驳回</Button>
      </div>}
    </div>)}
    <h3>纠正汇总</h3>
    {page.summary.length === 0 ? <p className={styles.meta}>近 {page.window_days} 天没有纠正信号。</p> : <ul className={styles.meta}>
      {page.summary.map(row => <li key={`${row.target.kind}:${row.target.key}:${row.target.version}:${row.reason}`}>{targetName(row.target)} · {row.reason_label}：{row.signal_count} 次，{row.run_count} 个运行{row.reaches_threshold ? "（已达阈值）" : ""}</li>)}
    </ul>}
    <h3>系统规则</h3>
    <p className={styles.note}>经验沉淀：{rules.skill.note}</p>
    {rules.rules.map(rule => <div key={rule.key} className={styles.setting}>
      <label><input type="checkbox" checked={rule.enabled} disabled={!!busy} onChange={event => void act(rule.key, `${base}/system-rules/${rule.key}`, { enabled: event.target.checked })}/>{rule.label}</label>
      <p className={styles.meta}>{rule.calls_model ? "起草的只是候选，进负责人“我的工作”。" : "不调用模型，确定性标记。"}</p>
    </div>)}
    {error && <p role="alert" className={styles.error}>{error}</p>}
  </section>;
}
