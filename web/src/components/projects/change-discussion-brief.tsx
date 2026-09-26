"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";
import { DiscussionContributions } from "./discussion-contributions";

const strings = (v: unknown): string[] => Array.isArray(v) ? v.map(String) : [];
const natures: Record<string, string> = { observed: "原资料事实", derived: "基于资料的判断", hypothesis: "待证实假设" };
const date = (v: unknown) => typeof v === "string" ? new Date(v).toLocaleString("zh-CN") : "未记录";
export function DiscussionStatement({ value, labels }: { value: Row; labels: Row }) {
  return <div className="space-y-1 rounded-md border p-2"><p>{natures[text(value.nature)]}：{text(value.text)}</p><details><summary className="cursor-pointer text-muted-foreground">核对引用原值</summary>{rows(value.citations).map((c, i) => <div key={i} className="mt-2"><p>{text(labels[text(c.reference_id)]) || (text(c.reference_id).startsWith("turn:") ? "原讨论发言 / 人工补充" : "原引用")}</p><p className="whitespace-pre-wrap break-words">{text(c.quoted_value)}</p></div>)}</details></div>;
}

export function DiscussionInitiation({ value, labels, candidates }: { value: Row; labels: Row; candidates: Row[] }) {
  const output = obj(value.output);
  return <section className="space-y-2 rounded-md border p-3"><p className="font-medium">Agent 发起判断 · {output.action === "convene" ? "已召集有不同依据的专业" : output.action === "not_needed" ? "无需多专业讨论" : "资料不足，尚未召集"}</p>
    <p>此判断及后续发言共用原预算；这是实际模型回执，不代表人工批准。</p>
    <DiscussionStatement value={obj(output.reason)} labels={labels}/>
    {rows(output.seats).map(s => <div key={text(s.key)}><p>{text(candidates.find(c => c.key === s.key)?.label) || text(s.key)} 的信息贡献依据</p><DiscussionStatement value={obj(s.contribution)} labels={labels}/></div>)}
    {strings(output.missing).map((s, i) => <p key={i}>待补：{s}</p>)}
  </section>;
}

function BriefBody({ body, labels }: { body: Row; labels: Row }) {
  const coverage = rows(body.coverage);
  const seat = (id: unknown) => id == null ? "共同资料" : text(coverage.find(v => v.seat_id === id)?.label) || "原专业席位";
  function jump(id: unknown) { const target = document.getElementById(`discussion-turn-${id}`); target?.scrollIntoView({ behavior: "smooth", block: "center" }); }
  return <div className="space-y-3">
    {body.initiation != null && <DiscussionInitiation value={obj(body.initiation)} labels={labels} candidates={coverage}/>}
    <p>{body.discussion_convened === false ? "本次尚未召集专业讨论，发起判断和待补资料已保留；不能当作多席位比较完成。" : body.ended_without_new_content ? "完整一轮没有新增内容，已按原规则停止剩余轮次；保留分歧与未知项，不据此认定共识。" : body.complete ? "所选席位与轮次已执行完成，仍需核对观点与资料缺项。" : "这是未完整完成讨论的阶段摘要，不能据此认定已覆盖所有观点。"}</p>
    <p>已保存发言用量 {String(body.recorded_turn_tokens ?? 0)} tokens；此数不包含未形成发言的重试等原运行费用。</p>
    <div>{coverage.map(c => <p key={text(c.seat_id)}>{text(c.label)}：已保存 {String(c.saved_turns)} 条，复述 {String(c.repeated_turns)} 条{strings(c.missing_rounds).length > 0 ? `；未完成第 ${strings(c.missing_rounds).join("、")} 轮` : ""}{strings(c.not_needed_rounds).length > 0 ? `；按无新增规则停止第 ${strings(c.not_needed_rounds).join("、")} 轮` : ""}。</p>)}</div>
    <DiscussionContributions value={obj(body.contributions)} coverage={coverage}/>
    <details><summary className="cursor-pointer font-medium">专业观点及依据 · {rows(body.positions).length} 条</summary><div className="mt-2 space-y-2">{rows(body.positions).map((p, i) => <div key={i}><Button type="button" size="sm" variant="ghost" onClick={() => jump(p.turn_id)}>{seat(p.seat_id)} · 查看第 {String(p.sequence)} 条原发言</Button><DiscussionStatement value={obj(p.statement)} labels={labels}/></div>)}</div></details>
    <section className="space-y-2"><p className="font-medium">明确回应与分歧</p><p className="text-muted-foreground">同意是对应发言的明确回应，不代表全席共识；未回应的观点仍待核对。</p>{rows(body.responses).map((r, i) => <div key={i}><p>{seat(r.seat_id)} 回应第 {String(r.target_sequence)} 条：{r.position === "agree" ? "同意" : r.position === "disagree" ? "不同意" : "需补证据"}{r.cross_seat ? "（跨席）" : "（本席或人工输入）"}</p><DiscussionStatement value={obj(r.basis)} labels={labels}/></div>)}{!rows(body.responses).length && <p>尚无明确回应记录，不能据此认定没有分歧。</p>}</section>
    <section><p className="font-medium">待补资料与未知项</p>{rows(body.missing).map((m, i) => <p key={i}>{seat(m.seat_id)}：{text(m.message)}</p>)}{!rows(body.missing).length && <p>发言及席位未列额外缺项，仍须人工核对覆盖。</p>}</section>
    {rows(body.human_inputs).length > 0 && <p>另保留 {rows(body.human_inputs).length} 条具名人工补充，请在原发言中核对；补充本身不等于已核实事实。</p>}
  </div>;
}

