"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { useProductWorkScope } from "./product-work-scope";
import { EvidencePicker } from "./evidence-picker";
import { ProductRequestError, request, type Evidence, type EvidenceContent, type ProductCatalog, type SourceRef, type Workspace } from "./product-work-api";

const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const groups = { target_users: "目标用户", customer_problems: "客户问题", use_environments: "使用环境", buying_criteria: "购买标准", unmet_needs: "未满足需求" };
const parameters = { potential_customers: "潜在客户数", annual_units_per_customer: "每客户年购买量", unit_price: "每件单价", serviceable_share: "可服务比例（0–1）", obtainable_share: "SAM 中可获取比例（0–1）" };
type Group = keyof typeof groups;
type ParameterKey = keyof typeof parameters;
export type Fact = { text: string; fact_kind: "hypothesis" | "observed" | "derived"; sources: SourceRef[]; approval: null; derivation_version: string | null };
export const emptyFact = (): Fact => ({ text: "", fact_kind: "hypothesis", sources: [], approval: null, derivation_version: null });
type Parameter = { lower: string | null; upper: string | null; basis: Fact };
type Sizing = Record<ParameterKey, Parameter> & { horizon_year: number; currency: string; population_unit: string; boundary: string };
type Outcome = { statement: string; metric_key: string; unit: string; baseline_value: string | null; target_value: string | null; measurement_method: string; window: string; sources: SourceRef[] };
export type Draft = Record<Group, Fact[]> & { title: string; product_line_id: string | null; supersedes_id: string | null; job_to_be_done: Fact; outcome: Outcome; sizing_inputs: Sizing; revision_reason: string };
type Interval = { lower: string; upper: string } | null;
export type SizingResult = { horizon_year: number; currency: string; boundary: string; population_unit: string; policy_version: string; estimates: Record<string, { annual_units: Interval; annual_revenue: Interval; units_formula: string; revenue_formula: string }>; unknown_parameters: ParameterKey[]; hypothesis_parameters: ParameterKey[]; interpretation: string };
export type Segment = Draft & { id: string; source_finding_id?: string | null; version: number; created_at: string; is_latest: boolean; source_warnings: string[]; sizing_result: SizingResult };
const emptyDraft = (): Draft => ({
  title: "", product_line_id: null, supersedes_id: null, job_to_be_done: emptyFact(), revision_reason: "",
  target_users: [emptyFact()], customer_problems: [emptyFact()], use_environments: [emptyFact()], buying_criteria: [emptyFact()], unmet_needs: [emptyFact()],
  outcome: { statement: "", metric_key: "", unit: "", baseline_value: null, target_value: null, measurement_method: "", window: "", sources: [] },
  sizing_inputs: { horizon_year: new Date().getFullYear(), currency: "", population_unit: "", boundary: "", ...Object.fromEntries(Object.keys(parameters).map((key) => [key, { lower: null, upper: null, basis: emptyFact() }])) } as Sizing,
});

export function ReferenceEditor({ refs, evidence, onChange }: { refs: SourceRef[]; evidence: Evidence[]; onChange: (refs: SourceRef[]) => void }) {
  const unavailable = refs.filter((ref) => !evidence.some((source) => source.id === ref.ref_id));
  return <div className="space-y-1"><EvidencePicker options={evidence} selected={refs.map((ref) => ref.ref_id)} onChange={(ids) => onChange([...unavailable, ...evidence.filter((source) => ids.includes(source.id)).map((source) => source.reference)])} />{unavailable.map((ref) => <p className="text-xs" key={ref.ref_id}>保留历史引用 {ref.ref_id} <Button type="button" variant="ghost" size="sm" onClick={() => onChange(refs.filter((item) => item.ref_id !== ref.ref_id))}>移除引用</Button></p>)}</div>;
}

