import { differenceLabels, specStateLabels, type ProposalDocument } from "@/components/product-work/proposal-types";

export type CandidateCitation = { reference_id: string; label: string; href: string };

export function CandidateSources({ ids, citations }: { ids: string[]; citations: CandidateCitation[] }) {
  return <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">{ids.map(id => {
    const source = citations.find(c => c.reference_id === id);
    return source ? <a key={id} href={source.href} target="_blank" rel="noreferrer" className="text-primary underline">{source.label}</a> : <span key={id}>{id === "brief" ? "你的需求片段" : id.startsWith("parameter:") ? "品类规格字典" : id.startsWith("category:") ? "品类资料" : "来源待核对"}</span>;
  })}</div>;
}

export function ProposalCandidatePreview({ document: d, citations }: { document: ProposalDocument; citations: CandidateCitation[] }) {
  return <div className="space-y-4">
    <p className="whitespace-pre-wrap text-sm leading-7">{d.narrative}</p>
    <section className="space-y-2"><h4 className="text-sm font-medium">关键规格</h4>{d.specifications.map(s => <article key={s.id} className="rounded-lg border p-3 text-sm"><h5>{s.label} · {s.value || "未知"} {s.unit} · {specStateLabels[s.state]}</h5><p className="mt-1 text-xs text-muted-foreground">{s.conditions || "测试条件待确认"}</p><CandidateSources ids={s.source_ids} citations={citations}/></article>)}</section>
    {d.options.map(o => <article key={o.key} className="rounded-lg border p-3 text-sm"><h4 className="font-medium">{o.key} · {o.name}</h4><p className="mt-2">{o.audience} · {o.positioning}</p><p className="mt-2">使用路径：{o.use_path || "待补充"}</p><p>价格带：{o.price_band || "未知"}</p><p className="mt-2">取舍：{o.tradeoffs || "待补充"}</p><CandidateSources ids={o.source_ids} citations={citations}/></article>)}
    {d.differences.map((diff, i) => <article key={i} className="rounded-lg border p-3 text-sm"><h4>{differenceLabels[diff.area]}差异</h4><p>{diff.baseline || "原值未知"} → {diff.proposed || "目标未知"}</p><p className="mt-2">{diff.impact}</p><CandidateSources ids={diff.source_ids} citations={citations}/></article>)}
    {d.competitors?.map((c, i) => <article key={i} className="rounded-lg border p-3 text-sm"><h4>{c.name}</h4><p>{c.audience} · {c.price_band}</p><p>{c.use_path}</p><p>{c.strengths} · {c.pain_points}</p><p className="text-xs text-muted-foreground">{c.comparison_basis}</p><CandidateSources ids={c.source_ids} citations={citations}/></article>)}
    {d.user_voices?.map((v, i) => <article key={i} className="rounded-lg border p-3 text-sm"><blockquote>“{v.quote}”</blockquote><p>{v.context} · {v.pain_point}</p><CandidateSources ids={v.source_ids} citations={citations}/></article>)}
    {!!d.questions.length && <section className="text-sm"><h4 className="font-medium">待决问题</h4><ul className="mt-2 space-y-1">{d.questions.map(q => <li key={q}>{q}</li>)}</ul></section>}
    {!!d.risks.length && <section className="text-sm"><h4 className="font-medium">风险</h4><ul className="mt-2 space-y-1">{d.risks.map(r => <li key={r}>{r}</li>)}</ul></section>}
  </div>;
}
