"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { skillTitle } from "@/lib/agent-skills";
import { breachLabels, criticalKinds, holdSummary, percent, ruleSummary, sampleReasons, sampleShortfall, spotOutcomes, unmarkedSample, type CriticalKind, type QualityHold, type QualityView, type SpotOutcome } from "@/features/settings/lib/skill-quality";
import { proofClockCurrent } from "@/lib/proof-clock";
import type { WorkspaceTransport } from "@/lib/workspace-api";

const fieldClass = "w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm";

// Open holds on current qualifications (P110 Q4). Administrators only: anyone else
// is refused by the server and simply sees nothing.
export function useQualityHolds(api: WorkspaceTransport, enabled: boolean, epoch = 0) {
  const [holds, setHolds] = useState<QualityHold[] | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    api<{ holds: QualityHold[] }>("v1/agent-skill-quality/holds").then(
      result => { if (alive) setHolds(result.holds); },
      () => { if (alive) setHolds(null); },
    );
    return () => { alive = false; };
  }, [api, enabled, epoch]);
  return enabled ? holds : null;
}

export function SkillQualityHoldsBanner({ holds }: { holds: QualityHold[] | null }) {
  if (!holds?.length) return null;
  return <section role="alert" aria-label="待复审的技能资格" className="space-y-2 rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-sm">
    <h3 className="font-medium text-destructive">待复审 · {holds.length} 项自动执行资格已降回一次确认</h3>
    <ul className="space-y-1">{holds.map(hold => <li key={hold.id} className="break-words"><span className="font-medium">{skillTitle(hold.skill_key)}</span> · {hold.skill_version} / {hold.model_version}<span className="block">{holdSummary(hold)} · {new Date(hold.created_at).toLocaleString("zh-CN")}</span>{hold.basis_run_ids.length > 0 && <span className="block break-all text-muted-foreground">依据运行：{hold.basis_run_ids.join("、")}</span>}</li>)}</ul>
    <p className="text-muted-foreground">恢复须在降级之后重新登记本人审阅，再由资格负责人或租户管理员具名批准；时间流逝不会自动恢复。</p>
  </section>;
}

type Preview = { command: { operation: string; payload: Record<string, unknown> } & Record<string, unknown>; expires_at: string | null; review: Record<string, unknown> & { effect: string } };

