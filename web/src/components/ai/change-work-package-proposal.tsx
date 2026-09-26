"use client";

import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import { SourcePreview, sourceLabel, scopeKinds } from "@/components/projects/change-impact-scope";

type Row = Record<string, unknown>;
const obj = (v: unknown): Row => isRecord(v) ? v : {};
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const text = (v: unknown) => v == null ? "" : typeof v === "string" ? v : JSON.stringify(v);
const actions: Record<string, string> = { retest: "复验", rereview: "复审 / 查证", recertification: "复认证", coordination: "协同处理", none: "无需行动" };
const conclusions: Record<string, string> = { affected: "受影响", unaffected: "无影响，有依据", unknown: "尚未明确" };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

export function Statement({ value, labels }: { value: Row; labels: Row }) {
  return <div className="space-y-1"><p className="whitespace-pre-wrap">{{ observed: "原资料观察", derived: "推导", hypothesis: "待验证假设" }[text(value.nature)] ?? "说明"}：{text(value.text)}</p><details><summary className="cursor-pointer text-muted-foreground">核对引用的原字段</summary>{rows(value.citations).map((citation, i) => <blockquote className="mt-2 whitespace-pre-wrap border-l-2 pl-2" key={i}><span className="block text-muted-foreground">{text(labels[text(citation.reference_id)]) || "原业务引用"} · {Array.isArray(citation.field_path) ? citation.field_path.map(String).join(" / ") : ""}</span>{text(citation.quoted_value)}</blockquote>)}</details></div>;
}

export function ChangeAssessmentView({ assessment, labels }: { assessment: Row; labels: Row }) {
  return <div className="space-y-3 text-sm"><p className="whitespace-pre-wrap">覆盖限制：{text(assessment.coverage_limits)}</p>{Array.isArray(assessment.missing) && assessment.missing.length > 0 && <p>待补资料：{assessment.missing.map(String).join("；")}</p>}{rows(assessment.summary).map((statement, i) => <Statement key={i} value={statement} labels={labels}/>)}{rows(assessment.impacts).map(impact => <div className="space-y-2 rounded-md border p-3" key={text(impact.target_reference_id)}><p className="font-medium">{text(labels[text(impact.target_reference_id)]) || "原对象"} · 建议判定：{conclusions[text(impact.verdict)]}</p><Statement value={obj(impact.basis)} labels={labels}/>{rows(impact.proposed_work).map((work, i) => <div className="space-y-1 border-t pt-2" key={i}><p>{actions[text(work.action)]} · {text(work.discipline)}</p><p className="whitespace-pre-wrap">{text(work.description)}</p><p className="whitespace-pre-wrap">完成判据：{work.completion_criteria == null ? "待专业补齐" : text(work.completion_criteria)}</p><Statement value={obj(work.basis)} labels={labels}/>{Array.isArray(work.missing) && work.missing.length > 0 && <p>待补：{work.missing.map(String).join("；")}</p>}</div>)}</div>)}</div>;
}

const filled = (v: unknown, max: number) => typeof v === "string" && !!v.trim() && v.length <= max;
function mergedCount(payload: Row): number {
  const context = obj(payload.review_context), version = obj(obj(context.scope).version);
  const keys = new Set(rows(obj(version.snapshot).items).map(i => `${i.kind}:${i.id}`));
  rows(obj(payload.review).choices).filter(c => c.disposition === "adopt").forEach(c => keys.add(text(c.target_reference_id)));
  return keys.size;
}
export function changePackageReady(payload: Row): boolean {
  const review = obj(payload.review), choices = rows(review.choices), impacts = rows(obj(payload.assessment).impacts);
  return payload.details_confirmed === true && mergedCount(payload) <= 100 && (obj(payload.review_context).scope == null || obj(obj(payload.review_context).scope).ready === true) && filled(review.reason, 4000) && filled(review.coverage, 10000) && filled(review.exclusions, 10000)
    && choices.length === impacts.length && new Set(choices.map(c => c.target_reference_id)).size === impacts.length
    && impacts.every(i => choices.some(c => c.target_reference_id === i.target_reference_id))
    && choices.some(c => c.disposition === "adopt") && choices.every(c => filled(c.reason, 4000) &&
      (c.disposition === "exclude" || c.disposition === "adopt" && filled(c.basis, 4000) && filled(c.next_action, 4000) && Object.hasOwn(actions, text(c.action)) && Object.hasOwn(conclusions, text(c.conclusion)) && (c.conclusion === "unaffected" || c.action !== "none")));
}

