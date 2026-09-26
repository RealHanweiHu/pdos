"use client";

import { obj, rows, text, type Row } from "@/components/quality/fmea-sources";

const strings = (v: unknown): string[] => Array.isArray(v) ? v.map(String) : [];

export function DiscussionContributions({ value, coverage }: { value: Row; coverage: Row[] }) {
  if (!value.version) return null;
  const contributions = rows(value.turns), rounds = rows(value.rounds);
  const notNeeded = new Set(coverage.flatMap(c => strings(c.not_needed_rounds)));
  const seat = (id: unknown) => text(coverage.find(v => v.seat_id === id)?.label) || "原专业席位";
  const sequence = (id: unknown) => contributions.find(v => v.turn_id === id)?.sequence;
  const separate = rows(value.responses).filter(v => v.separate_source_agreement === true);
  function jump(id: unknown) {
    document.getElementById(`discussion-turn-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  return <section className="space-y-2 rounded-md bg-muted/40 p-3">
    <p className="font-medium">实际引用与讨论进展</p>
    <p>{text(value.notice)}</p>
    <details><summary className="cursor-pointer">逐轮新增内容与同席复述</summary>
      <div className="mt-2 space-y-2">{rounds.map(r => <p key={String(r.round_number)}>第 {String(r.round_number)} 轮：{r.complete ? "全席位已发言" : notNeeded.has(String(r.round_number)) ? "已按无新增规则停止" : "尚未完整执行"}，首次引用 {String(r.new_citation_count)} 项来源字段{r.unchanged_from_previous ? "；与上一完整轮的观点、依据、回应及缺项相同" : ""}{strings(r.public_research_since_previous).length > 0 ? "；上一轮后有新增公开研究原文，不能按无新增提前停止" : ""}{strings(r.human_input_since_previous).length > 0 ? "；上一轮后有人补充，不能按无新增提前停止" : ""}。</p>)}</div>
      <div className="mt-2 space-y-2">{contributions.map(t => <div key={text(t.turn_id)}>
        <button type="button" className="text-primary underline" onClick={() => jump(t.turn_id)}>{seat(t.seat_id)} · 第 {String(t.sequence)} 条原发言</button>
        <p>引用 {String(t.business_citation_count)} 项来源字段；本席首次引用 {String(t.new_to_seat_count)} 项，整场首次引用 {String(t.new_to_discussion_count)} 项。{t.repeated_from_turn_id ? `结构化内容与本席第 ${String(sequence(t.repeated_from_turn_id))} 条相同。` : ""}{t.only_discussion_or_no_business_basis ? "未包含直接业务来源引用。" : ""}</p>
      </div>)}</div>
    </details>
    <p>有不同来源对象支持的跨席明确同意：{separate.length} 条。仅根据引用关系列出，须人工核对是否真正构成独立支持。</p>
    {separate.map((r, i) => <p key={i}>{seat(r.seat_id)} 的第 {String(sequence(r.turn_id))} 条，明确同意第 {String(sequence(r.target_turn_id))} 条；原依据见下方回应。</p>)}
    <p>保留的不同意或需补证据回应：{rows(value.recorded_disagreements).length} 条，交由人工判断是否已解决。</p>
    <p>尚无跨席明确回应的发言：{strings(value.without_cross_seat_response).map(id => `第 ${String(sequence(id))} 条`).join("、") || "无"}。未回应不计同意。</p>
    {obj(value.policy).stop_after_unchanged_full_round === true && <p>至少完成两轮，且新一完整轮的结构化内容均与上一轮相同、没有新人工补充{value.research_policy ? "或公开研究原文" : ""}时，可停止剩余轮次。停止不代表共识。</p>}
  </section>;
}
