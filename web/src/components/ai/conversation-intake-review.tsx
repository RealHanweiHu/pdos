"use client";

import { useState } from "react";
import { ConversationIntakeImports } from "./conversation-intake-imports";
import { ConversationIntakeAdoption } from "./conversation-intake-adoption";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
type Quote = { reference_id: string; start: number; end: number; exact_quote: string };
type Kind = "issue" | "decision" | "project_observation";
type Proposal = { number: number; kind: Kind; summary: string; anchor: Quote; fields: { name: string; citation: Quote }[]; missing_information: string[] };
type Pair = { first: number; second: number; explanation: string };
type Assessment = { disposition: "proposals" | "insufficient_evidence"; proposals: Proposal[]; possible_duplicates: Pair[]; open_questions: string[] };
type Duplicate = { first: number; second: number; disposition: "keep_separate" | "exclude_first" | "exclude_second"; reason: string };
type Fragment = { reference_id: string; attachment_id: string; ordinal: number; locator: string; text: string };
const text = (v: unknown) => v == null ? "" : String(v);
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const field = "w-full rounded-md border bg-background p-2 text-xs";
const kinds: Record<Kind, string> = { issue: "历史问题资料", decision: "历史决策资料", project_observation: "项目阶段、进展与缺项" };
const fields: Record<Kind, Record<string, string>> = {
  issue: { title: "标题", description: "说明", external_ref: "原编号", source_state: "原状态", root_cause: "原根因", resolution: "原解决措施", target_date: "原目标日期" },
  decision: { title: "标题", outcome: "原结论", context: "背景", options: "选项", trade_offs: "权衡", rationale: "理由", consequence: "影响", historical_date: "原日期", historical_approver: "原批准人", historical_owner: "原负责人", historical_kind: "原类型", historical_state: "原状态", external_ref: "原编号", issue_ref: "原问题编号" },
  project_observation: { phase: "原阶段", progress: "进展", historical_date: "原日期", responsibility: "责任说明", gap: "缺项", other: "其他原文" },
};
const lines = (s: string) => s.split("\n");

function QuotePicker({ fragments, initial, onUse, onClose }: { fragments: Fragment[]; initial: Quote; onUse: (quote: Quote) => void; onClose: () => void }) {
  const [reference, setReference] = useState(initial.reference_id), [quote, setQuote] = useState<Quote | null>(initial);
  const current = fragments.find(f => f.reference_id === reference);
  return <section className="space-y-2 rounded-md border border-primary p-3" aria-label="选择原文引用">
    <label>固定原文片段<select className={field} value={reference} onChange={e => { setReference(e.target.value); setQuote(null); }}>{fragments.map(f => <option key={f.reference_id} value={f.reference_id}>{f.locator} · {f.attachment_id.slice(0, 8)} · 片段 {f.ordinal}</option>)}</select></label>
    <p>在原文中框选连续文字，再点“采用这段原文”。字段保存原文，不代写日期、姓名或结论。</p>
    <textarea aria-label="框选原文字段" className={`${field} min-h-48`} readOnly value={current?.text ?? ""} onSelect={e => {
      const node = e.currentTarget, start = Array.from(node.value.slice(0, node.selectionStart)).length, end = Array.from(node.value.slice(0, node.selectionEnd)).length;
      setQuote(end > start ? { reference_id: reference, start, end, exact_quote: node.value.slice(node.selectionStart, node.selectionEnd) } : null);
    }}/>
    {quote && <p className="whitespace-pre-wrap">字符 {quote.start + 1}–{quote.end}：{quote.exact_quote}</p>}
    <div className="flex gap-2"><Button type="button" size="sm" disabled={!quote?.exact_quote.trim()} onClick={() => quote && onUse(quote)}>采用这段原文</Button><Button type="button" variant="outline" size="sm" onClick={onClose}>取消选段</Button></div>
  </section>;
}

