"use client";

import { useRef, useState } from "react";
import { AuditCustomerDisclosure } from "./audit-customer-disclosure";
import { AuditReportBundles } from "./audit-report-bundles";
import { Button } from "@/components/ui/button";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";

type Evidence = { kind: "gate" | "ecn" | "document"; id: string; position: string; relevance: string; valid_until: string | null };
type Clause = { standard: string; edition: string; clause: string; requirement: string; applicability: "applicable" | "not_applicable" | "unconfirmed"; rationale: string; missing: string; evidence: Evidence[] };
const emptyClause = (): Clause => ({ standard: "", edition: "", clause: "", requirement: "", applicability: "unconfirmed", rationale: "", missing: "", evidence: [] });
const kinds = { gate: "Gate 签核与裁决", ecn: "ECN 与原 ECR 签核", document: "项目文件原件索引" };
const formats = { docx: "Word", xlsx: "Excel", pptx: "PowerPoint", pdf: "PDF" };

export function AuditEvidenceExports({ projectId }: { projectId: string }) {
  const [clauses, setClauses] = useState<Clause[]>([emptyClause()]);
  const [target, setTarget] = useState(0), [kind, setKind] = useState<Evidence["kind"]>("gate");
  const [format, setFormat] = useState<keyof typeof formats>("pdf"), [reason, setReason] = useState("");
  const [search, setSearch] = useState(""), [loadedSearch, setLoadedSearch] = useState("");
  const [options, setOptions] = useState<Row | null>(null), [preview, setPreview] = useState<Row | null>(null), [history, setHistory] = useState<Row | null>(null);
  const [withdrawId, setWithdrawId] = useState(""), [withdrawReason, setWithdrawReason] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const requests = useRef(new Map<string, string>());
  const base = "/api/project-reports/" + projectId;
  function requestId(body: unknown) { const key = JSON.stringify(body); let id = requests.current.get(key); if (!id) { id = crypto.randomUUID(); requests.current.set(key, id); } return id; }
  async function request(path: string, body: unknown): Promise<Row> {
    const response = await fetch(base + "/" + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const value: unknown = await response.json();
    if (!response.ok) throw new Error(text(obj(obj(value).detail).message) || text(obj(value).message) || "证据包操作未完成");
    return obj(value);
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(""); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "证据包暂不可用"); } finally { setBusy(false); } }
  function change(index: number, patch: Partial<Clause>) { setClauses(old => old.map((v, i) => i === index ? { ...v, ...patch } : v)); setPreview(null); }
  function changeEvidence(index: number, at: number, patch: Partial<Evidence>) { change(index, { evidence: clauses[index].evidence.map((v, i) => i === at ? { ...v, ...patch } : v) }); }
  async function loadOptions(before?: string) { const query = before ? loadedSearch : search; const value = await request("audit-options", { kind, search: query, before_id: before ?? null }); setOptions(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); setLoadedSearch(query); }
  async function loadHistory(before?: string) { const value = await request("history", { kind: "audit", before_id: before ?? null }); setHistory(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); }
  function draft() { return { scope: { kind: "audit", audit_clauses: clauses }, format, reason }; }
  async function save() { const body = { ...draft(), expected_digest: preview?.digest }; await request("save", { ...body, request_id: requestId(body) }); setPreview(null); setNotice("内部证据包已固定，原签核和缺项保留；未作客户披露批准或外发。"); await loadHistory(); }
  function reuse(record: Row) { const data = rows(obj(record.scope).audit_clauses); setClauses(data as unknown as Clause[]); setTarget(0); setReason(text(record.reason)); setPreview(null); setNotice("已带入原条款范围；请更新依据，再读取当前来源预览。"); }
  return <details className="space-y-4 rounded-lg border p-4 text-sm">
    <summary className="cursor-pointer font-semibold">审核证据包 · 签核与条款对应</summary>
    <p className="text-muted-foreground">按实际适用的标准、版本及条款组包，可填写 ISO 9001、IATF 16949 或客户要求。请逐条说明适用依据，选择原 Gate、ECN 或项目文件；未选条款不在核对范围。当前输出为内部审阅稿。</p>
    {error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}
    <form className="space-y-4" onSubmit={event => { event.preventDefault(); void act(async () => setPreview(await request("preview", draft()))); }}>
      <fieldset disabled={busy} className="space-y-4">
        {clauses.map((clause, index) => <section key={index} className="space-y-3 rounded-md border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2"><h4 className="font-semibold">条款 {index + 1}</h4><Button type="button" size="sm" variant="ghost" disabled={clauses.length === 1} onClick={() => { setClauses(old => old.filter((_, i) => i !== index)); setTarget(0); setPreview(null); }}>移除此条</Button></div>
          <div className="grid gap-3 sm:grid-cols-3"><label>标准或客户要求名称<input required maxLength={128} className={field} value={clause.standard} onChange={e => change(index, { standard: e.target.value })}/></label><label>实际版本/年份<input required maxLength={128} className={field} value={clause.edition} onChange={e => change(index, { edition: e.target.value })}/></label><label>条款号或要求编号<input required maxLength={128} className={field} value={clause.clause} onChange={e => change(index, { clause: e.target.value })}/></label></div>
          <label className="block">本条核对要求摘要<textarea required maxLength={2048} className={field} value={clause.requirement} onChange={e => change(index, { requirement: e.target.value })}/></label>
          <label className="block">适用性<select className={field} value={clause.applicability} onChange={e => change(index, { applicability: e.target.value as Clause["applicability"] })}><option value="unconfirmed">待确认</option><option value="applicable">适用</option><option value="not_applicable">具名说明不适用</option></select></label>
          <label className="block">适用范围与判断依据<textarea required maxLength={2048} className={field} value={clause.rationale} onChange={e => change(index, { rationale: e.target.value })}/></label>
          <label className="block">缺项、未读取范围与后续补证<textarea required={clause.applicability !== "not_applicable" && !clause.evidence.length} maxLength={2048} className={field} value={clause.missing} onChange={e => change(index, { missing: e.target.value })}/></label>
          {clause.evidence.map((ref, at) => <div key={at} className="space-y-2 border-t pt-3"><p className="break-all font-medium">{kinds[ref.kind]} · {ref.id}</p><label className="block">原件位置/签核轮次定位<input required maxLength={2048} className={field} value={ref.position} onChange={e => changeEvidence(index, at, { position: e.target.value })}/></label><label className="block">该依据与条款的对应说明<textarea required maxLength={2048} className={field} value={ref.relevance} onChange={e => changeEvidence(index, at, { relevance: e.target.value })}/></label><label className="block">人工核对的有效截止日（有时填写，UTC）<input type="date" className={field} value={ref.valid_until ?? ""} onChange={e => changeEvidence(index, at, { valid_until: e.target.value || null })}/></label><Button type="button" size="sm" variant="ghost" onClick={() => change(index, { evidence: clause.evidence.filter((_, i) => i !== at) })}>移除此处依据</Button></div>)}
        </section>)}
        <Button type="button" variant="outline" disabled={clauses.length >= 30} onClick={() => { setClauses(old => [...old, emptyClause()]); setPreview(null); }}>新增条款（{clauses.length}/30）</Button>
        <section className="space-y-3 rounded-md border p-3"><h4 className="font-semibold">查找并加入实际证据</h4><div className="grid gap-3 sm:grid-cols-2"><label>加入哪个条款<select className={field} value={target} onChange={e => setTarget(Number(e.target.value))}>{clauses.map((v, i) => <option key={i} value={i}>条款 {i + 1} · {v.standard} {v.clause}</option>)}</select></label><label>原依据类型<select className={field} value={kind} onChange={e => { setKind(e.target.value as Evidence["kind"]); setOptions(null); }}>{Object.entries(kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label></div><label className="block">名称搜索<input className={field} maxLength={128} value={search} onChange={e => setSearch(e.target.value)}/></label><Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadOptions())}>查找</Button>
          {rows(options?.items).map(v => <article key={text(v.id)} className="flex flex-wrap items-center justify-between gap-2 border-t pt-2"><div><p>{text(v.code)} · {text(v.title)}</p><p className="text-muted-foreground">{text(v.status) || text(v.classification)}</p></div><Button type="button" size="sm" variant="outline" disabled={clauses[target].evidence.length >= 10 || clauses.reduce((n, c) => n + c.evidence.length, 0) >= 100} onClick={() => change(target, { evidence: [...clauses[target].evidence, { kind, id: text(v.id), position: "", relevance: "", valid_until: null }] })}>加入条款 {target + 1}</Button></article>)}
          {options?.next_before_id != null && <Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadOptions(text(options.next_before_id)))}>更多原记录</Button>}<p className="text-muted-foreground">每条最多 10 处，整包最多 100 处。文件只导出原件索引与校验信息；正文附件须沿原文件另行核对。</p>
        </section>
        <label className="block">内部核对用途与范围<textarea required maxLength={2048} className={field} value={reason} onChange={e => { setReason(e.target.value); setPreview(null); }}/></label><label className="block">文件格式<select className={field} value={format} onChange={e => { setFormat(e.target.value as keyof typeof formats); setPreview(null); }}>{Object.entries(formats).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label><Button>读取原记录并预览证据包</Button>
      </fieldset>
    </form>
    {preview && <section className="space-y-3 rounded-md bg-muted/30 p-3"><h4 className="font-semibold">原签核、条款及缺项预览</h4><p className="text-primary">{text(obj(preview.source).status_label)}</p>{rows(obj(preview.source).sections).map((v, i) => <details key={i}><summary className="cursor-pointer font-medium">{text(v.title)}</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words font-sans">{text(v.text)}</pre></details>)}<form className="space-y-3" onSubmit={e => { e.preventDefault(); void act(save); }}><label className="flex items-start gap-2"><input required type="checkbox" key={text(preview.digest)} disabled={busy}/>已核对适用范围、原签核与待补项，仅生成内部审阅稿。</label><Button disabled={busy}>保存固定证据包文件</Button></form></section>}
    <Button type="button" disabled={busy} variant="outline" onClick={() => void act(() => loadHistory())}>查看证据包历史</Button>
    {rows(history?.items).map(v => <article key={text(v.id)} className="space-y-2 rounded-md border p-3"><p className="font-semibold">{formats[text(v.format) as keyof typeof formats]} · {new Date(text(v.created_at)).toLocaleString()}</p><p>{text(v.reason)}</p><p className="break-all text-xs">原文件校验：{text(v.content_digest)}</p>{v.withdrawal ? <p className="text-primary">已撤回：{text(obj(v.withdrawal).reason)} · {new Date(text(obj(v.withdrawal).created_at)).toLocaleString()}</p> : <><a className="inline-flex min-h-11 items-center underline" href={base + "/" + text(v.id) + "/download"}>下载原内部稿（原来源变化会停止下载）</a><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => { setWithdrawId(text(v.id)); setWithdrawReason(""); }}>具名撤回此文件</Button></>}<Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => reuse(v)}>以此范围重新准备</Button><AuditReportBundles projectId={projectId} reportId={text(v.id)} withdrawn={v.withdrawal != null}/><AuditCustomerDisclosure projectId={projectId} reportId={text(v.id)} withdrawn={v.withdrawal != null}/><details><summary className="cursor-pointer">原条款范围</summary><pre className="whitespace-pre-wrap break-words text-xs">{JSON.stringify(obj(v.scope).audit_clauses, null, 2)}</pre></details></article>)}
    {history?.next_before_id != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => loadHistory(text(history.next_before_id)))}>更多历史</Button>}
    {withdrawId && <form className="space-y-3 rounded-md border p-3" onSubmit={e => { e.preventDefault(); void act(async () => { const body = { report_id: withdrawId, reason: withdrawReason }; await request("withdraw", { ...body, request_id: requestId(body) }); setWithdrawId(""); await loadHistory(); setNotice("已撤回此报告及关联附件包，原记录保留；停止后续下载，已下载文件不能追回。"); }); }}><p className="break-all">撤回原文件 {withdrawId}</p><label className="block">撤回原因<textarea required disabled={busy} maxLength={2048} className={field} value={withdrawReason} onChange={e => setWithdrawReason(e.target.value)}/></label><Button disabled={busy}>确认撤回并停止下载</Button><Button type="button" variant="ghost" disabled={busy} onClick={() => setWithdrawId("")}>取消</Button></form>}
  </details>;
}