type Choice = { title: string; tradeoff: string; turn_ids: string[] };
export function ChangeDiscussionBrief({ run, currentSource, canReview, busy, submit }: { run: Row; currentSource: string; canReview: boolean; busy: boolean; submit: (body: Row) => Promise<void> }) {
  const brief = obj(run.brief), body = obj(brief.body), labels = obj(run.reference_labels);
  const [choices, setChoices] = useState<Choice[]>([{ title: "", tradeoff: "", turn_ids: [] }, { title: "", tradeoff: "", turn_ids: [] }]);
  const [outcome, setOutcome] = useState("validated");
  const working = ["queued", "running"].includes(text(run.status)) || run.recovery_requested === true && run.status === "degraded";
  const sameSource = currentSource === run.source_digest;
  const reviewHistory = rows(brief.reviews), latest = reviewHistory[0];
  const currentReview = latest?.brief_digest === brief.digest && sameSource ? latest : null;
  const actualTurns = rows(run.turns).filter(t => rows(run.receipts).some(r => r.turn_id === t.id));
  function edit(index: number, patch: Partial<Choice>) { setChoices(items => items.map((v, i) => i === index ? { ...v, ...patch } : v)); }
  return <details className="space-y-3 rounded-md border p-3"><summary className="cursor-pointer font-medium">决策摘要与人工对照 · {currentReview ? obj(currentReview.body).outcome === "validated" ? "已具名核对" : "已退回" : "待核对"}</summary>
    <p>摘要按真实回执直接整理。人工核对记录与原讨论版本绑定，不会批准 ECR、签发生效 ECN 或自动开放模型能力。</p>
    <BriefBody body={body} labels={labels}/>
    {!sameSource && <p className="text-primary">原资料与当前预览不同；历史摘要可回看，核对通过前须按当前资料重新分析。</p>}
    {canReview && !working && actualTurns.length > 0 && <form className="space-y-3" onSubmit={e => { e.preventDefault(); const values = new FormData(e.currentTarget); void submit({ expected_digest: brief.digest, outcome, manual_conclusion: values.get("manual_conclusion"), comparison: values.get("comparison"), recommendation: values.get("recommendation"), evidence_checked: values.get("evidence_checked") === "on", disagreements_complete: values.get("disagreements_complete") === "on", alternatives: choices.filter(v => v.title.trim() || v.tradeoff.trim() || v.turn_ids.length) }); }}><fieldset disabled={busy} className="space-y-3">
      <label className="block">人工独立结论<textarea name="manual_conclusion" required maxLength={4000} className={field}/></label>
      <label className="block">与讨论对照：一致、遗漏或需纠正的内容<textarea name="comparison" required maxLength={4000} className={field}/></label>
      <p className="font-medium">人工备选方案与取舍</p>
      {choices.map((choice, index) => <div key={index} className="space-y-2 rounded-md border p-2"><label className="block">方案 {index + 1}<input required={outcome === "validated"} maxLength={300} className={field} value={choice.title} onChange={e => edit(index, { title: e.target.value })}/></label><label className="block">收益、代价、风险与尚待明确处<textarea required={outcome === "validated" || !!choice.title} maxLength={4000} className={field} value={choice.tradeoff} onChange={e => edit(index, { tradeoff: e.target.value })}/></label><fieldset><legend>引用本次专业发言</legend>{actualTurns.map(t => <label key={text(t.id)} className="mr-3 inline-flex gap-1"><input type="checkbox" checked={choice.turn_ids.includes(text(t.id))} onChange={e => edit(index, { turn_ids: e.target.checked ? [...choice.turn_ids, text(t.id)] : choice.turn_ids.filter(id => id !== t.id) })}/>第 {String(t.sequence)} 条</label>)}</fieldset>{index > 1 && <Button type="button" size="sm" variant="ghost" onClick={() => setChoices(v => v.filter((_, i) => i !== index))}>移除此方案</Button>}</div>)}
      {choices.length < 8 && <Button type="button" size="sm" variant="outline" onClick={() => setChoices(v => [...v, { title: "", tradeoff: "", turn_ids: [] }])}>增加方案</Button>}
      <label className="block">建议及后续办理依据<textarea name="recommendation" required maxLength={4000} className={field}/></label>
      <label className="flex gap-2"><input name="evidence_checked" type="checkbox" required={outcome === "validated"}/>已核对引用原值与事实/判断区分</label>
      <label className="flex gap-2"><input name="disagreements_complete" type="checkbox" required={outcome === "validated"}/>原发言中的分歧、未知项和未完成范围已如实保留</label>
      <label className="block">核对结果<select className={field} value={outcome} onChange={e => setOutcome(e.target.value)}><option value="validated">核对通过，保留人工建议</option><option value="rejected">退回，记录缺项或纠正意见</option></select></label>
      <Button type="submit" size="sm" disabled={outcome === "validated" && (!sameSource || choices.filter(v => v.title.trim() && v.tradeoff.trim() && v.turn_ids.length).length < 2)}>保存具名核对记录</Button>
    </fieldset></form>}
    {reviewHistory.map((review, index) => { const value = obj(review.body); return <details className="rounded-md border p-2" key={text(review.id)}><summary className="cursor-pointer">{value.outcome === "validated" ? "核对通过" : "退回"} · {text(review.author_name)} · {date(review.created_at)}{index === 0 && review.brief_digest === brief.digest && sameSource ? " · 当前版本" : " · 历史记录"}</summary><div className="mt-2 space-y-2"><p>人工结论：{text(value.manual_conclusion)}</p><p>对照记录：{text(value.comparison)}</p>{rows(value.alternatives).map((a, i) => <p key={i}>备选 {i + 1} · {text(a.title)}：{text(a.tradeoff)}</p>)}<p>建议：{text(value.recommendation)}</p><details><summary className="cursor-pointer">核对时的原摘要</summary><BriefBody body={obj(review.snapshot)} labels={labels}/></details></div></details>; })}
  </details>;
}
