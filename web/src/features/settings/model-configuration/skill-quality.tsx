"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { breachLabels, percent, ruleSummary, sampleReasons, sampleShortfall, type QualityView } from "@/features/settings/lib/skill-quality";
import type { WorkspaceTransport } from "@/lib/workspace-api";

// Read-only T0 value metrics and P41 step-back state for one skill (D117, D37 ⑧).
export function SkillQualityPanel({ api, skill }: { api: WorkspaceTransport; skill: string }) {
  const [view, setView] = useState<QualityView | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(true), [epoch, setEpoch] = useState(0);
  useEffect(() => {
    let alive = true;
    api<QualityView>(`v1/agent-skill-quality?skill_key=${encodeURIComponent(skill)}`).then(
      result => { if (alive) { setView(result); setError(""); } },
      failure => { if (alive) { setView(null); setError((failure as Error).message); } },
    ).finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [api, skill, epoch]);
  return <section aria-label="运行指标与自动降级" className="space-y-3 rounded-lg border border-border p-3 text-sm">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-medium">运行指标与自动降级</h3><Button variant="outline" disabled={busy} onClick={() => { setBusy(true); setEpoch(value => value + 1); }}>刷新指标</Button></div>
    <p className="text-muted-foreground">按“租户 × 技能包 × 模型版本”从运行回执和之后的人工动作确定性计算，不经模型判断。超过阈值时降回一次确认，只有重新审阅后具名批准才恢复自动写入。</p>
    {busy && <p role="status">正在读取运行指标…</p>}
    {error && <p role="alert" className="break-words text-destructive">{error}</p>}
    {view && <SkillQualityBody view={view} />}
  </section>;
}

export function SkillQualityBody({ view }: { view: QualityView }) {
  const current = view.current;
  const shortfall = current ? sampleShortfall(current.spot_check) : [];
  return <>
    {!current && <p className="text-muted-foreground">当前没有有效资格，下面只列历史版本的价值指标。</p>}
    {current && <div className="space-y-2 rounded-lg bg-muted/40 p-3">
      <p className="break-all">当前资格：技能 {current.skill_version} · 模型 {current.model_version} · 自 {new Date(current.since).toLocaleString("zh-CN")} 起计</p>
      {current.breach ? <p role="alert" className="font-medium text-destructive">{breachLabels[current.breach] ?? current.breach}，自动写入已降回一次确认，待重新审阅。</p> : <p>未触发自动降级。</p>}
      <ul className="space-y-1">{current.rules.map(rule => <li key={rule.key} className="break-words">{ruleSummary(rule)}{rule.reason && <span className="block text-muted-foreground">{rule.reason}</span>}</li>)}</ul>
      {(current.basis.withdrawal.length > 0 || current.basis.modification.length > 0) && <details><summary className="cursor-pointer">依据运行</summary>
        <p className="mt-2 break-all">被撤回：{current.basis.withdrawal.join("、") || "无"}</p>
        <p className="break-all">之后被人修改：{current.basis.modification.join("、") || "无"}</p>
      </details>}
      <details><summary className="cursor-pointer">抽检样本（{current.spot_check.runs.length} 次）</summary>
        <p className="mt-2 text-muted-foreground">{current.spot_check.rule}</p>
        {shortfall.length > 0 && <p role="alert" className="text-destructive">以下周抽样不足：{shortfall.join("、")}</p>}
        <ul className="mt-2 space-y-1">{current.spot_check.weeks.map(week => <li key={week.week_start}>{week.week_start} 起一周：T0 运行 {week.runs} 次，抽中 {week.sampled} 次（至少 {week.required} 次）</li>)}</ul>
        <ul className="mt-2 space-y-1">{current.spot_check.runs.map(run => <li key={run.run_id} className="break-all">{run.run_id} · {new Date(run.first_at).toLocaleString("zh-CN")} · {sampleReasons[run.reason]}</li>)}</ul>
      </details>
    </div>}
    <div className="space-y-2">
      <h4 className="font-medium">价值指标（全部历史）</h4>
      {!view.groups.length && <p className="text-muted-foreground">尚无自动写入记录。</p>}
      <div className="overflow-x-auto"><table className="w-full min-w-[36rem] text-left text-xs"><thead><tr className="border-b border-border"><th className="py-1 pr-2 font-medium">技能 · 模型</th><th className="py-1 pr-2 font-medium">运行 / 写入</th><th className="py-1 pr-2 font-medium">撤回率</th><th className="py-1 pr-2 font-medium">人工修改率</th><th className="py-1 pr-2 font-medium">草稿保留率</th><th className="py-1 font-medium">原样保留率</th></tr></thead>
        <tbody>{view.groups.map(group => <tr key={`${group.skill_version}:${group.model_version}`} className="border-b border-border"><td className="break-all py-1 pr-2">{group.skill_version} · {group.model_version}</td><td className="py-1 pr-2">{group.runs_total} / {group.writes_total}</td><td className="py-1 pr-2">{percent(group.metrics?.withdrawal_rate)}</td><td className="py-1 pr-2">{percent(group.metrics?.modification_rate)}</td><td className="py-1 pr-2">{percent(group.metrics?.retention_rate)}</td><td className="py-1">{percent(group.metrics?.untouched_rate)}</td></tr>)}</tbody></table></div>
      <details><summary className="cursor-pointer">指标口径</summary><ul className="mt-2 space-y-1 text-muted-foreground">{Object.entries(view.definitions).map(([key, text]) => <li key={key}>{text}</li>)}</ul></details>
    </div>
  </>;
}