export function ConversationIntakeReview({ conversationId, findingId, archived, onReviewed }: { conversationId: string; findingId: string; archived: boolean; onReviewed: () => void }) {
  const [data, setData] = useState<Row | null>(null), [draft, setDraft] = useState<Assessment | null>(null), [excluded, setExcluded] = useState<Record<number, string>>({});
  const [duplicates, setDuplicates] = useState<Duplicate[]>([]), [comment, setComment] = useState(""), [preview, setPreview] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [picker, setPicker] = useState<{ number: number; index: number | null; quote: Quote } | null>(null);
  const base = `/api/conversations/${conversationId}/intake-ai-findings/${findingId}`;
  const finding = data && isRecord(data.finding) ? data.finding : null, source = data && isRecord(data.source) ? data.source : null;
  const pending = finding?.status === "pending_review", editable = pending && !archived && data?.source_current === true && !busy;
  async function request(path = "", body?: object): Promise<Row> {
    const response = await fetch(base + path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" });
    const value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && isRecord(value.detail) ? text(value.detail.message) : "核对未完成，请保留输入后重试");
    return value;
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "核对未完成"); } finally { setBusy(false); } }
  async function load() {
    const value = await request(); setData(value);
    if (!isRecord(value.finding)) return;
    const item = value.finding, original = isRecord(item.proposed_payload) ? item.proposed_payload : {};
    const accepted = isRecord(item.accepted_payload) ? item.accepted_payload : null;
    setDraft((accepted?.assessment ?? original.assessment) as Assessment);
    setExcluded(Object.fromEntries(rows(accepted?.exclusions).map(v => [Number(v.number), text(v.reason)])));
    setDuplicates(accepted ? accepted.duplicate_reviews as Duplicate[] : rows(original.possible_duplicates).map(v => ({ first: Number(v.first), second: Number(v.second), disposition: "keep_separate", reason: "" })));
    setComment(text(item.review_comment)); setPreview(null); setPicker(null);
  }
  function change(number: number, patch: Partial<Proposal>) { setDraft(old => old && { ...old, proposals: old.proposals.map(p => p.number === number ? { ...p, ...patch } : p) }); setPreview(null); }
  function edited() {
    if (!draft) throw new Error("请先读取原建议");
    const proposals = draft.proposals.filter(p => !(p.number in excluded)).map(p => ({ ...p, missing_information: p.missing_information.filter(v => v.trim()) })), kept = new Set(proposals.map(p => p.number));
    return { assessment: { ...draft, open_questions: draft.open_questions.filter(v => v.trim()), disposition: proposals.length ? "proposals" : "insufficient_evidence", proposals, possible_duplicates: draft.possible_duplicates.filter(p => kept.has(p.first) && kept.has(p.second)) }, exclusions: Object.entries(excluded).map(([number, reason]) => ({ number: Number(number), reason })), duplicate_reviews: duplicates };
  }
  async function review(decision: "accepted" | "rejected") {
    const result = await request("/review", { decision, comment, ...(decision === "accepted" ? { edited: edited(), preview_digest: preview?.preview_digest } : {}) });
    setData(old => ({ ...old, finding: result })); setPreview(null); setPicker(null); onReviewed();
  }
  const fragments = (source?.fragments ?? []) as Fragment[];
  const quoteLabel = (value: Row) => `${fragments.find(f => f.reference_id === value.reference_id)?.locator ?? "原片段"} · ${text(value.reference_id).split(":")[0].slice(0, 8)} · 字符 ${Number(value.start) + 1}–${text(value.end)}`;
  const accepted = finding && isRecord(finding.accepted_payload) ? finding.accepted_payload : null;
  return <details className="space-y-3 rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(load); }}>
    <summary className="cursor-pointer font-medium">人工核对、修改与接受</summary>
    {finding && <>
      <p className="mt-2">核对状态：{({ pending_review: "待核对", accepted: "已接受", rejected: "已拒绝", applied: "已独立应用" } as Record<string, string>)[text(finding.status)] ?? text(finding.status)}。接受固定人工核对稿；在下方分别独立采用项目现状或确认导入问题、历史决策。</p>
      {data?.source_current !== true && <p className="text-destructive">{text(data?.source_reason) || "来源已不再适用"}；历史结果保留回查。</p>}
      {!pending && <p>核对人 {text(finding.reviewed_by_user_id)} · {text(finding.reviewed_at)} · {text(finding.review_comment)}</p>}
      {picker && editable && <QuotePicker key={`${picker.number}:${picker.index}:${picker.quote.reference_id}`} fragments={fragments} initial={picker.quote} onClose={() => setPicker(null)} onUse={quote => {
        const proposal = draft?.proposals.find(p => p.number === picker.number); if (!proposal) return;
        change(proposal.number, picker.index === null ? { anchor: quote } : { fields: proposal.fields.map((f, i) => i === picker.index ? { ...f, citation: quote } : f) }); setPicker(null);
      }}/>}
      {accepted && <ConversationIntakeAdoption conversationId={conversationId} finding={finding} receipts={rows(data?.observation_applications)} disabled={archived || data?.source_current !== true || busy} onAdopted={async () => { await load(); onReviewed(); }}/>}
      {accepted && <ConversationIntakeImports conversationId={conversationId} finding={finding} saved={rows(data?.import_previews)} completed={data && isRecord(data.completed_imports) ? data.completed_imports : {}} disabled={archived || data?.source_current !== true || busy} onChanged={async () => { await load(); onReviewed(); }}/>}
      {!pending && rows(accepted?.exclusions).map(item => <p key={Number(item.number)}>已排除建议 {text(item.number)}：{text(item.reason)}</p>)}
      {draft?.proposals.map(p => <article key={p.number} className="space-y-2 border-t pt-3">
        <div className="flex flex-wrap items-center gap-2"><strong>建议 {p.number}</strong><label className="flex gap-1"><input type="checkbox" disabled={!editable} checked={p.number in excluded} onChange={e => { setExcluded(old => { const next = { ...old }; if (e.target.checked) next[p.number] = ""; else delete next[p.number]; return next; }); setPreview(null); }}/>排除此条</label></div>
        {p.number in excluded ? <label>排除理由<textarea className={field} disabled={!editable} value={excluded[p.number]} maxLength={2000} onChange={e => { setExcluded(old => ({ ...old, [p.number]: e.target.value })); setPreview(null); }}/></label> : <>
          <label>整理类型<select className={field} disabled={!editable} value={p.kind} onChange={e => change(p.number, { kind: e.target.value as Kind })}>{Object.entries(kinds).filter(([key]) => Array.isArray(source?.kinds) && source.kinds.includes(key)).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label>人工归纳（与原文字段分列）<textarea className={field} disabled={!editable} maxLength={2000} value={p.summary} onChange={e => change(p.number, { summary: e.target.value })}/></label>
          <p className="whitespace-pre-wrap">主要依据：{p.anchor.exact_quote}</p><Button type="button" size="sm" variant="outline" disabled={!editable} onClick={() => setPicker({ number: p.number, index: null, quote: p.anchor })}>修改主要依据选段</Button>
          {p.fields.map((f, index) => <div key={index} className="space-y-1 rounded-md border p-2">
            <label>字段归属<select className={field} disabled={!editable} value={f.name} onChange={e => change(p.number, { fields: p.fields.map((v, i) => i === index ? { ...v, name: e.target.value } : v) })}>{!fields[p.kind][f.name] && <option value={f.name}>请重新归类：{f.name}</option>}{Object.entries(fields[p.kind]).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <p className="whitespace-pre-wrap">{f.citation.exact_quote}</p><p className="text-muted-foreground">{fragments.find(v => v.reference_id === f.citation.reference_id)?.locator} · 字符 {f.citation.start + 1}–{f.citation.end}</p>
            <div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={!editable} onClick={() => setPicker({ number: p.number, index, quote: f.citation })}>修改原文选段</Button><Button type="button" size="sm" variant="outline" disabled={!editable} onClick={() => change(p.number, { fields: p.fields.filter((_, i) => i !== index) })}>移除字段</Button></div>
          </div>)}
          <Button type="button" size="sm" variant="outline" disabled={!editable || p.fields.length >= Object.keys(fields[p.kind]).length} onClick={() => { const name = Object.keys(fields[p.kind]).find(key => !p.fields.some(f => f.name === key)); if (name) { change(p.number, { fields: [...p.fields, { name, citation: p.anchor }] }); setPicker({ number: p.number, index: p.fields.length, quote: p.anchor }); } }}>补充原文字段</Button>
          <label>待补信息（每行一项）<textarea className={field} disabled={!editable} value={p.missing_information.join("\n")} onChange={e => change(p.number, { missing_information: lines(e.target.value) })}/></label>
        </>}
      </article>)}
      {duplicates.map((pair, i) => <div key={`${pair.first}:${pair.second}`} className="space-y-2 rounded-md border p-2">
        <p>疑似重复：建议 {pair.first} 与 {pair.second}。{draft?.possible_duplicates.find(p => p.first === pair.first && p.second === pair.second)?.explanation}</p>
        <label>逐对处理<select className={field} disabled={!editable} value={pair.disposition} onChange={e => { setDuplicates(old => old.map((p, index) => i === index ? { ...p, disposition: e.target.value as Duplicate["disposition"] } : p)); setPreview(null); }}><option value="keep_separate">分别保留两条</option><option value="exclude_first">排除建议 {pair.first}</option><option value="exclude_second">排除建议 {pair.second}</option></select></label>
        <label>核对依据（须与上方实际排除结果一致）<textarea className={field} disabled={!editable} value={pair.reason} maxLength={2000} onChange={e => { setDuplicates(old => old.map((p, index) => i === index ? { ...p, reason: e.target.value } : p)); setPreview(null); }}/></label>
      </div>)}
      {draft && <label>其他待确认问题（每行一项）<textarea className={field} disabled={!editable} value={draft.open_questions.join("\n")} onChange={e => { setDraft(old => old && { ...old, open_questions: lines(e.target.value) }); setPreview(null); }}/></label>}
      {pending && <>
        <label>本次核对意见<textarea className={field} disabled={busy || archived} maxLength={2000} value={comment} onChange={e => setComment(e.target.value)}/></label>
        <div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="outline" disabled={!editable || !!picker} onClick={() => void act(async () => setPreview(await request("/preview", edited())))}>查看接受前差异</Button><Button type="button" size="sm" disabled={!editable || !preview || !comment.trim() || !!picker} onClick={() => void act(() => review("accepted"))}>接受这份核对稿</Button><Button type="button" size="sm" variant="outline" disabled={busy || archived || !comment.trim()} onClick={() => void act(() => review("rejected"))}>拒绝全部建议</Button></div>
      </>}
      {preview && <section aria-label="接受前差异" className="space-y-2 rounded-md border border-primary p-3"><strong>实际差异 · 原AI结果 → 人工核对稿</strong>{rows(preview.changes).map(change => <details key={Number(change.number)} open={change.status !== "unchanged"}><summary>建议 {text(change.number)} · {({ added: "新增", excluded: "排除", changed: "已修改", unchanged: "未修改" } as Record<string, string>)[text(change.status)]}</summary><div className="grid gap-2 md:grid-cols-2">{[change.before, change.after].map((value, i) => <div key={i} className="rounded-md bg-muted p-2"><p className="font-medium">{i === 0 ? "原AI建议" : "核对后"}</p>{isRecord(value) ? <><p>{kinds[text(value.kind) as Kind]} · {text(value.summary)}</p>{isRecord(value.anchor) && <p className="whitespace-pre-wrap">主要依据 · {quoteLabel(value.anchor)}：{text(value.anchor.exact_quote)}</p>}{rows(value.fields).map(f => <p key={text(f.name)} className="whitespace-pre-wrap">{fields[text(value.kind) as Kind]?.[text(f.name)] ?? text(f.name)}：{isRecord(f.citation) ? `${quoteLabel(f.citation)}：${text(f.citation.exact_quote)}` : ""}</p>)}<p>待补：{Array.isArray(value.missing_information) ? value.missing_information.join("；") : ""}</p></> : <p>{i === 0 ? "原稿无此条" : `已排除：${excluded[Number(change.number)] ?? ""}`}</p>}</div>)}</div></details>)}<div className="grid gap-2 md:grid-cols-2"><p>原待确认问题：{Array.isArray(preview.questions_before) ? preview.questions_before.join("；") : ""}</p><p>核对后待确认问题：{Array.isArray(preview.questions_after) ? preview.questions_after.join("；") : ""}</p></div>{isRecord(preview.accepted_payload) && rows(preview.accepted_payload.duplicate_reviews).map(pair => <p key={`${pair.first}:${pair.second}`}>建议 {text(pair.first)} / {text(pair.second)}：{pair.disposition === "keep_separate" ? "分别保留" : `排除建议 ${pair.disposition === "exclude_first" ? pair.first : pair.second}`} · {text(pair.reason)}</p>)}<p>未选原文、图片、邮件附件和未核实资料仍属未知；此处确认不等于原业务通过或关闭。</p></section>}
    </>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {busy && <p role="status">正在保存或读取核对回执…</p>}
  </details>;
}
