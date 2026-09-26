"use client";
import { isRecord } from "@/components/workspace-api";

const labels: Record<string, string> = { issue: "问题", risk: "风险", change: "变更申请" };
export const meetingBusinessTypes = ["meeting_issue", "meeting_risk", "meeting_change"];
function text(row: Record<string, unknown>, key: string): string { return typeof row[key] === "string" ? row[key] : ""; }
export function businessProposalReady(p: Record<string, unknown>): boolean {
  if (p.details_confirmed !== true || !text(p, "title").trim() || !text(p, "description").trim() || !Array.isArray(p.citations) || !p.citations.length) return false;
  if (p.kind === "change") return !!text(p, "code").trim();
  if (!text(p, "owner_id") || !text(p, "target_date")) return false;
  if (p.kind === "issue") return !!text(p, "issue_type") && !!text(p, "severity") && !!text(p, "closure_criteria").trim() && (!["high", "critical"].includes(text(p, "severity")) || (!!text(p, "verifier_id") && p.verifier_id !== p.owner_id));
  return p.kind === "risk" && typeof p.likelihood === "number" && p.likelihood >= 1 && p.likelihood <= 5 && typeof p.impact === "number" && p.impact >= 1 && p.impact <= 5 && !!text(p, "mitigation_plan").trim();
}
export function MeetingBusinessProposalView({ projectId, payload: p, onChange }: { projectId: string; payload: Record<string, unknown>; onChange?: (next: Record<string, unknown>) => void }) {
  const members = Array.isArray(p.member_options) ? p.member_options.filter(isRecord) : [];
  const quotes = Array.isArray(p.citations) ? p.citations.filter(isRecord) : [];
  const edit = (key: string, value: unknown) => onChange?.({ ...p, [key]: value, details_confirmed: false });
  const input = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
  const field = (key: string, name: string, max = 5000) => <label key={key} className="block text-xs">{name}{onChange ? <textarea className={input} aria-label={name} rows={key === "title" || key === "code" ? 2 : 3} maxLength={max} value={text(p, key)} onChange={e => edit(key, e.target.value)} /> : <p className="mt-1 whitespace-pre-wrap break-words text-sm">{text(p, key) || "待补充"}</p>}</label>;
  const selectField = (key: string, name: string, choices: Record<string, string>) => <label className="block text-xs">{name}{onChange ? <select className={input} value={text(p, key)} onChange={e => edit(key, e.target.value || null)}><option value="">请选择</option>{Object.entries(choices).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select> : <p className="mt-1">{choices[text(p, key)] || "待指定"}</p>}</label>;
  const people = Object.fromEntries(members.map(m => [text(m, "id"), text(m, "display_name")]));
  return <div className="space-y-4 p-4 text-sm">
    <h4 className="font-medium">会议{labels[text(p, "kind")] || "业务"}建议</h4>
    <p className="text-xs text-muted-foreground">接受与应用分开办理。{p.kind === "change" ? "应用只创建变更申请，后续影响分析、审批和实施沿原流程。" : p.kind === "issue" ? "应用创建待分析问题，根因、处置与关闭证据须后续实际办理。" : "风险评分和应对计划由人核对，后续缓解与关闭沿风险流程。"}</p>
    {field("title", "标题", 512)}{field("description", p.kind === "change" ? "申请原因与范围" : "事实或风险描述")}
    <div className="rounded-lg bg-muted/40 p-3 text-xs"><p className="font-medium">原文提出的应对</p><p className="mt-1 whitespace-pre-wrap">{text(p, "suggested_response") || "未明确提出，不自动补造"}</p></div>
    {p.kind === "change" ? field("code", "变更申请编号", 64) : <>
      {selectField("owner_id", "实际负责人", people)}
      <label className="block text-xs">目标日期{onChange ? <input type="date" className={input} value={text(p, "target_date")} onChange={e => edit("target_date", e.target.value || null)} /> : <p className="mt-1">{text(p, "target_date") || "待确认"}</p>}</label>
      {p.kind === "issue" ? <>
        {selectField("issue_type", "问题类别", { engineering: "工程", quality: "品质", supplier: "供应商", test_failure: "测试失败", certification: "认证" })}
        {selectField("severity", "严重级别", { low: "低", medium: "中", high: "高", critical: "严重" })}
        {selectField("verifier_id", "验证人（高/严重问题须不同于负责人）", people)}{field("closure_criteria", "关闭标准")}
      </> : <>
        {[{ key: "likelihood", label: "发生可能性（1至5）" }, { key: "impact", label: "影响程度（1至5）" }].map(f => <label key={f.key} className="block text-xs">{f.label}{onChange ? <input type="number" min={1} max={5} step={1} className={input} value={typeof p[f.key] === "number" ? String(p[f.key]) : ""} onChange={e => edit(f.key, e.target.value ? Number(e.target.value) : null)} /> : <p className="mt-1">{typeof p[f.key] === "number" ? String(p[f.key]) : "待人工评估"}</p>}</label>)}
        {field("mitigation_plan", "缓解计划")}{field("contingency_plan", "应急方案（如有）")}
      </>}
    </>}
    <section className="space-y-2"><h4 className="text-xs font-medium">原句依据</h4>{quotes.map((q, i) => <blockquote key={i} className="whitespace-pre-wrap border-l-2 pl-3 text-xs">{text(q, "exact_quote")}</blockquote>)}<a className="text-xs text-primary underline" href={`/projects?project=${projectId}&tab=decisions&meeting=${text(p, "meeting_id")}`}>核对会议原文</a></section>
    {onChange && <label className="flex gap-2 text-xs"><input type="checkbox" checked={p.details_confirmed === true} onChange={e => onChange({ ...p, details_confirmed: e.target.checked })} />已核对本候选的事实、范围及所需办理资料。</label>}
    {!businessProposalReady(p) && <p className="text-xs text-destructive">办理资料或逐项确认尚不完整，请补齐后再接受。</p>}
  </div>;
}