// Read-only T0 value metrics, P41 step-back state and the P42 spot-check queue (D117, D37 ⑧).
export function SkillQualityPanel({ api, skill, categoryId, categoryRevision, onChanged }: { api: WorkspaceTransport; skill: string; categoryId: string; categoryRevision: number; onChanged?: () => void }) {
  const [view, setView] = useState<QualityView | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(true), [epoch, setEpoch] = useState(0);
  useEffect(() => {
    let alive = true;
    api<QualityView>(`v1/agent-skill-quality?skill_key=${encodeURIComponent(skill)}`).then(
      result => { if (alive) { setView(result); setError(""); } },
      failure => { if (alive) { setView(null); setError((failure as Error).message); } },
    ).finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [api, skill, epoch]);
  const refresh = () => { setBusy(true); setEpoch(value => value + 1); onChanged?.(); };
  return <section aria-label="运行指标与自动降级" className="space-y-3 rounded-lg border border-border p-3 text-sm">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-medium">运行指标与自动降级</h3><Button variant="outline" disabled={busy} onClick={refresh}>刷新指标</Button></div>
    <p className="text-muted-foreground">按“租户 × 技能包 × 模型版本”从运行回执和之后的人工动作确定性计算，不经模型判断。超过阈值或抽检发现关键错误时降回一次确认，只有重新审阅后具名批准才恢复自动写入。</p>
    {busy && <p role="status">正在读取运行指标…</p>}
    {error && <p role="alert" className="break-words text-destructive">{error}</p>}
    {view && <SkillQualityBody view={view} />}
    {view?.current && <SpotCheckQueue api={api} view={view} categoryId={categoryId} categoryRevision={categoryRevision} onRecorded={refresh} />}
  </section>;
}

function SpotCheckQueue({ api, view, categoryId, categoryRevision, onRecorded }: { api: WorkspaceTransport; view: QualityView; categoryId: string; categoryRevision: number; onRecorded: () => void }) {
  const current = view.current!;
  const queue = unmarkedSample(current.spot_check, current.spot_checks);
  const [run, setRun] = useState(""), [outcome, setOutcome] = useState<SpotOutcome>("correct"), [kinds, setKinds] = useState<CriticalKind[]>([]), [note, setNote] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const focus = useRef<HTMLElement>(null);
  useEffect(() => { if (preview) focus.current?.focus(); }, [preview]);
  async function act(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); } catch (failure) { setError((failure as Error).message); } finally { setBusy(false); }
  }
  const ready = !!run && (outcome !== "critical_error" || kinds.length > 0) && (outcome === "correct" || !!note.trim());
  return <section aria-label="抽检复核队列" className="space-y-3 rounded-lg border border-border p-3">
    <h4 className="font-medium">抽检复核队列 · 待标注 {queue.length} 次</h4>
    <p className="text-muted-foreground">当前租户管理员本人标注抽中的运行。普通错误计入人工修改率；关键错误立即暂停该资格。标注人记入回执，不改变已写入的内容。</p>
    {error && <p role="alert" className="break-words text-destructive">{error}</p>}{notice && <p role="status" className="break-all">{notice}</p>}
    {current.spot_checks.length > 0 && <details><summary className="cursor-pointer">已标注 {current.spot_checks.length} 次</summary><ul className="mt-2 space-y-1">{current.spot_checks.map(mark => <li key={mark.id} className="break-words"><span className="break-all">{mark.run_id}</span> · {spotOutcomes[mark.outcome]} · {mark.reviewed_by_name}{mark.critical_kinds.length > 0 && <span className="block">{mark.critical_kinds.map(kind => criticalKinds[kind]).join("；")}</span>}{mark.note && <span className="block text-muted-foreground">{mark.note}</span>}</li>)}</ul></details>}
    {queue.length > 0 && <fieldset disabled={busy || !!preview} className="space-y-3">
      <label className="block space-y-1"><span>抽中的运行</span><select className={fieldClass} value={run} onChange={event => setRun(event.target.value)}><option value="">请选择运行</option>{queue.map(item => <option key={item.run_id} value={item.run_id}>{new Date(item.first_at).toLocaleString("zh-CN")} · {sampleReasons[item.reason]} · {item.run_id.slice(0, 8)}</option>)}</select></label>
      <label className="block space-y-1"><span>抽检结论</span><select className={fieldClass} value={outcome} onChange={event => { setOutcome(event.target.value as SpotOutcome); setKinds([]); }}>{Object.entries(spotOutcomes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      {outcome === "critical_error" && <fieldset className="space-y-1"><legend>关键错误类别（至少一类）</legend>{(Object.keys(criticalKinds) as CriticalKind[]).map(kind => <label key={kind} className="flex items-start gap-2"><input type="checkbox" className="mt-1" checked={kinds.includes(kind)} onChange={event => setKinds(old => event.target.checked ? [...old, kind] : old.filter(value => value !== kind))} /><span>{criticalKinds[kind]}</span></label>)}</fieldset>}
      {outcome !== "correct" && <label className="block space-y-1"><span>具体问题</span><textarea className={fieldClass} rows={2} maxLength={2000} value={note} onChange={event => setNote(event.target.value)} /></label>}
      <Button disabled={!ready} onClick={() => void act(async () => {
        const result = await api<Preview>("v1/commands/preview", { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), category_id: categoryId, product_id: null, operation: "ai.skill.spot_check.record", expected_revision: categoryRevision, source_read_set: [], payload: { skill_key: view.skill_key, run_id: run, outcome, critical_kinds: kinds, note } });
        setPreview(result); setNotice("");
      })}>预览抽检标注</Button>
    </fieldset>}
    {!queue.length && <p className="text-muted-foreground">当前样本已全部标注。</p>}
    {preview && <section ref={focus} tabIndex={-1} aria-label="确认抽检标注" className="space-y-2 rounded-lg border border-primary/40 p-3">
      <p className="font-medium">确认抽检标注 · {String(preview.review.outcome_label)}</p>
      <p className="break-all">运行 {String(preview.review.run_id)} · {String(preview.review.sample_reason)}</p>
      {Array.isArray(preview.review.critical_kinds) && preview.review.critical_kinds.length > 0 && <p>{(preview.review.critical_kinds as string[]).join("；")}</p>}
      <p className={preview.review.outcome === "critical_error" ? "font-medium text-destructive" : undefined}>{preview.review.effect}</p>
      <div className="flex flex-wrap gap-2"><Button disabled={busy || !proofClockCurrent("T1", preview.expires_at)} onClick={() => void act(async () => {
        const receipt = await api<{ id: string }>("v1/commands", preview.command);
        setPreview(null); setRun(""); setOutcome("correct"); setKinds([]); setNote("");
        setNotice(`抽检标注已保存 · 回执 ${receipt.id}`); onRecorded();
      })}>确认保存标注</Button><Button variant="outline" disabled={busy} onClick={() => setPreview(null)}>返回</Button></div>
    </section>}
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
