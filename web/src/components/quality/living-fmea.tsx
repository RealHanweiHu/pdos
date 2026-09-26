"use client";

import { useRef, useState } from "react";
import { FmeaCandidates } from "./fmea-candidates";
import { Button } from "@/components/ui/button";
import { FmeaSources, FmeaSourceValue, field, kinds, label, obj, request, rows, text, type Reference, type Row } from "./fmea-sources";

const labels: Record<string, string> = { title: "条目名称", design_function: "设计功能与要求", failure_mode: "失效模式", effect: "失效影响", possible_cause: "可能原因与调查依据", control_gaps: "控制措施缺口 / 未覆盖范围", scoring_method: "采用的评分表、版本和分级方法", scoring_basis: "S / O / D 逐项评分依据", unknown_reason: "未评分原因与补齐安排", next_action: "后续处理要求", reason: "本次建立 / 修订理由" };
const scores: Record<string, string> = { severity: "严重度 S", occurrence: "发生度 O", detection: "探测度 D" };
const causes: Record<string, string> = { unknown: "尚不清楚", hypothesis: "待验证假设", evidence_supported: "人员核对有证据支持" };
const defaults = () => ({ title: "", design_function: "", failure_mode: "", effect: "", possible_cause: "", cause_status: "unknown", controls: [], control_gaps: "", severity: null, occurrence: null, detection: null, scoring_method: "", scoring_basis: "", unknown_reason: "", next_action: "", reason: "" } as Row);
function ContentView({ version }: { version: Row }) {
  const body = obj(version.body);
  return <div className="space-y-3 text-sm"><dl className="grid gap-3 md:grid-cols-2">{Object.entries(labels).filter(([k]) => body[k]).map(([k, v]) => <div key={k}><dt className="text-muted-foreground">{v}</dt><dd className="whitespace-pre-wrap">{text(body[k])}</dd></div>)}</dl>
    <p>原因结论：{causes[text(body.cause_status)] ?? "未记录"}</p>
    <p>{Object.entries(scores).map(([k, v]) => `${v}：${body[k] == null ? "未评定" : text(body[k])}`).join(" · ")}</p>
    {rows(body.controls).map(c => <div className="rounded-md border p-2" key={text(c.key)}><p>{c.kind === "prevention" ? "预防控制" : "探测控制"}：{text(c.description)}</p><p>验证要求：{text(c.verification)}</p></div>)}
    {rows(version.sources).map(r => <details className="rounded-md border p-2" key={`${r.kind}:${r.id}`}><summary className="cursor-pointer">{kinds[text(r.kind)]} · {label(obj(r.value))}</summary><p>{text(r.relationship)}</p><p>{text(r.locator)}</p><FmeaSourceValue value={obj(r.value)}/></details>)}
  </div>;
}
export function LivingFmea({ projectId }: { projectId: string }) {
  const [list, setList] = useState<Row | null>(null), [detail, setDetail] = useState<Row | null>(null), [coverage, setCoverage] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [editing, setEditing] = useState(false), [content, setContent] = useState<Row>(defaults), [references, setReferences] = useState<Reference[]>([]);
  const [confirmed, setConfirmed] = useState(false), [publishReason, setPublishReason] = useState("");
  const [candidate, setCandidate] = useState<Row | null>(null), [exclusions, setExclusions] = useState<Record<string,string>>({}), [candidateRefresh, setCandidateRefresh] = useState(0);
  const attempt = useRef<{ signature: string; id: string } | null>(null);
  async function act(fn: () => Promise<void>) { setBusy(true); setError(""); try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "操作失败"); } finally { setBusy(false); } }
  function requestId(body: unknown) { const signature = JSON.stringify(body); if (attempt.current?.signature !== signature) attempt.current = { signature, id: crypto.randomUUID() }; return attempt.current.id; }
  async function load(more = false) { const data = await request(projectId, more && list?.next_offset != null ? `?offset=${list.next_offset}` : ""); setList(old => more && old ? { ...data, items: [...rows(old.items), ...rows(data.items)] } : data); }
  async function select(id: string) { setDetail(await request(projectId, `/${id}`)); setConfirmed(false); setPublishReason(""); }
  async function readCoverage(more = false) { const data = await request(projectId, `/coverage?offset=${more ? coverage?.next_offset ?? 0 : 0}`); setCoverage(old => more && old ? { ...data, items: [...rows(old.items), ...rows(data.items)] } : data); }
  function start(current = false, issue?: Row) {
    attempt.current = null; setCandidate(null); setExclusions({});
    const version = obj(detail?.latest);
    setContent(current ? { ...obj(version.body), reason: "" } : issue ? { ...defaults(), title: text(issue.title), failure_mode: text(issue.description || issue.title), possible_cause: "尚待调查，不能以问题描述代替已证原因", unknown_reason: "待专业人员补齐评分依据" } : defaults());
    setReferences(current ? rows(version.sources).map(r => ({ kind: text(r.kind), id: text(r.id), expected_digest: text(r.expected_digest), relationship: text(r.relationship), locator: text(r.locator), value: obj(r.value) })) : []);
    if (!current) setDetail(null);
    setConfirmed(false); setEditing(true);
  }
  async function fromCandidate(selected: Row, useSelected: boolean) {
    if (useSelected && !detail?.entry_id) throw new Error("请先在上方选择要修订的 FMEA 条目，再办理此候选");
    const actual = await request(projectId, `/candidates/${selected.id}`);
    if (actual.status !== "pending") throw new Error("候选已有变化，请刷新后按当前资料办理");
    const target = useSelected ? await request(projectId, `/${detail?.entry_id}`) : null;
    const version = obj(target?.latest), sourceIssue = obj(obj(actual.snapshot).issue);
    const content = target ? { ...obj(version.body), reason: "" } : { ...defaults(), title: text(sourceIssue.title), failure_mode: text(sourceIssue.description || sourceIssue.title), possible_cause: "尚待专业调查，问题描述不作为已证原因", unknown_reason: "待专业人员补齐评分依据" };
    const refs = new Map<string, Reference>(rows(version.sources).map(r => [`${r.kind}:${r.id}`, { kind: text(r.kind), id: text(r.id), expected_digest: text(r.expected_digest), relationship: text(r.relationship), locator: text(r.locator), value: obj(r.value) }]));
    for (const r of rows(obj(actual.snapshot).sources)) {
      const key = `${r.kind}:${r.id}`, old = refs.get(key);
      refs.set(key, { kind: text(r.kind), id: text(r.id), expected_digest: text(r.expected_digest), relationship: old?.relationship ?? "本次修订的原业务输入，适用范围及专业结论由本版内容说明", locator: old?.locator ?? "", value: obj(r.value) });
    }
    setDetail(target); setContent(content); setReferences([...refs.values()]); setCandidate(actual); setExclusions({}); setConfirmed(false); setEditing(true); attempt.current = null;
  }
  function patch(key: string, value: unknown) { setContent(c => ({ ...c, [key]: value })); }
  const latest = obj(detail?.latest), pub = obj(detail?.publication), published = obj(detail?.published_version);
  const excluded = rows(obj(candidate?.snapshot).sources).filter(r => !references.some(ref => ref.kind === r.kind && ref.id === r.id));
  const samePublished = pub.version_id === latest.id;
  return <details className="rounded-lg border bg-card p-4" onToggle={e => { if (e.currentTarget.open && !list && !busy) void act(() => load()); }}>
    <summary className="cursor-pointer font-semibold">Living FMEA · 失效模式与风险控制</summary>
    <div className="mt-4 space-y-4">
      <p className="text-sm text-muted-foreground">以实际需求、物料、测试和质量记录核对失效模式。评分由人员按明确方法评定；修订保存后须明确发布，原版本持续保留。</p>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy || editing} onClick={() => void act(() => load())}>刷新条目</Button>{list?.can_edit === true && <Button size="sm" disabled={busy || editing} onClick={() => start()}>建立失效模式</Button>}<Button size="sm" variant="outline" disabled={busy || editing} onClick={() => void act(() => readCoverage())}>核对问题覆盖</Button></div>
      {list && !rows(list.items).length && <p className="text-sm">尚无 FMEA 条目。可先登记失效模式、控制缺口及待补评分。</p>}
      <div className="flex flex-wrap gap-2">{rows(list?.items).map(item => <Button key={text(item.id)} size="sm" variant={detail?.entry_id === item.id ? "default" : "outline"} disabled={busy || editing} onClick={() => void act(() => select(text(item.id)))}>{text(item.title)} · v{text(item.version)} · {item.published_version_id == null ? "待发布" : item.published_version_id === item.latest_version_id ? "当前已发布" : "有未发布修订"}</Button>)}{list?.next_offset != null && <Button size="sm" variant="outline" disabled={busy || editing} onClick={() => void act(() => load(true))}>更多条目</Button>}</div>
      <FmeaCandidates key={candidateRefresh} projectId={projectId} disabled={busy || editing} refreshKey={candidateRefresh} onStart={(c, useSelected) => act(() => fromCandidate(c, useSelected))} onOpen={entry => act(() => select(entry))}/>
      {coverage && <section className="space-y-2 rounded-md border p-3"><h4 className="font-medium">问题覆盖核对</h4><p className="text-xs text-muted-foreground">{text(coverage.meaning)}</p>{rows(coverage.items).map(item => { const issue = obj(item.issue); return <div key={text(issue.id)} className="space-y-1 rounded-md border p-2 text-sm"><p>{text(issue.code)} · {text(issue.title)} · {item.coverage === "associated_current" ? "已关联当前版本" : item.coverage === "needs_review" ? "关联来源已变化，需重核" : "尚未关联已发布版本"}</p>{rows(item.links).map(link => <Button size="sm" variant="outline" key={text(link.version_id)} disabled={busy || editing} onClick={() => void act(() => select(text(link.entry_id)))}>{text(link.title)} · v{text(link.version)}</Button>)}{list?.can_edit === true && <Button size="sm" variant="outline" disabled={busy || editing} onClick={() => { start(false, issue); setReferences([{ kind: "issue", id: text(issue.id), expected_digest: text(item.digest), relationship: "本条问题为失效模式调查输入，仍需核对适用范围", locator: "", value: issue }]); }}>据此建立失效模式草稿</Button>}</div>; })}{coverage.next_offset != null && <Button size="sm" variant="outline" disabled={busy || editing} onClick={() => void act(() => readCoverage(true))}>更多问题</Button>}</section>}
      {detail && !editing && <section className="space-y-3 rounded-md border p-3">
        <h4 className="font-medium">{text(obj(latest.body).title)} · 最新修订 v{text(latest.version)}</h4>
        {rows(detail.sources).some(s => s.current !== true) && <p className="text-primary">关联记录已变化或不可用。请在修订中重新读取原值、核对结论后保存。</p>}
        <ContentView version={latest}/>
        {list?.can_edit === true && <Button size="sm" disabled={busy} onClick={() => start(true)}>以最新版本修订</Button>}
        {pub.id ? <p className="text-sm">当前发布 v{text(published.version)} · {text(obj(detail.people)[text(pub.published_by_user_id)])} · {text(pub.published_at)}{Array.isArray(detail.published_source_gaps) && detail.published_source_gaps.length > 0 ? " · 原关联资料需重核" : ""}</p> : <p className="text-sm">尚未发布。</p>}
        {!!pub.id && !samePublished && <details className="rounded-md border p-2"><summary className="cursor-pointer">对照当前发布版本 v{text(published.version)}</summary><ContentView version={published}/></details>}
        {list?.can_publish === true && !samePublished && <form className="space-y-2 rounded-md border p-3" onSubmit={e => { e.preventDefault(); void act(async () => { const body = { version_id: latest.id, expected_publication_id: pub.id ?? null, expected_digest: detail.digest, details_confirmed: confirmed, reason: publishReason.trim() }; await request(projectId, `/${detail.entry_id}/publish`, { ...body, request_id: requestId(body) }); setCandidateRefresh(v => v + 1); await select(text(detail.entry_id)); await load(); if (coverage) await readCoverage(); }); }}>
          <label className="block">发布 / 替代依据<textarea required maxLength={4000} className={field} disabled={busy} value={publishReason} onChange={e => setPublishReason(e.target.value)}/></label>
          <label className="flex items-start gap-2"><input type="checkbox" disabled={busy} checked={confirmed} onChange={e => setConfirmed(e.target.checked)}/><span>已核对本版失效模式、控制措施、评分依据、未知项及实际关联资料。</span></label><Button type="submit" size="sm" disabled={busy || !confirmed || !publishReason.trim() || rows(detail.sources).some(s => s.current !== true)}>发布本版 FMEA</Button>
        </form>}
        <details><summary className="cursor-pointer">不可变修订与发布历史</summary>{rows(detail.history).map(v => <details key={text(v.id)} className="mt-2 rounded-md border p-2"><summary className="cursor-pointer">v{text(v.version)} · {text(obj(detail.people)[text(v.created_by_user_id)])} · {text(v.created_at)} · {text(obj(v.body).reason)}{rows(detail.publications).some(p => p.version_id === v.id) ? " · 曾发布" : " · 修订稿"}</summary><ContentView version={v}/>{rows(detail.candidate_origins).filter(r => r.version_id === v.id).map(r => <div className="mt-2 rounded-md border p-2 text-xs" key={text(r.id)}><p>来自具名候选处置：{text(obj(detail.people)[text(r.created_by_user_id)])} · {text(r.created_at)}</p><p>{text(r.reason)}</p><a className="text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${r.issue_id}#issue-${r.issue_id}`}>追溯原问题 / 质量记录</a>{rows(r.excluded_sources).map(ref => <p key={`${ref.kind}:${ref.id}`}>{kinds[text(ref.kind)]} 不适用依据：{text(ref.reason)}</p>)}</div>)}{rows(detail.publications).filter(p => p.version_id === v.id).map(p => <p className="mt-2 text-sm" key={text(p.id)}>发布人：{text(obj(detail.people)[text(p.published_by_user_id)])} · {text(p.published_at)} · {text(p.reason)}</p>)}</details>)}{detail.next_before_version != null && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => { const more = await request(projectId, `/${detail.entry_id}?before_version=${detail.next_before_version}`); setDetail({ ...detail, history: [...rows(detail.history), ...rows(more.history)], publications: [...rows(detail.publications), ...rows(more.publications)], people: { ...obj(detail.people), ...obj(more.people) }, candidate_origins: [...rows(detail.candidate_origins), ...rows(more.candidate_origins)], next_before_version: more.next_before_version }); })}>更早历史</Button>}</details>
      </section>}
      {editing && <form className="space-y-3" onSubmit={e => { e.preventDefault(); void act(async () => {
        const body = { entry_id: detail?.entry_id ?? null, expected_version_id: latest.id ?? null, content: { ...content, references: references.map(ref => ({ kind: ref.kind, id: ref.id, expected_digest: ref.expected_digest, relationship: ref.relationship, locator: ref.locator })) } };
        const submission = candidate ? { ...body, action: "draft_created", expected_digest: candidate.input_digest, reason: text(content.reason), excluded_sources: excluded.map(r => ({ kind: r.kind, id: r.id, reason: exclusions[`${r.kind}:${r.id}`]?.trim() ?? "" })) } : body;
        const result = await request(projectId, candidate ? `/candidates/${candidate.id}/disposition` : "/versions", { ...submission, request_id: requestId({ candidate_id: candidate?.id ?? null, ...submission }) });
        const entry = text(candidate ? result.entry_id : obj(result.version).entry_id);
        setEditing(false); setCandidate(null); setCandidateRefresh(v => v + 1); await select(entry); await load();
      }); }}><fieldset disabled={busy} className="space-y-3 rounded-md border p-3"><legend className="px-1 font-medium">人工建立 / 修订</legend>
        {candidate && <div className="space-y-2 rounded-md border p-3 text-sm"><p>正在处置原问题 {text(obj(obj(candidate.snapshot).issue).code)} 的修订候选。保存仅建立修订稿；发布仍须另行核对。</p><p>已带入当次实际记录；原有评分保持原值。请核对控制措施、评分依据和各项引用的适用性。</p>{excluded.map(r => <div key={`${r.kind}:${r.id}`}>{r.kind === "issue" ? <p className="text-destructive">须保留原问题引用；若整项不适用，请放弃修订后办理不适用处置。</p> : <label className="block">排除此 {kinds[text(r.kind)]} 的专业理由<textarea required maxLength={4000} className={field} value={exclusions[`${r.kind}:${r.id}`] ?? ""} onChange={e => setExclusions(old => ({ ...old, [`${r.kind}:${r.id}`]: e.target.value }))}/></label>}</div>)}</div>}
        {Object.entries(labels).map(([k, title]) => <label className="block" key={k}>{title}<textarea className={field} required={k !== "unknown_reason"} maxLength={k === "title" ? 300 : 4000} value={text(content[k])} onChange={e => patch(k, e.target.value)}/></label>)}
        <label className="block">原因判断状态<select className={field} value={text(content.cause_status)} onChange={e => patch("cause_status", e.target.value)}>{Object.entries(causes).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <div className="grid gap-3 sm:grid-cols-3">{Object.entries(scores).map(([k, title]) => <label key={k}>{title}<input type="number" min={1} max={10} step={1} placeholder="未评定" className={field} value={content[k] == null ? "" : text(content[k])} onChange={e => patch(k, e.target.value === "" ? null : Number(e.target.value))}/></label>)}</div>
        <p className="text-xs text-muted-foreground">空白表示尚未评定，须说明原因；评分不会根据问题数、测试结果或措施状态自动修改。</p>
        {rows(content.controls).map((c, i) => { const change = (patch: Row) => setContent(old => ({ ...old, controls: rows(old.controls).map((v, n) => n === i ? { ...v, ...patch } : v) })); return <div className="space-y-2 rounded-md border p-2" key={text(c.key)}><label className="block">控制类别<select className={field} value={text(c.kind)} onChange={e => change({ kind: e.target.value })}><option value="prevention">预防控制</option><option value="detection">探测控制</option></select></label><label className="block">控制措施<textarea required maxLength={4000} className={field} value={text(c.description)} onChange={e => change({ description: e.target.value })}/></label><label className="block">验证要求 / 对应测试或原资料<textarea required maxLength={4000} className={field} value={text(c.verification)} onChange={e => change({ verification: e.target.value })}/></label><Button size="sm" type="button" variant="outline" onClick={() => patch("controls", rows(content.controls).filter((_, n) => n !== i))}>移除此措施</Button></div>; })}
        <Button size="sm" type="button" variant="outline" disabled={rows(content.controls).length >= 50} onClick={() => patch("controls", [...rows(content.controls), { key: crypto.randomUUID(), kind: "prevention", description: "", verification: "" }])}>添加控制措施</Button>
        <FmeaSources projectId={projectId} value={references} onChange={setReferences} disabled={busy}/>
        <div className="flex gap-2"><Button type="submit" size="sm" disabled={!!candidate && excluded.some(r => r.kind === "issue" || !exclusions[`${r.kind}:${r.id}`]?.trim())}>{candidate ? "保存修订稿及候选处置回执" : "保存修订稿"}</Button><Button type="button" size="sm" variant="outline" onClick={() => { setEditing(false); setCandidate(null); attempt.current = null; }}>放弃未保存修订</Button></div>
      </fieldset></form>}
    </div>
  </details>;
}