export function FactEditor({ label, value, evidence, onChange }: { label: string; value: Fact; evidence: Evidence[]; onChange: (fact: Fact) => void }) {
  return <div className="space-y-2 rounded-md border p-3"><label className="block text-sm">{label}<textarea required maxLength={2048} className={field} value={value.text} onChange={(event) => onChange({ ...value, text: event.target.value })} /></label><label className="block text-sm">依据类型<select className={field} value={value.fact_kind} onChange={(event) => onChange({ ...value, fact_kind: event.target.value as Fact["fact_kind"], derivation_version: event.target.value === "derived" ? value.derivation_version ?? "" : null })}><option value="hypothesis">待验证假设</option><option value="observed">来源观察</option><option value="derived">推导结论</option></select></label>{value.fact_kind === "derived" && <label className="block text-sm">推导方法 / 版本标识<input required pattern={"[a-zA-Z0-9_.:\\-]+"} maxLength={128} className={field} value={value.derivation_version ?? ""} onChange={(event) => onChange({ ...value, derivation_version: event.target.value })} /></label>}<ReferenceEditor refs={value.sources} evidence={evidence} onChange={(sources) => onChange({ ...value, sources })} />{value.fact_kind !== "hypothesis" && value.sources.length === 0 && <p className="text-xs text-destructive">观察和推导须选择证据快照。</p>}</div>;
}

export function Estimates({ result }: { result: SizingResult }) {
  const interval = (value: Interval) => value === null ? "未知" : value.lower === value.upper ? value.lower : `${value.lower} ～ ${value.upper}`;
  const formula = (value: string) => value.split(" × ").map((key) => parameters[key as ParameterKey] ?? key).join(" × ");
  return <div className="space-y-2 text-sm"><p>{result.horizon_year} 年 · {result.boundary} · 客户计量：{result.population_unit}</p><div className="overflow-x-auto"><table className="w-full text-left"><thead><tr><th className="p-2">市场层级</th><th className="p-2">年购买件数</th><th className="p-2">年金额（{result.currency}）</th></tr></thead><tbody>{Object.entries(result.estimates).map(([key, value]) => <tr className="border-t" key={key}><th className="p-2">{key.toUpperCase()}</th><td className="p-2">{interval(value.annual_units)}</td><td className="p-2">{interval(value.annual_revenue)}</td></tr>)}</tbody></table></div>{result.unknown_parameters.length > 0 && <p>未知参数：{result.unknown_parameters.map((key) => parameters[key]).join("、")}</p>}{result.hypothesis_parameters.length > 0 && <p>假设参数：{result.hypothesis_parameters.map((key) => parameters[key]).join("、")}</p>}<p className="text-xs text-muted-foreground">{result.interpretation}</p><details><summary className="cursor-pointer">计算公式与版本</summary><p>{result.policy_version}</p>{Object.entries(result.estimates).map(([key, value]) => <p className="mt-1" key={key}>{key.toUpperCase()} 年件数 = {formula(value.units_formula)}；年金额 = {formula(value.revenue_formula)}</p>)}</details></div>;
}

