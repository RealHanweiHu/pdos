"use client";

import { isRecord } from "@/components/workspace-api";

function text(source: Record<string, unknown>, key: string): string { return typeof source[key] === "string" ? source[key] : ""; }
export function actionProposalReady(payload: Record<string, unknown>): boolean {
  return ["title", "description", "agenda_id", "assignee_id", "due_date", "expected_output"].every(key => text(payload, key).trim())
    && payload.details_confirmed === true && Array.isArray(payload.citations) && payload.citations.length > 0;
}
export function MeetingActionProposalView({ projectId, payload, onChange }: {
  projectId: string; payload: Record<string, unknown>; onChange?: (next: Record<string, unknown>) => void;
}) {
  const agendas = Array.isArray(payload.agenda_options) ? payload.agenda_options.filter(isRecord) : [];
  const members = Array.isArray(payload.member_options) ? payload.member_options.filter(isRecord) : [];
  const quotes = Array.isArray(payload.citations) ? payload.citations.filter(isRecord) : [];
  const edit = (key: string, value: unknown) => onChange?.({ ...payload, [key]: value, details_confirmed: false });
  const controls = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
  return <div className="space-y-4 p-4 text-sm">
    <p className="text-xs text-muted-foreground">本建议尚未创建任务。请核对议题、负责人、截止日期和完成标准，接受后再独立应用；纪要确认不会代替这些办理。</p>
    <div className="rounded-lg bg-muted/40 p-3 text-xs"><p>原文责任表述：{text(payload, "owner_text") || "未明确，待人核对"}</p><p className="mt-2">原文时间表述：{text(payload, "date_text") || "未明确，待人核对"}</p></div>
    {[{ key: "title", label: "行动标题", max: 512 }, { key: "description", label: "行动内容与依据", max: 3000 }, { key: "expected_output", label: "完成标准", max: 3000 }].map(field => <label key={field.key} className="block text-xs">{field.label}{onChange ? <textarea aria-label={field.label} className={controls} maxLength={field.max} rows={field.key === "title" ? 2 : 4} value={text(payload, field.key)} onChange={event => edit(field.key, event.target.value)} /> : <p className="mt-1 whitespace-pre-wrap break-words text-sm">{text(payload, field.key) || "待补充"}</p>}</label>)}
    <div className="grid gap-3 sm:grid-cols-2"><label className="block text-xs">所属议题{onChange ? <select className={controls} value={text(payload, "agenda_id")} onChange={event => edit("agenda_id", event.target.value || null)}><option value="">请选择需办理的议题</option>{agendas.map(item => <option key={text(item, "id")} value={text(item, "id")}>{text(item, "title")}</option>)}</select> : <p className="mt-1 text-sm">{text(agendas.find(a => a.id === payload.agenda_id) ?? {}, "title") || "待选择"}</p>}</label>
    <label className="block text-xs">具名负责人{onChange ? <select className={controls} value={text(payload, "assignee_id")} onChange={event => edit("assignee_id", event.target.value || null)}><option value="">请选择实际负责人</option>{members.map(item => <option key={text(item, "id")} value={text(item, "id")}>{text(item, "display_name")}</option>)}</select> : <p className="mt-1 text-sm">{text(members.find(m => m.id === payload.assignee_id) ?? {}, "display_name") || "待选择"}</p>}</label></div>
    <label className="block text-xs">截止日期{onChange ? <input aria-label="截止日期" type="date" className={controls} value={text(payload, "due_date")} onChange={event => edit("due_date", event.target.value || null)} /> : <p className="mt-1 text-sm">{text(payload, "due_date") || "待确认"}</p>}</label>
    <section className="space-y-2"><h4 className="text-xs font-medium">行动依据原句</h4>{quotes.map((quote, index) => <blockquote key={index} className="whitespace-pre-wrap break-words border-l-2 pl-3 text-xs">{text(quote, "exact_quote")}</blockquote>)}<a className="text-xs text-primary underline" href={`/projects?project=${projectId}&tab=decisions&meeting=${text(payload, "meeting_id")}`}>打开会议核对议题、原文及已有行动</a></section>
    {onChange && <label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={payload.details_confirmed === true} onChange={event => onChange({ ...payload, details_confirmed: event.target.checked })} />已逐项核对议题、实际负责人、截止日期与完成标准，并确认需要新增此行动。</label>}
    {!actionProposalReady(payload) && <p className="text-xs text-destructive">行动资料尚待核对，请编辑补齐后再接受。</p>}
  </div>;
}
