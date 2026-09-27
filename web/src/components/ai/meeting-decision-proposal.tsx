"use client";
import { isRecord } from "@/components/workspace-api";

function text(row: Record<string, unknown>, key: string): string { return typeof row[key] === "string" ? row[key] : ""; }
const kinds: Record<string, string> = { technical_choice: "技术选型", supplier_choice: "供应商选择", process_decision: "流程决定", rebaseline: "基线调整", definition_release: "定义发布", ccr_response: "客户变更响应" };
export function decisionProposalReady(payload: Record<string, unknown>): boolean {
  return payload.details_confirmed === true && ["title", "decision_kind", "context", "trade_offs", "outcome", "rationale", "consequence", "approver_id"].every(key => text(payload, key).trim())
    && Array.isArray(payload.options) && payload.options.length > 0 && payload.options.every(o => typeof o === "string" && o.trim())
    && Array.isArray(payload.citations) && payload.citations.length > 0
    && (payload.follow_up_pending === true ? !!text(payload, "owner_id") && !!text(payload, "follow_up_note").trim() : !["rebaseline", "definition_release"].includes(text(payload, "decision_kind")));
}
export function MeetingDecisionProposalView({ projectId, payload, onChange, draftOwned = false }: { projectId: string; draftOwned?: boolean; payload: Record<string, unknown>; onChange?: (next: Record<string, unknown>) => void }) {
  const members = Array.isArray(payload.member_options) ? payload.member_options.filter(isRecord) : [];
  const quotes = Array.isArray(payload.citations) ? payload.citations.filter(isRecord) : [];
  const options = Array.isArray(payload.options) ? payload.options.filter((v): v is string => typeof v === "string") : [];
  const edit = (key: string, value: unknown) => onChange?.({ ...payload, [key]: value, details_confirmed: false });
  const input = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
  return <div className="space-y-4 p-4 text-sm">
    <p className="text-xs text-muted-foreground">{draftOwned ? "草稿采用不代表决策获批。补齐依据后，须由指定批准人本人正式批准；基线、发布等原业务操作另行办理。" : "请逐项核对决策依据和缺项。接受后，须由指定批准人本人独立应用为正式决策；原业务的发布、签核与执行仍分别办理。"}</p>
    <label className="block text-xs">决策类型{onChange ? <select className={input} value={text(payload, "decision_kind")} onChange={e => edit("decision_kind", e.target.value || null)}><option value="">请选择</option>{Object.entries(kinds).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select> : <p className="mt-1">{kinds[text(payload, "decision_kind")] || "待选择"}</p>}</label>
    {[{ key: "title", label: "标题" }, { key: "context", label: "背景" }, { key: "trade_offs", label: "方案权衡" }, { key: "outcome", label: "待确认的决策结论" }, { key: "rationale", label: "选择理由" }, { key: "consequence", label: "后果与影响" }].map(f => <label key={f.key} className="block text-xs">{f.label}{onChange ? <textarea className={input} aria-label={f.label} rows={f.key === "title" ? 2 : 3} maxLength={f.key === "title" ? 512 : 5000} value={text(payload, f.key)} onChange={e => edit(f.key, e.target.value || null)} /> : <p className="mt-1 whitespace-pre-wrap break-words text-sm">{text(payload, f.key) || "缺少依据，待补充"}</p>}</label>)}
    <label className="block text-xs">考虑的选项（每行一项）{onChange ? <textarea className={input} rows={4} value={options.join("\n")} onChange={e => edit("options", e.target.value.split("\n"))} /> : <ul className="mt-1 list-disc pl-4">{options.map((o, i) => <li key={i}>{o}</li>)}</ul>}</label>
    {[{ key: "approver_id", label: "具名批准人（由本人独立应用）" }, { key: "owner_id", label: "执行跟进负责人" }].map(f => <label key={f.key} className="block text-xs">{f.label}{onChange ? <select className={input} value={text(payload, f.key)} onChange={e => edit(f.key, e.target.value || null)}><option value="">请选择</option>{members.map(m => <option key={text(m, "id")} value={text(m, "id")}>{text(m, "display_name")}</option>)}</select> : <p className="mt-1">{text(members.find(m => m.id === payload[f.key]) ?? {}, "display_name") || "待指定"}</p>}</label>)}
    {onChange ? <label className="flex gap-2 text-xs"><input type="checkbox" checked={payload.follow_up_pending === true} onChange={e => edit("follow_up_pending", e.target.checked)} />需要继续在原业务办理或跟进执行</label> : <p className="text-xs">{payload.follow_up_pending ? "应用后保留待执行跟进" : "已明确无需后续执行"}</p>}
    {payload.follow_up_pending === true && <label className="block text-xs">执行要求{onChange ? <textarea className={input} maxLength={2000} rows={3} value={text(payload, "follow_up_note")} onChange={e => edit("follow_up_note", e.target.value || null)} /> : <p className="mt-1 whitespace-pre-wrap">{text(payload, "follow_up_note")}</p>}</label>}
    <section className="space-y-2"><h4 className="text-xs font-medium">原句依据</h4>{quotes.map((q, i) => <blockquote key={i} className="whitespace-pre-wrap border-l-2 pl-3 text-xs">{text(q, "exact_quote")}</blockquote>)}<a className="text-xs text-primary underline" href={`/projects?project=${projectId}&tab=decisions&meeting=${text(payload, "meeting_id")}`}>核对会议原文与已有决策</a></section>
    {onChange && <label className="flex gap-2 text-xs"><input type="checkbox" checked={payload.details_confirmed === true} onChange={e => onChange({ ...payload, details_confirmed: e.target.checked })} />已核对决策结论、依据、责任和后续执行范围。</label>}
    {!decisionProposalReady(payload) && <p className="text-xs text-destructive">决策资料或具名确认尚不完整，请补齐后再正式办理。</p>}
  </div>;
}