export function SegmentForm({ candidate, onReview, initial, workspace, catalog, evidence, base, onSaved, onCancel, onAuthorityLost, onPendingChange }: { candidate?: Draft; onReview?: (draft: Draft) => void; initial: Segment | null; workspace: Workspace; catalog: ProductCatalog; evidence: Evidence[]; base: string; onSaved: () => void; onCancel: () => void; onAuthorityLost?: (message: string) => void; onPendingChange?: (pending: boolean) => void }) {
  const [draft, setDraft] = useState<Draft>(() => {
    if (candidate) return candidate;
    if (!initial) return emptyDraft();
    const { statement, metric_key, unit, baseline_value, target_value, measurement_method, window, sources } = initial.outcome;
    return { ...Object.fromEntries(Object.keys(groups).map((key) => [key, initial[key as Group]])), title: initial.title, product_line_id: initial.product_line_id, supersedes_id: initial.id, job_to_be_done: initial.job_to_be_done, outcome: { statement, metric_key, unit, baseline_value, target_value, measurement_method, window, sources }, sizing_inputs: initial.sizing_inputs, revision_reason: "" } as Draft;
  });
  const [preview, setPreview] = useState<{ input: string; result: SizingResult } | null>(null);
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const lastRequest = useRef({ body: "", id: "" });
  const [writePending, setWritePending] = useState<(Draft & { request_id: string }) | null>(null);
  const originalWrite = useRef<(Draft & { request_id: string }) | null>(null), pendingCallback = useRef(onPendingChange);
  useEffect(() => { pendingCallback.current = onPendingChange; }, [onPendingChange]);
  const live = useRef(true), operation = useRef(false);
  useEffect(() => { live.current = true; return () => { live.current = false; if (originalWrite.current) { originalWrite.current = null; pendingCallback.current?.(false); } }; }, []);
  const fail = (failure: unknown) => {
    if (!live.current) return;
    const message = failure instanceof Error ? failure.message : "市场记录暂不可用";
    setError(message);
    if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) { setPreview(null); onAuthorityLost?.(message); }
  };
  const signature = JSON.stringify(draft.sizing_inputs);
  const canWrite = workspace.can_contribute && (!draft.product_line_id || catalog.line_access[draft.product_line_id]?.can_contribute === true);
  const releaseWrite = () => { originalWrite.current = null; setWritePending(null); pendingCallback.current?.(false); };
  async function save(retry = false) {
    if (!live.current || operation.current || !canWrite || (!retry && originalWrite.current)) return;
    let body = originalWrite.current;
    if (!body) {
      if (retry) return;
      const serialized = JSON.stringify(draft);
      if (lastRequest.current.body !== serialized) lastRequest.current = { body: serialized, id: crypto.randomUUID() };
      body = JSON.parse(JSON.stringify({ ...draft, request_id: lastRequest.current.id })) as Draft & { request_id: string };
      originalWrite.current = body; setWritePending(body); pendingCallback.current?.(true);
    }
    operation.current = true; setBusy(true); setError(null);
    try {
      await request(`${base}/market-segments`, "POST", body);
      if (!live.current) return;
      releaseWrite(); onSaved();
    } catch (failure) {
      if (!live.current) return;
      if (failure instanceof ProductRequestError && failure.status < 500 && ![408, 429].includes(failure.status)) releaseWrite();
      fail(failure);
    } finally { if (live.current) { operation.current = false; setBusy(false); } }
  }
  const setSizing = (value: Partial<Sizing>) => setDraft({ ...draft, sizing_inputs: { ...draft.sizing_inputs, ...value } });
  const setOutcome = (value: Partial<Outcome>) => setDraft({ ...draft, outcome: { ...draft.outcome, ...value } });
  return <form className="space-y-4 rounded-lg border p-4" onSubmit={(event) => {
    event.preventDefault(); if (onReview) { onReview(draft); return; } void save();
  }}><h3 className="font-semibold">{candidate ? "核对市场细分候选" : initial ? `追加 v${initial.version + 1} 修订` : "新建市场细分"}</h3><fieldset disabled={busy || !!writePending} className="space-y-4">
    <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">细分名称<input required maxLength={512} className={field} value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /></label><label className="text-sm">工作归属<select disabled={!!initial || !!candidate} className={field} value={draft.product_line_id ?? ""} onChange={(event) => setDraft({ ...draft, product_line_id: event.target.value || null })}><option value="">市场空间共同研究</option>{catalog.nodes.filter((node) => node.level === "line" && (catalog.line_access[node.id]?.can_contribute || node.id === draft.product_line_id)).map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}</select></label></div>
    <FactEditor label="用户要完成的任务（JTBD）" value={draft.job_to_be_done} evidence={evidence} onChange={(job_to_be_done) => setDraft({ ...draft, job_to_be_done })} />
    {(Object.keys(groups) as Group[]).map((key) => <details key={key} open className="space-y-2"><summary className="cursor-pointer font-medium">{groups[key]}</summary>{draft[key].map((fact, index) => <div key={index} className="space-y-1"><FactEditor label={`${groups[key]} ${index + 1}`} value={fact} evidence={evidence} onChange={(value) => setDraft({ ...draft, [key]: draft[key].map((item, i) => i === index ? value : item) })} />{draft[key].length > 1 && <Button type="button" size="sm" variant="ghost" onClick={() => setDraft({ ...draft, [key]: draft[key].filter((_, i) => i !== index) })}>移除此条</Button>}</div>)}<Button type="button" size="sm" variant="outline" disabled={draft[key].length >= 30} onClick={() => setDraft({ ...draft, [key]: [...draft[key], emptyFact()] })}>添加{groups[key]}</Button></details>)}
    <section className="space-y-3"><h4 className="font-semibold">希望达成的可衡量结果</h4><div className="grid gap-3 sm:grid-cols-2">{([["statement", "目标结果"], ["metric_key", "指标标识（英文）"], ["unit", "单位"], ["measurement_method", "测量方法"], ["window", "测量时间范围"]] as const).map(([key, label]) => <label className="text-sm" key={key}>{label}<input required maxLength={key === "metric_key" ? 128 : key === "unit" ? 64 : 2048} pattern={key === "metric_key" ? "[a-zA-Z0-9_.:\\-]+" : undefined} className={field} value={draft.outcome[key]} onChange={(event) => setOutcome({ [key]: event.target.value })} /></label>)}{([["baseline_value", "现状基线（未知留空）"], ["target_value", "期望目标（待定留空）"]] as const).map(([key, label]) => <label className="text-sm" key={key}>{label}<input type="number" step="any" className={field} value={draft.outcome[key] ?? ""} onChange={(event) => setOutcome({ [key]: event.target.value || null })} /></label>)}</div><p className="text-xs text-muted-foreground">现状数值须引用证据；期望目标是待达成的结果。</p><ReferenceEditor refs={draft.outcome.sources} evidence={evidence} onChange={(sources) => setOutcome({ sources })} /></section>
    <section className="space-y-3"><h4 className="font-semibold">市场规模区间</h4><p className="text-sm text-muted-foreground">点估计的上下界填相同值；未知参数两格均留空，并说明缺失信息。比例以 0–1 填写。</p><div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">估计年份<input required type="number" min={2000} max={2100} className={field} value={draft.sizing_inputs.horizon_year || ""} onChange={(event) => setSizing({ horizon_year: Number(event.target.value) })} /></label>{([["currency", "币种（三位代码）"], ["population_unit", "客户计量单位（人 / 家等）"], ["boundary", "地域、用户与产品范围"]] as const).map(([key, label]) => <label className="text-sm" key={key}>{label}<input required pattern={key === "currency" ? "[A-Z]{3}" : undefined} maxLength={key === "currency" ? 3 : 2048} className={field} value={draft.sizing_inputs[key]} onChange={(event) => setSizing({ [key]: key === "currency" ? event.target.value.toUpperCase() : event.target.value })} /></label>)}</div>
      {(Object.keys(parameters) as ParameterKey[]).map((key) => { const parameter = draft.sizing_inputs[key]; return <details open key={key} className="space-y-2 rounded-md border p-3"><summary className="cursor-pointer font-medium">{parameters[key]}</summary><div className="grid gap-3 sm:grid-cols-2">{(["lower", "upper"] as const).map((bound) => <label className="text-sm" key={bound}>{bound === "lower" ? "下界" : "上界"}<input type="number" min={0} max={key.endsWith("share") ? 1 : undefined} step="any" className={field} value={parameter[bound] ?? ""} onChange={(event) => setSizing({ [key]: { ...parameter, [bound]: event.target.value || null } })} /></label>)}</div><FactEditor label="数值依据 / 缺失原因" value={parameter.basis} evidence={evidence} onChange={(basis) => setSizing({ [key]: { ...parameter, basis } })} /></details>; })}
      <Button type="button" variant="outline" onClick={() => { if (operation.current || originalWrite.current) return; operation.current = true; setBusy(true); setError(null); setPreview(null); const input = signature; void request<SizingResult>(`${base}/market-sizing`, "POST", draft.sizing_inputs).then((result) => { if (live.current) setPreview({ input, result }); }).catch(fail).finally(() => { if (live.current) { operation.current = false; setBusy(false); } }); }}>预览当前参数计算结果</Button>{preview && preview.input === signature && <div className="space-y-2 rounded-md bg-muted p-3"><p className="font-medium">尚未保存 · 此处只计算输入参数</p><Estimates result={preview.result} /></div>}
    </section>
    <label className="block text-sm">记录 / 修订原因<textarea required maxLength={2048} className={field} value={draft.revision_reason} onChange={(event) => setDraft({ ...draft, revision_reason: event.target.value })} /></label>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}<div className="flex gap-2"><Button disabled={!canWrite}>{candidate ? "保存此条核对内容" : "保存完整版本"}</Button><Button type="button" variant="outline" onClick={() => { if (!operation.current && !originalWrite.current) onCancel(); }}>取消</Button></div>
  </fieldset>{writePending && <div className="space-y-2 text-sm"><p role="status">市场记录保存结果尚未确认，已保留原内容和请求编号。请先重试原保存，再修改或离开。</p><Button type="button" variant="outline" disabled={busy || !canWrite} onClick={() => void save(true)}>按原请求重试保存</Button></div>}</form>;
}

