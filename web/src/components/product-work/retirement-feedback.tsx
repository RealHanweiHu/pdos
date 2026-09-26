"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { obj, rows, text, field, type Row } from "@/components/quality/fmea-sources";
import { request, type Evidence, type SourceRef } from "./product-work-api";
import { ReferenceEditor } from "./market-segments";

const verdicts: Record<string, string> = { adopt_for_followup: "采用为后续调整依据", retain_assumption: "保留原假设", needs_evidence: "需要补充证据", withdrawn: "撤回原反馈" };
const lifecycle: Record<string, string> = { proposed: "拟议", developing: "开发中", available: "在售 / 可供应", retired: "已退役" };

export function RetirementFeedback({ base, productId, evidence, disabled = false }: { base: string; productId: string; evidence: Evidence[]; disabled?: boolean }) {
  const [events, setEvents] = useState<Row | null>(null), [audit, setAudit] = useState("");
  const [definitions, setDefinitions] = useState<Row | null>(null), [definition, setDefinition] = useState("");
  const [data, setData] = useState<Row | null>(null), [paths, setPaths] = useState<string[]>([]);
  const [verdict, setVerdict] = useState("needs_evidence"), [finding, setFinding] = useState(""), [followUp, setFollowUp] = useState(""), [limits, setLimits] = useState(""), [refs, setRefs] = useState<SourceRef[]>([]);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const attempt = useRef<{ key: string; id: string } | null>(null);
  async function act(work: () => Promise<void>) { setBusy(true); setError(""); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "退市反馈暂不可用"); } finally { setBusy(false); } }
  async function loadEvents(before?: string) { const value = await request<Row>(`${base}/retirement-feedback-options`, "POST", { product_id: productId, before_audit_id: before ?? null }); setEvents(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); }
  async function loadDefinitions(before?: string) { const value = await request<Row>(`${base}/retirement-feedback-options`, "POST", { product_id: productId, retirement_audit_id: audit, before_definition_id: before ?? null }); setDefinitions(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); }
  async function read(before?: number) { const value = await request<Row>(`${base}/retirement-feedback`, "POST", { product_id: productId, retirement_audit_id: audit, definition_id: definition || null, before_version: before ?? null }); setData(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); }
  const source = obj(data?.source), retirement = obj(source.retirement), linked = obj(source.linked_records);
  async function save() {
    const body = { product_id: productId, retirement_audit_id: audit, definition_id: definition || null, expected_version: data?.version, expected_digest: source.digest, field_paths: paths, verdict, finding, follow_up: followUp, limitations: limits, sources: refs };
    const key = JSON.stringify(body); if (attempt.current?.key !== key) attempt.current = { key, id: crypto.randomUUID() };
    await request(`${base}/retirement-feedback-save`, "POST", { ...body, request_id: attempt.current.id });
    attempt.current = null; setNotice("退市反馈已留档；原生命周期、定义和知识发布仍沿原办理流程。"); setFinding(""); setFollowUp(""); setLimits(""); setRefs([]); await read();
  }
  return <details className="space-y-3 rounded-md border p-3 text-sm" onToggle={event => { if (event.currentTarget.open && !events && !busy) void act(() => loadEvents()); }}>
    <summary className="cursor-pointer font-medium">退市记录与复盘反馈</summary>
    <p className="text-muted-foreground">以本对象真实退市记录为依据，核对当时已发布的定义、关联策略和机会。后续恢复供应或修改资料，会与原时点记录分开保留。</p>
    {error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}
    <fieldset className="space-y-3" disabled={busy || disabled}>
      <Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadEvents())}>刷新真实退市记录</Button>
      {events && rows(events.items).length === 0 && <p>此页没有已登记的退市变更。当前状态或口头说明不能替代原办理记录。</p>}
      <label className="block">本次核对的退市记录<select className={field} value={audit} onChange={event => { setAudit(event.target.value); setDefinitions(null); setDefinition(""); setData(null); setPaths([]); setNotice(""); }}><option value="">请选择实际记录</option>{rows(events?.items).map(value => <option key={text(value.id)} value={text(value.id)}>{text(value.recorded_at)} · v{text(value.version)} · {text(value.reason) || "原原因未登记"}</option>)}</select></label>
      {events?.next_before_audit_id != null && <Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadEvents(text(events.next_before_audit_id)))}>更早退市记录</Button>}
      <Button type="button" size="sm" variant="outline" disabled={!audit} onClick={() => void act(() => loadDefinitions())}>查找退市前已发布定义</Button>
      <label className="block">核对范围<select className={field} value={definition} onChange={event => { setDefinition(event.target.value); setData(null); setPaths([]); }}><option value="">本退市对象的原身份、市场和渠道范围</option>{rows(definitions?.items).map(value => <option key={text(value.id)} value={text(value.id)}>{text(value.title)} · 修订 {text(value.revision_number)} · {text(value.published_at)}</option>)}</select></label>
      {definitions && rows(definitions.items).length === 0 && <p>此页没有该次退市前已发布的定义，仍可核对对象本身，不补造假设。</p>}
      {definitions?.next_before_definition_id != null && <Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadDefinitions(text(definitions.next_before_definition_id)))}>更多原定义版本</Button>}
      <Button type="button" disabled={!audit} onClick={() => void act(() => read())}>核对原办理与假设</Button>
    </fieldset>
    {data && <>
      <section className="space-y-2 rounded-md bg-muted/30 p-3"><h6 className="font-medium">原退市记录</h6><p>{text(retirement.recorded_at)} · 原对象 {text(obj(retirement.after).name)}</p><p className="whitespace-pre-wrap">原登记原因：{text(retirement.reason) || "未登记，需补充说明"}</p><p>当前状态：{lifecycle[text(obj(source.current_product).lifecycle)] ?? "未知"}</p><p className="text-muted-foreground">退市状态不证明市场失败、成本收益或技术原因；反馈须保留事实依据和适用限制。</p>
        {Object.entries({ definition: "原定义", strategy: "关联策略", opportunity: "原机会" }).map(([kind, label]) => linked[kind] ? <a key={kind} className="mr-3 inline-flex min-h-11 items-center underline" href={`/product-work?space=${base.split("/")[1]}&tab=${kind === "definition" ? "definitions" : kind === "strategy" ? "strategies" : "opportunities"}#${kind}-${text(obj(linked[kind]).id)}`}>{label}</a> : null)}
        {Array.isArray(source.source_warnings) && source.source_warnings.map((warning, index) => <p key={index} className="text-primary">{String(warning)}</p>)}
        <details><summary className="cursor-pointer">原变更、当前对象与关联假设全文</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(source, null, 2)}</pre></details>
      </section>
      {data.can_respond === true && <form className="space-y-3 rounded-md border p-3" onSubmit={event => { event.preventDefault(); void act(save); }}><fieldset className="space-y-3" disabled={busy || disabled}>
        <h6 className="font-medium">具名反馈</h6><p>选择实际核对的原字段，最多 20 项。未选择的范围保持未回应。</p>
        <div className="max-h-80 space-y-2 overflow-auto">{rows(source.fields).map(value => <label key={text(value.path)} className="block rounded-md border p-2"><span className="flex gap-2"><input type="checkbox" checked={paths.includes(text(value.path))} disabled={!paths.includes(text(value.path)) && paths.length >= 20} onChange={event => setPaths(old => event.target.checked ? [...old, text(value.path)] : old.filter(p => p !== value.path))}/><span className="break-all text-xs">{text(value.path)}</span></span><pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(value.value, null, 2)}</pre></label>)}</div>
        <label className="block">判断<select className={field} value={verdict} onChange={event => setVerdict(event.target.value)}>{Object.entries(verdicts).filter(([key]) => key !== "withdrawn" || Number(data.version)>0).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label className="block">原假设、实际观察与退市原因的关系<textarea className={field} required maxLength={2048} value={finding} onChange={event => setFinding(event.target.value)}/></label>
        <label className="block">后续调整、保留或补证安排<textarea className={field} required maxLength={2048} value={followUp} onChange={event => setFollowUp(event.target.value)}/></label>
        <label className="block">适用范围、未知项与结论限制<textarea className={field} required maxLength={2048} value={limits} onChange={event => setLimits(event.target.value)}/></label>
        <p>补充已保存的研究证据（可选）</p><ReferenceEditor refs={refs} evidence={evidence} onChange={setRefs}/>
        <label className="flex items-start gap-2"><input key={`${text(source.digest)}:${text(data.version)}`} type="checkbox" required/>已核对原退市记录及所选字段，未把后续计划当作已发生效果。</label><Button disabled={!paths.length}>保存退市反馈</Button>
      </fieldset></form>}
      {rows(data.items).map(value => <article key={text(value.id)} className="space-y-2 border-t pt-3"><h6 className="font-medium">反馈 v{text(value.version)} · {verdicts[text(value.verdict)]} · {value.version === data.version ? "最新回应" : "历史回应"}</h6><p className="text-xs text-muted-foreground">{text(value.actor_name)} · {new Date(text(value.created_at)).toLocaleString()}</p><p className="whitespace-pre-wrap">{text(value.finding)}</p><p className="whitespace-pre-wrap">后续：{text(value.follow_up)}</p><p className="whitespace-pre-wrap">限制：{text(value.limitations)}</p>{value.sources_current !== true && <p className="text-primary">原关联资料或当前产品已变化，以下保留当时判断。</p>}{Array.isArray(value.additional_source_warnings) && value.additional_source_warnings.map((warning,index)=><p key={index} className="text-primary">{String(warning)}</p>)}<details><summary className="cursor-pointer">当时所选字段及全部依据</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify({ fields: value.selected_fields, source: value.source_snapshot, additional: value.sources }, null, 2)}</pre></details></article>)}
      {data.next_before_version != null && <Button type="button" size="sm" variant="outline" disabled={busy || disabled} onClick={() => void act(() => read(Number(data.next_before_version)))}>更早反馈</Button>}
    </>}
  </details>;
}
