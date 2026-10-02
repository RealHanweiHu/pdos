"use client";

import type { Criterion } from "./product-matrix-coverage";

export type ScoringPolicy = {
  formula_version: "product-coverage-weighted.v1";
  policy_key: string; policy_version: number; title: string; basis: string;
  weights: { criterion_key: string; weight: string; basis: string }[];
};
type Score = { score: string | null; lower_bound: string; upper_bound: string; unknown_weight: string; contributions: { criterion_key: string; status: string; weight: string; points: string | null }[] };
export type CoverageScoring = { policy: ScoringPolicy; policy_digest: string; formula: string; scope: string; products: (Score & { product_id: string })[]; selected_portfolio: Score };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

export function ScoringEditor({ policy, criteria, onChange }: { policy: ScoringPolicy | null; criteria: Criterion[]; onChange: (policy: ScoringPolicy | null) => void }) {
  return <section className="space-y-3 rounded-md border p-3">
    <label className="text-sm"><input type="checkbox" checked={!!policy} onChange={event => onChange(event.target.checked ? { formula_version: "product-coverage-weighted.v1", policy_key: "", policy_version: 1, title: "", basis: "", weights: [] } : null)}/> 同时计算需求覆盖分</label>
    {policy && <><p className="text-sm text-muted-foreground">请明确本次评分政策及每项权重，合计必须为1。没有默认商业权重；未知项只给区间，不补分。评分只用于当前所选需求，不代表收入、利润或立项优先级。</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">政策编号<input required pattern={"[a-zA-Z0-9_.:\\-]+"} maxLength={128} className={field} value={policy.policy_key} onChange={event => onChange({ ...policy, policy_key: event.target.value })}/></label>
        <label className="text-sm">政策版本<input required type="number" min={1} step={1} className={field} value={policy.policy_version} onChange={event => onChange({ ...policy, policy_version: Number(event.target.value) })}/></label>
        <label className="text-sm">政策名称<input required maxLength={2048} className={field} value={policy.title} onChange={event => onChange({ ...policy, title: event.target.value })}/></label>
        <label className="text-sm">适用范围与政策依据<textarea required maxLength={2048} className={field} value={policy.basis} onChange={event => onChange({ ...policy, basis: event.target.value })}/></label>
      </div>
      {criteria.map((criterion, index) => {
        const row = policy.weights.find(item => item.criterion_key === criterion.key) ?? { criterion_key: criterion.key, weight: "", basis: "" };
        const update = (patch: Partial<typeof row>) => onChange({ ...policy, weights: criteria.map(item => item.key === criterion.key ? { ...row, ...patch } : policy.weights.find(weight => weight.criterion_key === item.key) ?? { criterion_key: item.key, weight: "", basis: "" }) });
        return <div key={criterion.key} className="grid gap-3 sm:grid-cols-2"><label className="text-sm">判据 {index + 1} 权重（大于0，至1）<input required inputMode="decimal" className={field} value={row.weight} onChange={event => update({ weight: event.target.value })}/></label><label className="text-sm">判据 {index + 1} 权重依据<textarea required maxLength={2048} className={field} value={row.basis} onChange={event => update({ basis: event.target.value })}/></label></div>;
      })}
      <p className="text-xs text-muted-foreground">修改已保存政策的权重或依据时，请增加政策版本。判据、来源快照和政策会随对照版本一起保存，可按原输入复算。</p>
    </>}
  </section>;
}

export function ScoringResult({ value, name }: { value: CoverageScoring; name: (id: string) => string }) {
  return <section className="space-y-3 rounded-md border p-3"><h6 className="font-semibold">需求覆盖评分 · {value.policy.title} v{value.policy.policy_version}</h6><p className="text-sm">{value.scope}</p><p className="text-xs">{value.formula}</p><p className="text-sm">政策依据：{value.policy.basis}</p>
    {[...value.products.map(product => ({ label: name(product.product_id), value: product })), { label: "所选产品组合（每条需求仅计一次）", value: value.selected_portfolio }].map(row => <article key={row.label} className="space-y-1 rounded-md bg-muted p-3 text-sm"><p className="font-medium">{row.label}：{row.value.score === null ? `待补资料 · 可能区间 ${row.value.lower_bound}～${row.value.upper_bound} / 100` : `${row.value.score} / 100`}</p><details><summary className="cursor-pointer">逐项权重与得分</summary>{row.value.contributions.map(item => <p key={item.criterion_key}>{item.criterion_key} · 权重 {item.weight} · {item.points === null ? "未知，未计确定分" : `${item.points} 分`} · {value.policy.weights.find(weight => weight.criterion_key === item.criterion_key)?.basis}</p>)}</details></article>)}
    <p className="break-all text-xs text-muted-foreground">{value.policy.formula_version} · 政策摘要 {value.policy_digest}</p>
  </section>;
}