function SegmentDetails({ segment, evidence, onRead }: { segment: Segment; evidence: Evidence[]; onRead: (ref: SourceRef) => void }) {
  const kind = { observed: "来源观察", derived: "推导结论", hypothesis: "待验证假设" };
  const refs = (sources: SourceRef[]) => <ul className="space-y-1 text-xs">{sources.map((ref) => <li className="break-all" key={ref.ref_id}>{evidence.find((item) => item.id === ref.ref_id)?.name ?? "历史证据"} · {new Date(ref.as_of).toLocaleDateString()} <Button size="sm" variant="ghost" onClick={() => onRead(ref)}>查看正文</Button></li>)}</ul>;
  const fact = (value: Fact) => <div className="space-y-1"><p>{value.text} <span className="text-xs text-muted-foreground">{kind[value.fact_kind]}{value.derivation_version ? ` · ${value.derivation_version}` : ""}</span></p>{refs(value.sources)}</div>;
  return <details className="space-y-3"><summary className="cursor-pointer text-sm">查看用户、目标和计算依据</summary><div className="space-y-3 text-sm"><h4 className="font-medium">用户任务（JTBD）</h4>{fact(segment.job_to_be_done)}{(Object.keys(groups) as Group[]).map((key) => <section key={key} className="space-y-2"><h4 className="font-medium">{groups[key]}</h4>{segment[key].map((value, i) => <div key={i}>{fact(value)}</div>)}</section>)}<section className="space-y-1"><h4 className="font-medium">期望结果</h4><p>{segment.outcome.statement}</p><p>{segment.outcome.metric_key}：{segment.outcome.baseline_value ?? "未知基线"} → {segment.outcome.target_value ?? "目标待定"} {segment.outcome.unit}</p><p>方法：{segment.outcome.measurement_method} · 时间：{segment.outcome.window}</p>{refs(segment.outcome.sources)}</section>{(Object.keys(parameters) as ParameterKey[]).map((key) => <section className="space-y-1" key={key}><h4 className="font-medium">{parameters[key]}：{segment.sizing_inputs[key].lower === null ? "未知" : `${segment.sizing_inputs[key].lower} ～ ${segment.sizing_inputs[key].upper}`}</h4>{fact(segment.sizing_inputs[key].basis)}</section>)}</div></details>;
}

