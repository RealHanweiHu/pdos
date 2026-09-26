"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { IssueIntakeConfirmation } from "./issue-intake-confirmation";
import { DecisionIntakeConfirmation } from "./decision-intake-confirmation";
import type { IntakeSourceRow } from "./issue-intake-reuse";
type Row = Record<string, unknown>;
const text = (v: unknown) => v == null ? "" : String(v);
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const strings = (v: unknown): string[] => Array.isArray(v) ? v.map(String) : [];
const field = "w-full rounded-md border bg-background p-2 text-xs";

export function ConversationIntakeImports({ conversationId, finding, saved, completed, disabled, onChanged }: { conversationId: string; finding: Row; saved: Row[]; completed: Row; disabled: boolean; onChanged: () => Promise<void> }) {
  const accepted = isRecord(finding.accepted_payload) ? finding.accepted_payload : {};
  const candidates = rows(accepted.proposals).filter(p => p.kind === "issue" || p.kind === "decision");
  const [number, setNumber] = useState(""), [format, setFormat] = useState("YYYY-MM-DD"), [preview, setPreview] = useState<Row | null>(null), [kind, setKind] = useState("issue");
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const readonly = disabled || finding.status === "applied";
  async function request(path: string, body?: object): Promise<Row> {
    const response = await fetch(`/api/conversations/${conversationId}${path}`, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" });
    const value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && isRecord(value.detail) ? text(value.detail.message) : "导入暂未完成，请读取原草稿及回执");
    return value;
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "导入未完成"); } finally { setBusy(false); } }
  async function open(type: string, id: string) { setKind(type); setPreview(await request(`/${type}-intake-previews/${id}`)); }
  async function reload() { if (preview) await open(kind, text(preview.id)); await onChanged(); }
  async function prepare() {
    const result = await request(`/intake-ai-findings/${finding.id}/prepare-import`, { number: Number(number), date_format: format });
    await open(text(result.kind), text(result.id)); await onChanged();
  }
  const mapping = preview && isRecord(preview.mapping) ? preview.mapping : {}, sources = isRecord(mapping.source_identities) ? mapping.source_identities : {};
  const entries = rows(preview?.rows);
  const issueRows: IntakeSourceRow[] = entries.map(row => ({ row: Number(row.row), errors: strings(row.errors), proposed: isRecord(row.proposed) ? Object.fromEntries(Object.entries(row.proposed).map(([key, value]) => [key, value == null ? null : text(value)])) : {}, historical_state: row.historical_state == null ? null : text(row.historical_state), external_ref: row.external_ref == null ? null : text(row.external_ref) }));
  if (!candidates.length) return null;
  return <section className="space-y-3 rounded-md border p-3" aria-label="独立导入问题和历史决策">
    <strong>独立导入问题和历史决策</strong>
    <p>先按原文日期格式生成实际导入草稿，再核对新建或关联已有对象并确认。保存草稿不计为业务应用。</p>
    {candidates.map(p => <p key={Number(p.number)}>建议 {text(p.number)} · {p.kind === "issue" ? "问题" : "历史决策"} · {isRecord(completed[text(p.number)]) ? <a className="text-primary underline" href={text((completed[text(p.number)] as Row).href)}>已登记，打开实际业务</a> : "待办理"}</p>)}
    <label className="block">选择已接受的建议<select className={field} value={number} disabled={readonly || busy} onChange={e => setNumber(e.target.value)}><option value="">请选择</option>{candidates.filter(p => !completed[text(p.number)]).map(p => <option key={Number(p.number)} value={text(p.number)}>建议 {text(p.number)} · {text(p.model_summary)}</option>)}</select></label>
    <label className="block">原文日期格式<select className={field} disabled={readonly || busy} value={format} onChange={e => setFormat(e.target.value)}>{["YYYY-MM-DD", "YYYY/MM/DD", "DD/MM/YYYY", "MM/DD/YYYY", "RFC 5322"].map(v => <option key={v}>{v}</option>)}</select></label>
    <Button type="button" size="sm" variant="outline" disabled={readonly || busy || !number} onClick={() => void act(prepare)}>生成或读取此格式的导入草稿</Button>
    {saved.length > 0 && <details><summary className="cursor-pointer">已保存的导入草稿（{saved.length}）</summary>{saved.map(item => <div key={text(item.id)} className="my-2"><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => open(text(item.kind), text(item.id)))}>建议 {text(item.number)} · {text(item.date_format)} · {text(item.created_at)}</Button></div>)}</details>}
    {preview && <section className="space-y-3 border-t pt-3">
      <p>当前导入：建议 {text(mapping.proposal_number)} · {text(mapping.date_format)}</p>
      {preview.source_current !== true && <p className="text-destructive">固定原文、权限或已接受核对稿不再适用。草稿及历史回执保留，新登记需重新核对。</p>}
      <p>确认登记将共享下列完整原件（包括未选内容），以及所选字段、许可用途和核对回执：</p>
      {Object.entries(sources).map(([key, value]) => isRecord(value) && <p key={key}>{text(value.filename)} · {text(value.size_bytes)} 字节 · SHA256 {text(value.sha256)}</p>)}
      <p>许可：{text(preview.permission_basis)} · 用途：{text(preview.purpose)}</p>
      {entries.map(row => <article key={Number(row.row)} className="space-y-2">
        {strings(row.errors).map((message, i) => <p key={i} className="text-destructive">{message}</p>)}
        {isRecord(row.anchor) && <p className="whitespace-pre-wrap">主要依据 · {text(row.anchor.cell)}：{text(row.anchor.value)}</p>}
        {isRecord(row.original) && Object.entries(row.original).map(([key, value]) => isRecord(value) && <details key={key}><summary>{key} · {text(value.cell)}</summary><p className="whitespace-pre-wrap">{text(value.value)}</p><a className="text-primary underline" href={`/ask?project=${preview.project_id}&conversation=${conversationId}&attachment=${value.attachment_id}&fragment=${value.ordinal}`}>核对实际附件</a></details>)}
        <p>解释后日期：{kind === "issue" && isRecord(row.proposed) ? text(row.proposed.target_date) || "未知" : text(row.historical_date) || "未知"}</p>
        {strings(row.gaps).length > 0 && <p>仍有缺项：{strings(row.gaps).join("、")}</p>}
      </article>)}
      {kind === "issue" ? <IssueIntakeConfirmation key={text(preview.id)} conversationId={conversationId} previewId={text(preview.id)} digest={text(preview.request_digest)} rows={issueRows} receipts={rows(preview.confirmation_receipts)} disabled={readonly || busy || preview.source_current !== true} onRefresh={reload} onBusyChange={setBusy}/> : <DecisionIntakeConfirmation key={text(preview.id)} preview={preview} disabled={busy} readOnly={readonly} act={act} request={request} reload={reload}/>}
    </section>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
  </section>;
}
