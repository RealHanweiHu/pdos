import { rawSpec, type DefinitionCandidate } from "./contracts";

export function CandidateReading({ candidate }: { candidate: DefinitionCandidate | null }) {
  if (!candidate) return <p role="status" className="text-sm text-muted-foreground">尚未取得当前来源重核的定义预览。</p>;
  return <section aria-label="固定定义候选" className="space-y-3 rounded-lg border p-4 text-sm">
    <h2 className="font-semibold">{candidate.payload.title} · 内部定义草稿预览</h2>
    <p>{candidate.effect}</p>
    <p>用途：{candidate.payload.purpose} · 来源包 v{candidate.research_revision} · 型号 v{candidate.expected_product_revision}</p>
    <p className="break-all font-mono text-xs text-muted-foreground">固定候选 {candidate.digest}</p>
    {candidate.payload.specs.map(spec => <article key={spec.key} className="rounded-lg bg-muted/40 p-3">
      <strong>{spec.key} · {spec.parameter}</strong><p className="font-mono">{spec.availability === "known" ? rawSpec({ ...spec, applicability: null }) : spec.availability === "conflicted" ? "冲突，目标值未裁决" : "未知，保留原始候选"}</p>
      <p>状态：待确认 · 原因：{spec.reason}</p><p>方法：{spec.method ?? "未知"} · 条件：{spec.test_conditions.join("；") || "未知"}</p>
    </article>)}
    {!!candidate.payload.requirements.length && <div><h3 className="font-medium">要求候选</h3><ul>{candidate.payload.requirements.map(value => <li key={value}>{value}</li>)}</ul></div>}
    {!!candidate.payload.constraints.length && <div><h3 className="font-medium">约束与适用范围</h3><ul>{candidate.payload.constraints.map(value => <li key={value}>{value}</li>)}</ul></div>}
    {!!candidate.payload.unknowns.length && <div><h3 className="font-medium">未知与剩余缺项</h3><ul className="list-inside list-disc">{candidate.payload.unknowns.map(value => <li key={value}>{value}</li>)}</ul></div>}
    {!!candidate.conflicts.length && <div><h3 className="font-medium">并列冲突仍保留</h3><ul>{candidate.conflicts.map(conflict => <li key={conflict.key}>{conflict.key} · {conflict.reasons.join("、")} · {conflict.observation_ids.length} 条证据</li>)}</ul></div>}
    {candidate.provenance.map(entry => <details key={entry.key}><summary className="cursor-pointer py-2">{entry.key} · 选择依据与原文</summary>
      <p>办理人 {entry.actor_id} · {entry.reason} · {entry.maturity === "accepted_requirement" ? "已接受需求记录重核" : "候选"}</p>
      {entry.observations.map(stored => <blockquote key={stored.observation.id} className="my-2 whitespace-pre-wrap break-words border-l-2 pl-3">{stored.observation.raw_text}</blockquote>)}
    </details>)}
  </section>;
}