type MarketProps = { base: string; workspace: Workspace; catalog: ProductCatalog; evidence: Evidence[]; onAuthorityLost?: (message: string) => void; onPendingChange?: (pending: boolean) => void };
export function MarketSegments(props: MarketProps) { return <MarketSegmentsPanel key={props.base} {...props}/>; }
function MarketSegmentsPanel({ base, workspace, catalog, evidence, onAuthorityLost, onPendingChange }: MarketProps) {
  const [items, setItems] = useState<Segment[] | null>(null); const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Segment | null | undefined>(undefined);
  const [history, setHistory] = useState(false); const { scope, setScope, shared: sharedScope } = useProductWorkScope();
  const [content, setContent] = useState<EvidenceContent | null>(null); const [reading, setReading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [writePending, setWritePending] = useState(false); const writeLock = useRef(false);
  const pendingChanged = useCallback((pending: boolean) => { writeLock.current = pending; setWritePending(pending); onPendingChange?.(pending); }, [onPendingChange]);
  const live = useRef(true), readRevision = useRef(0), listRevision = useRef(0), readLock = useRef(false);
  useEffect(() => { live.current = true; return () => { live.current = false; readRevision.current += 1; listRevision.current += 1; }; }, []);
  const authorityLost = useCallback((message: string) => { readRevision.current += 1; listRevision.current += 1; readLock.current = false; setContent(null); setReading(false); setLoading(false); setItems(null); setEditing(undefined); setError(message); onAuthorityLost?.(message); }, [onAuthorityLost]);
  const fail = useCallback((failure: unknown) => { const message = failure instanceof Error ? failure.message : "细分资料暂不可用"; if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) authorityLost(message); else setError(message); }, [authorityLost]);
  const scrolled = useRef("");
  const fetchRows = useCallback(async () => {
    const data = await request<{ items: Segment[] }>(`${base}/market-segments`);
    const target = window.location.hash.match(/^#segment-([0-9a-f-]{36})$/i)?.[1];
    if (target && !data.items.some(item => item.id === target)) data.items.unshift(await request<Segment>(`${base}/market-segments/${target}`));
    return { items: data.items, showHistory: new URLSearchParams(window.location.search).get("history") === "1" || data.items.some(item => item.id === target && !item.is_latest) };
  }, [base]);
  const reload = async () => { if (writeLock.current) return; const current = ++listRevision.current; setLoading(true); setError(null); try { const data = await fetchRows(); if (live.current && current === listRevision.current) { setItems(data.items); if (data.showHistory) setHistory(true); } } catch (failure) { if (live.current && current === listRevision.current) fail(failure); } finally { if (live.current && current === listRevision.current) setLoading(false); } };
  useEffect(() => { let live = true; const current = ++listRevision.current; void fetchRows().then(data => { if (live && current === listRevision.current) { setItems(data.items); if (data.showHistory) setHistory(true); } }).catch(failure => { if (live && current === listRevision.current) fail(failure); }); return () => { live = false; }; }, [fetchRows, fail]);
  useEffect(() => {
    if (!items) return;
    const id = window.location.hash.slice(1);
    if (/^segment-[0-9a-f-]{36}$/i.test(id) && scrolled.current !== id) { const element = document.getElementById(id); if (element) { element.scrollIntoView({ block: "start" }); scrolled.current = id; } }
  }, [items, history, scope]);
  const read = (ref: SourceRef) => { if (readLock.current) return; readLock.current = true; const current = ++readRevision.current; setReading(true); setContent(null); setError(null); void request<EvidenceContent>(`${base}/evidence/${ref.ref_id}/content`).then(value => { if (!live.current || current !== readRevision.current) return; if (value.snapshot_id !== ref.ref_id || value.content_digest !== ref.digest) throw new Error("正文与固定引用版本不一致，请重新核对来源"); setContent(value); }).catch(failure => { if (live.current && current === readRevision.current) fail(failure); }).finally(() => { if (live.current && current === readRevision.current) { readLock.current = false; setReading(false); } }); };
  const closeContent = () => { readRevision.current += 1; readLock.current = false; setContent(null); setReading(false); };
  return <section className="space-y-4"><div><h3 className="font-semibold">市场细分与用户任务</h3><p className="mt-1 text-sm text-muted-foreground">从用户问题形成可衡量目标；市场规模保留参数、假设和来源，每次修订保存完整版本。</p></div><div className="flex flex-wrap items-end gap-3">{workspace.can_contribute && editing === undefined && <Button disabled={writePending} onClick={() => { if (!writeLock.current) setEditing(null); }}>新建细分</Button>}<Button variant="outline" disabled={loading || writePending} onClick={() => void reload()}>刷新细分</Button>{!sharedScope && <label className="text-sm">工作归属<select disabled={writePending} className={field} value={scope} onChange={(event) => { if (writeLock.current) return; closeContent(); setEditing(undefined); setScope(event.target.value); }}><option value="all">全部可访问范围</option><option value="">市场空间共同研究</option>{catalog.nodes.filter((node) => node.level === "line").map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}</select></label>}<label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={writePending} checked={history} onChange={(event) => setHistory(event.target.checked)} />显示历史版本</label></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{reading && <div className="flex items-center gap-2"><p role="status" className="text-sm">正在读取证据正文…</p><Button variant="ghost" size="sm" onClick={closeContent}>取消读取正文</Button></div>}{content && <section className="space-y-2 rounded-md border p-3"><div className="flex items-center justify-between"><h4 className="font-medium">证据快照原文</h4><Button size="sm" variant="ghost" onClick={closeContent}>关闭正文</Button></div><details className="text-xs text-muted-foreground"><summary className="cursor-pointer">技术核对</summary><p className="mt-2 break-all">快照：{content.snapshot_id}<br/>完整性摘要：{content.content_digest}</p></details><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words text-sm">{content.content}</pre></section>}
    {editing !== undefined && <SegmentForm key={editing?.id ?? "new"} initial={editing} workspace={workspace} catalog={catalog} evidence={evidence} base={base} onPendingChange={pendingChanged} onAuthorityLost={authorityLost} onCancel={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); void reload(); }} />}
    {items === null ? <p className="text-sm">{error ? "细分列表暂不可用，可刷新重试。" : "正在加载细分…"}</p> : items.filter((item) => (history || item.is_latest) && (scope === "all" || (item.product_line_id ?? "") === scope)).length === 0 ? <p className="text-sm text-muted-foreground">此范围尚无市场细分记录。</p> : items.filter((item) => (history || item.is_latest) && (scope === "all" || (item.product_line_id ?? "") === scope)).map((segment) => <article id={`segment-${segment.id}`} key={segment.id} className="space-y-3 rounded-lg border p-4"><h4 className="font-semibold">{segment.title} · v{segment.version}{segment.is_latest ? "" : " · 历史版本"}</h4><p className="text-xs text-muted-foreground">{segment.product_line_id ? catalog.nodes.find((node) => node.id === segment.product_line_id)?.name ?? "产品线" : "市场空间共同研究"} · {new Date(segment.created_at).toLocaleString()} · {segment.revision_reason}</p>{segment.source_finding_id && <p className="text-xs text-muted-foreground">来源：AI 候选，经人工核对接受并独立应用。</p>}{segment.source_warnings.map((warning) => <p className="text-sm text-amber-700 dark:text-amber-400" key={warning}>{warning}</p>)}<Estimates result={segment.sizing_result} /><SegmentDetails segment={segment} evidence={evidence} onRead={read} />{segment.is_latest && workspace.can_contribute && (!segment.product_line_id || catalog.line_access[segment.product_line_id]?.can_contribute) && <Button size="sm" variant="outline" disabled={editing !== undefined} onClick={() => setEditing(segment)}>追加修订</Button>}</article>)}
    <p className="text-xs text-muted-foreground">显示最近 100 个可访问版本及通过链接打开的历史细分。可在「机会树」展开候选方案，再到「实验 / 决策」记录验证过程。</p>
  </section>;
}