export function ChangeWorkPackageProposalView({ projectId, payload, onChange }: { projectId: string; payload: Row; onChange?: (value: Row) => void }) {
  const context = obj(payload.review_context), targets = obj(context.targets), assessment = obj(payload.assessment), impacts = rows(assessment.impacts);
  const oldVersion = obj(obj(context.scope).version), oldSnapshot = obj(oldVersion.snapshot), oldItems = rows(oldSnapshot.items);
  const review = obj(payload.review), choices = rows(review.choices);
  const update = (change: Row) => onChange?.({ ...payload, review: { ...review, ...change }, details_confirmed: false });
  const updateChoice = (id: string, change: Row) => update({ choices: choices.map(c => c.target_reference_id === id ? { ...c, ...change } : c) });
  return <div className="space-y-4 p-3 text-sm">
    {context.discussion_input != null && <p className="rounded-md bg-muted/40 p-2">本候选采用了固定版本的专业讨论摘要。请同时核对分歧和未解决问题；讨论发言不代表已批准事实。可在原变更的分析运行记录中查看对应讨论及先前候选。</p>}
    <a href={`/projects?project=${projectId}&tab=engineering&ecr=${text(payload.ecr_id)}`} className="text-primary underline">打开原变更与当前范围</a>
    <p>先逐项核对并接受候选，再独立应用为变更范围新版本。原范围中未被明确调整的条目、原关系与历史版本会保留；后续影响分析、批准和任务安排继续在原变更办理。</p>
    <ChangeAssessmentView assessment={assessment} labels={obj(context.reference_labels)}/>
    <details className="rounded-md border p-3"><summary className="cursor-pointer">原核对范围{oldVersion.revision_number ? ` v${text(oldVersion.revision_number)}` : "（尚未建立）"} · {oldItems.length} 个对象</summary><p className="mt-2 whitespace-pre-wrap">原覆盖：{text(oldSnapshot.coverage) || "未填写"}</p><p className="whitespace-pre-wrap">原排除：{text(oldSnapshot.exclusions) || "未填写"}</p>{oldItems.map(item => <div className="mt-2 rounded-md border p-2" key={text(item.key)}><p>{scopeKinds[text(item.kind)]} · {sourceLabel(obj(item.snapshot))}</p><p>{conclusions[text(item.conclusion)]} · {actions[text(item.action)]}</p><p className="whitespace-pre-wrap">{text(item.basis)}</p><p className="whitespace-pre-wrap">{text(item.next_action)}</p></div>)}<p className="mt-2">保留原有的 {rows(oldSnapshot.edges).length} 条有据关系。</p></details>
    {onChange && !payload.review && <Button size="sm" variant="outline" onClick={() => update({ reason: "", coverage: text(oldSnapshot.coverage), exclusions: text(oldSnapshot.exclusions), choices: impacts.map(impact => {
      const works = rows(impact.proposed_work), old = oldItems.find(i => `${i.kind}:${i.id}` === impact.target_reference_id);
      return { target_reference_id: impact.target_reference_id, disposition: "", reason: "", conclusion: impact.verdict, action: works.length > 1 ? "coordination" : text(works[0]?.action) || "none", basis: text(obj(impact.basis).text), next_action: works.length ? works.map(w => `${actions[text(w.action)]} · ${text(w.discipline)}：${text(w.description)}\n完成判据：${text(w.completion_criteria) || "待专业补齐"}${Array.isArray(w.missing) && w.missing.length ? `\n待补：${w.missing.map(String).join("；")}` : ""}`).join("\n\n") : text(old?.next_action) };
    }) })}>开始逐项核对采用范围</Button>}
    {payload.review != null && <div className="space-y-3"><h4 className="font-medium">人工核对与应用内容</h4><p>应用后共 {mergedCount(payload)} 个范围对象；采用 {choices.filter(c=>c.disposition==="adopt").length} 项建议，不采用 {choices.filter(c=>c.disposition==="exclude").length} 项建议。原其他条目和全部有据关系保留。</p>{mergedCount(payload)>100&&<p role="alert" className="text-destructive">合并范围超过 100 个对象，请调整采用项。</p>}{choices.map(choice => {
      const id = text(choice.target_reference_id), target = obj(targets[id]);
      return <fieldset key={id} className="space-y-2 rounded-md border p-3" disabled={!onChange}><legend>{text(target.label) || "核对对象"}</legend><SourcePreview snapshot={obj(target.snapshot)}/><label className="block">本项建议如何处理<select className={field} value={text(choice.disposition)} onChange={e => updateChoice(id, { disposition: e.target.value, ...(e.target.value === "exclude" ? { basis: "", next_action: "" } : {}) })}><option value="">请明确选择</option><option value="adopt">采用，经核对调整后写入范围</option><option value="exclude">本次不采用此建议，原范围条目保留</option></select></label><label className="block">采用、调整或不采用的实际依据<textarea maxLength={4000} className={field} value={text(choice.reason)} onChange={e => updateChoice(id, { reason: e.target.value })}/></label>{choice.disposition === "adopt" && <><label className="block">核对后的影响判断<select className={field} value={text(choice.conclusion)} onChange={e => updateChoice(id, { conclusion: e.target.value })}>{Object.entries(conclusions).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></label><label className="block">对照原值、适用范围与判断依据<textarea maxLength={4000} className={field} value={text(choice.basis)} onChange={e => updateChoice(id, { basis: e.target.value })}/></label><label className="block">处理方式<select className={field} value={text(choice.action)} onChange={e => updateChoice(id, { action: e.target.value })}>{Object.entries(actions).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></label><label className="block">后续全部工作及逐项完成判据<textarea maxLength={4000} className={`${field} min-h-36`} value={text(choice.next_action)} onChange={e => updateChoice(id, { next_action: e.target.value })}/><span className="text-xs text-muted-foreground">{text(choice.next_action).length} / 4000 字。多项专业工作须全部说明，缺失判据保留待补。</span></label></>}</fieldset>;
    })}
      <fieldset className="space-y-3" disabled={!onChange}>{([ ["coverage", "应用后的完整覆盖范围（包含保留条目）", 10000], ["exclusions", "应用后的排除范围与未覆盖限制", 10000], ["reason", "本次建立 / 修订范围的依据", 4000] ] as const).map(([key,label,max]) => <label className="block" key={key}>{label}<textarea className={field} maxLength={max} value={text(review[key])} onChange={e => update({ [key]: e.target.value })}/></label>)}<label className="flex items-start gap-2"><input type="checkbox" checked={payload.details_confirmed === true} onChange={e => onChange?.({ ...payload, details_confirmed: e.target.checked })}/><span>已逐项核对原值和全部专业工作，并确认采用、调整、不采用的依据及合并后的完整范围。</span></label></fieldset>
    </div>}
  </div>;
}
