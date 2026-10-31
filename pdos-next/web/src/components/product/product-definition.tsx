"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowClockwise, FileText, Plus, Trash } from "@phosphor-icons/react";
import { originalLocation } from "@/lib/original-location";
import { numericShapeProblem } from "@/lib/spec-bound-values";
import { Button } from "@/components/ui/button";
import { availabilityLabels, isLatestDefinition, natureLabels, plainReference, referenceKey, sourceLines, specificationValue, type DefinitionApi, type DefinitionList, type DefinitionPayload, type DefinitionReference, type DefinitionRevision, type DefinitionSource, type DefinitionSpec } from "@/lib/product-view";
import { DefinitionDraftActions } from "./definition-draft-actions";
import { ReadingPanel, ReadingRecord } from "./reading";

type Product = { id: string; name: string; purpose: string; revision: number };
type Props = { compact?: boolean; product: Product; principalId: string; sources: DefinitionSource[]; api: DefinitionApi; onSaved: () => void | Promise<void>; onAccessDenied?: () => void };
type Pending = { command_id: string; idempotency_key: string; operation: "product.definition.draft"; product_id: string; expected_revision: number; source_read_set: { artifact_id: string; expected_revision: number }[]; payload: DefinitionPayload };
type LocalDraft = { payload: DefinitionPayload; pending: Pending | null };
const listFields = [ ["use_cases", "使用场景"], ["requirements", "要求"], ["constraints", "成本 / 市场 / 专业约束"], ["unknowns", "仍待确认的事项"], ["exclusions", "本轮排除范围"] ] as const;
const emptyPayload = (product: Product): DefinitionPayload => ({ title: `${product.name} · 定义草稿`, purpose: product.purpose, visibility: "private", parent_definition_id: null, expected_parent_revision: null, use_cases: [], requirements: [], constraints: [], unknowns: [], exclusions: [], sources: [], specs: [], change_reason: "" });
const nullable = (value: string) => value.trim() || null;
const lines = (value: string) => value.split("\n");
const draftList = (values: string[]) => values.map(value => value.trim()).filter(Boolean);
const knownError = (error: unknown) => error as Error & { code?: string; status?: number };
const pathLabels: Record<string, string> = { title: "名称", purpose: "用途", use_cases: "场景", requirements: "要求", constraints: "约束", unknowns: "未知事项", exclusions: "排除范围", visibility: "受众", sources: "来源引用" };

function restoredDraft(value: unknown): LocalDraft | null {
  if (!value || typeof value !== "object") return null;
  const local = value as Record<string, unknown>;
  if (!local.payload || typeof local.payload !== "object") return null;
  const draft = local.payload as Record<string, unknown>;
  if (!["title", "purpose", "change_reason"].every(key => typeof draft[key] === "string")) return null;
  if (!["private", "category", "audience"].includes(String(draft.visibility))) return null;
  if (!listFields.every(([key]) => Array.isArray(draft[key]) && (draft[key] as unknown[]).every(item => typeof item === "string"))) return null;
  if (!Array.isArray(draft.sources) || !Array.isArray(draft.specs)) return null;
  const validRef = (item: unknown) => !!item && typeof item === "object" && typeof (item as DefinitionReference).artifact_id === "string" && typeof (item as DefinitionReference).quote === "string" && Number.isInteger((item as DefinitionReference).line) && Number.isInteger((item as DefinitionReference).expected_revision);
  if (!draft.sources.every(validRef)) return null;
  if (!draft.specs.every(item => item && typeof item === "object" && typeof item.key === "string" && typeof item.parameter === "string" && typeof item.reason === "string" && ["known", "unknown", "conflicted", "not_applicable"].includes(item.availability) && ["number", "range", "text"].includes(item.value_type) && Array.isArray(item.sources) && item.sources.every(validRef) && Array.isArray(item.test_conditions) && item.test_conditions.every((entry: unknown) => typeof entry === "string"))) return null;
  if (local.pending && (typeof local.pending !== "object" || (local.pending as Pending).operation !== "product.definition.draft" || typeof (local.pending as Pending).idempotency_key !== "string" || typeof (local.pending as Pending).command_id !== "string")) return null;
  return { payload: draft as unknown as DefinitionPayload, pending: local.pending as Pending | null ?? null };
}

function inputProblem(draft: DefinitionPayload): string | null {
  if (draft.title.trim().length < 2 || draft.purpose.trim().length < 3 || draft.change_reason.trim().length < 3) return "请填写定义名称、用途和至少3字的保存原因。";
  if (!draft.use_cases.some(item => item.trim())) return "请至少填写一个真实使用场景。";
  if (!draft.sources.length) return "请先选择至少一条精确原文依据。";
  for (const spec of draft.specs) {
    if (!spec.parameter.trim() || !spec.reason.trim()) return `规格 ${spec.key} 的参数和依据说明尚未齐备。`;
    if (!spec.sources.length) return `规格 ${spec.parameter} 需要至少一条已选原文出处。`;
    if (spec.availability === "known") {
      if (spec.value_type === "text" && !spec.text?.trim()) return `规格 ${spec.parameter} 需要文字目标。`;
      if (spec.value_type !== "text" && !spec.unit?.trim()) return `规格 ${spec.parameter} 需要明确单位。`;
      if (["number", "range"].includes(spec.value_type)) {
        const problem = numericShapeProblem(spec.value_type, spec.value, spec.lower, spec.upper, spec.text);
        if (problem) return `规格 ${spec.parameter}：${problem}`;
      }
    }
  }
  return null;
}

function changeValue(value: unknown): ReactNode {
  if (value === null || value === undefined) return <span className="subtle">未记录</span>;
  if (typeof value === "string") return value === "private" ? "仅本人" : value === "category" ? "品类授权成员" : value === "audience" ? "指定评审人" : value;
  if (Array.isArray(value)) return <ul className="space-y-1">{value.map((item, index) => <li key={index}>{changeValue(item)}</li>)}</ul>;
  if (typeof value === "object") {
    const item = value as Record<string, unknown>;
    if (typeof item.parameter === "string") return <div className="space-y-1"><p>{item.parameter} · {specificationValue(item as unknown as DefinitionSpec)}</p><p className="subtle">条件：{Array.isArray(item.test_conditions) ? item.test_conditions.join("；") || "未知" : "未知"}</p><p className="subtle">方法：{String(item.method ?? "未知")} · 判据：{String(item.acceptance_criterion ?? "未知")}</p><p className="subtle">说明：{String(item.reason ?? "未知")}</p></div>;
    if (typeof item.quote === "string") return <p>原文第{String(item.line)}行：{item.quote}</p>;
  }
  return String(value);
}

export function ProductDefinition(props: Props) {
  return <DefinitionPanel key={`${props.principalId}:${props.product.id}`} {...props}/>;
}

function DefinitionPanel({ compact = false, product, principalId, sources, api, onSaved, onAccessDenied }: Props) {
  const storageKey = `pdos-next:definition:${principalId}:${product.id}`;
  const [items, setItems] = useState<DefinitionRevision[]>([]);
  const [payload, setPayload] = useState(() => emptyPayload(product));
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [editorOpen, setEditorOpen] = useState<boolean | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [unavailable, setUnavailable] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [sourceId, setSourceId] = useState(sources.find(source => source.status === "active")?.id ?? "");
  const [selectedLine, setSelectedLine] = useState(1);
  const [quote, setQuote] = useState("");
  const alive = useRef(true);
  const writing = useRef(false);
  const source = sources.find(item => item.id === sourceId);
  const selectedSources = payload.sources.map(ref => sources.find(item => item.id === ref.artifact_id));
  const privateSource = selectedSources.some(item => item?.visibility !== "category");
  const invalidSources = payload.sources.some(ref => !sources.some(item => item.id === ref.artifact_id && item.revision === ref.expected_revision && item.status === "active"));
  const latest = items.find(item => item.variant_id === null && isLatestDefinition(item, items));

  const refresh = useCallback(async () => {
    const result = await api<DefinitionList>(`v1/products/${product.id}/definitions`);
    if (!alive.current) return;
    setItems(result.items); setUnavailable(result.unavailable_count); setHasMore(result.has_more); setLoading(false);
  }, [api, product.id]);
  useEffect(() => {
    alive.current = true;
    void refresh().catch(failure => {
      if (alive.current) { setError(failure.message); setLoading(false); }
    });
    void Promise.resolve().then(() => {
      if (!alive.current) return;
      try {
        const saved = restoredDraft(JSON.parse(localStorage.getItem(storageKey) ?? "null"));
        if (saved) { setPayload(saved.payload); setPending(saved.pending); }
      } catch { /* Local storage is optional; server remains authoritative. */ }
      setReady(true);
    });
    return () => { alive.current = false; };
  }, [refresh, storageKey]);

  function store(next: DefinitionPayload, waiting: Pending | null) {
    try { localStorage.setItem(storageKey, JSON.stringify({ payload: next, pending: waiting })); } catch { /* Saving online remains available. */ }
  }
  function edit(next: DefinitionPayload) { setPayload(next); store(next, pending); }
  function changeSpec(index: number, patch: Partial<DefinitionSpec>) {
    edit({ ...payload, specs: payload.specs.map((spec, position) => index === position ? { ...spec, ...patch } : spec) });
  }
  function clearPrivate() {
    setItems([]); setPayload(emptyPayload(product)); setEditorOpen(false);
    setSourceId(""); setQuote(""); setUnavailable(0);
    if (!pending) localStorage.removeItem(storageKey);
    onAccessDenied?.();
  }
  async function definitionSaved() {
    await refresh(); await onSaved();
  }
  function addReference() {
    if (!source || source.status !== "active" || !quote.trim()) return;
    const ref = { artifact_id: source.id, expected_revision: source.revision, line: selectedLine, quote: quote.trim() };
    if (payload.sources.some(item => referenceKey(item) === referenceKey(ref))) return;
    edit({ ...payload, visibility: source.visibility !== "category" ? "private" : payload.visibility, sources: [...payload.sources, ref] });
  }
  function removeReference(ref: DefinitionReference) {
    const key = referenceKey(ref);
    edit({ ...payload, sources: payload.sources.filter(item => referenceKey(item) !== key), specs: payload.specs.map(spec => ({ ...spec, sources: spec.sources.filter(item => referenceKey(item) !== key) })) });
  }
  function addSpec() {
    let key = `spec-${payload.specs.length + 1}`;
    while (payload.specs.some(spec => spec.key === key)) key += "-new";
    edit({ ...payload, specs: [...payload.specs, { key, parameter: "", value_type: "number", availability: "unknown", value: null, lower: null, upper: null, text: null, unit: null, tolerance: null, test_conditions: [], method: null, acceptance_criterion: null, nature: "extracted", state: "needs_confirmation", owner_id: null, reason: "", sources: payload.sources.map(plainReference) }] });
  }
  async function submit(original?: Pending) {
    if (writing.current) return;
    if (!original) {
      const problem = inputProblem(payload);
      if (problem) { setError(problem); return; }
    }
    writing.current = true; setBusy(true); setError(""); setNotice("");
    const clean = { ...payload, ...Object.fromEntries(listFields.map(([key]) => [key, draftList(payload[key])])), sources: payload.sources.map(plainReference), specs: payload.specs.map(spec => ({ ...spec, test_conditions: draftList(spec.test_conditions), sources: spec.sources.map(plainReference) })) } as DefinitionPayload;
    const request: Pending = original ?? { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation: "product.definition.draft", product_id: product.id, expected_revision: product.revision, source_read_set: [...new Map(clean.sources.map(ref => [ref.artifact_id, { artifact_id: ref.artifact_id, expected_revision: ref.expected_revision }])).values()], payload: clean };
    setPending(request); store(payload, request);
    let committed = false;
    try {
      const receipt = await api<{ id: string; subject_type: string; subject_id: string }>("v1/commands", request);
      if (!receipt.id || receipt.subject_type !== "definition_revision" || !receipt.subject_id) throw new Error("保存结果尚未确认，请保留原请求重试。");
      if (!alive.current) return;
      committed = true;
      setPending(null); store(payload, null);
      setNotice("新定义草稿已保存，原版本与来源保留。尚未发布或专业确认。");
      await refresh(); await onSaved();
    } catch (failure) {
      if (!alive.current) return;
      const error = knownError(failure);
      if (error.status && error.status < 500) { setPending(null); store(payload, null); }
      if (error.status === 401 || error.status === 403) { setItems([]); }
      setError(committed ? `草稿已保存；最新结果读取失败，可刷新已保存版本。${error.message}` : error.message);
    } finally {
      writing.current = false;
      if (alive.current) setBusy(false);
    }
  }

  const showEditor = !!pending || (editorOpen ?? (!loading && items.length === 0));
  return <section className="min-w-0 space-y-5" aria-label="型号定义">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><p className="subtle">从当前资料形成定义 · 无需建立项目</p><h2 className="mt-1 text-lg font-semibold">型号定义与可测规格</h2></div><div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy || !!pending} aria-expanded={showEditor} aria-controls={`definition-editor-pane-${product.id}`} onClick={() => setEditorOpen(!showEditor)}><Plus/>{showEditor ? "收起编辑" : "编辑定义草稿"}</Button><Button variant="outline" disabled={busy} onClick={() => { setError(""); void refresh().catch(failure => setError(failure.message)); }}><ArrowClockwise/>刷新已保存版本</Button></div></header>
    {error && <p role="alert" className="break-words rounded-lg border border-destructive p-3 text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-border p-3">{notice}</p>}
    {unavailable > 0 && <p className="subtle">{unavailable} 个版本的来源权限需要重核，派生正文已隐藏。</p>}
    {pending && <div className="rounded-lg border border-primary p-4"><p className="mb-2 font-medium">此保存结果仍待确认</p><p className="subtle mb-3">保留原内容与请求编号。重试会核对同一请求，不另建定义。</p><Button disabled={busy} onClick={() => void submit(pending)}>按原请求重试定义保存</Button></div>}
    <div className={showEditor ? "grid min-w-0 items-start gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]" : "min-w-0 max-w-5xl"}>
      <div id={`definition-editor-pane-${product.id}`} hidden={!showEditor}>
      <ReadingPanel title={payload.parent_definition_id ? `续写固定草稿 v${payload.expected_parent_revision}` : "准备首版定义"}>
        <form noValidate id={`definition-editor-${product.id}`} className="min-w-0 scroll-mt-20" onSubmit={event => { event.preventDefault(); void submit(); }}>
          <fieldset disabled={busy || !!pending || !ready} className="min-w-0">
            {latest && <p className="subtle mb-4">已有基础定义 v{latest.revision}。请在已保存版本中修订条目，或填写原因继续下一版草稿。</p>}
            <label>定义名称<input required minLength={2} maxLength={200} value={payload.title} onChange={event => edit({ ...payload, title: event.target.value })}/></label>
            <label>用途<textarea required minLength={3} maxLength={2000} value={payload.purpose} onChange={event => edit({ ...payload, purpose: event.target.value })}/></label>
            {listFields.map(([key, label]) => <label key={key}>{label}（每行一项）<textarea required={key === "use_cases"} maxLength={12000} value={payload[key].join("\n")} onChange={event => edit({ ...payload, [key]: lines(event.target.value) })}/></label>)}
            <details className="mb-5 rounded-lg border border-border p-3" open={payload.sources.length === 0}>
              <summary className="cursor-pointer font-medium">选择精确原文依据 · {payload.sources.length} 条</summary>
              <div className="mt-4"><label>原始资料<select value={sourceId} onChange={event => { setSourceId(event.target.value); setQuote(""); }}><option value="">选择资料</option>{sources.map(item => <option key={item.id} value={item.id} disabled={item.status !== "active"}>{item.title} · v{item.revision}{item.status !== "active" ? " · 已失效" : ""}</option>)}</select></label>
                {source && <div className="mb-3 max-h-52 overflow-auto rounded-lg border border-border p-2">{sourceLines(source.content).map((text, index) => <button type="button" className="source-line" key={index} disabled={source.status !== "active" || !text.trim()} aria-pressed={selectedLine === index + 1 && !!quote && text.includes(quote)} onClick={() => { setSelectedLine(index + 1); setQuote(text.trim().slice(0, 4000)); }}><span className="subtle shrink-0 w-6">{index + 1}</span><span className="min-w-0 break-words">{text || " "}{originalLocation(source, index + 1) && <small className="subtle block">{originalLocation(source, index + 1)}</small>}</span></button>)}</div>}
                <label>精确摘录 · 第 {selectedLine} 行<textarea maxLength={4000} value={quote} onChange={event => setQuote(event.target.value)} placeholder="选择原文行，也可缩小为该行内的准确片段"/></label>
                <Button type="button" variant="outline" disabled={!source || source.status !== "active" || !quote.trim()} onClick={addReference}>加入定义依据</Button>
                <ul className="mt-4 space-y-3">{payload.sources.map(ref => <li key={referenceKey(ref)} className="min-w-0 rounded-lg border border-border p-3"><p className="subtle">{sources.find(item => item.id === ref.artifact_id)?.title ?? "原来源"} · v{ref.expected_revision} · 第{ref.line}行</p><blockquote className="my-2 break-words">{ref.quote}</blockquote><Button type="button" size="sm" variant="ghost" onClick={() => removeReference(ref)}><Trash/>移除此引用</Button></li>)}</ul>
              </div>
            </details>
            <section className="min-w-0 space-y-4 mb-5"><header className="flex items-center justify-between gap-2"><h3 className="font-semibold">规格条目</h3><Button type="button" variant="outline" disabled={payload.specs.length >= 100} onClick={addSpec}><Plus/>新增规格</Button></header><p className="subtle">未知项留空。记录方法和条件不等于测试已执行；草稿条目仍待专业确认。</p>
              {payload.specs.map((spec, index) => <details key={`${index}-${spec.key}`} className="min-w-0 rounded-lg border border-border p-3" open>
                <summary className="cursor-pointer break-words font-medium">{spec.parameter || `新规格 ${index + 1}`} · {availabilityLabels[spec.availability]}</summary>
                <div className="mt-4 min-w-0"><label>规格参数<input required maxLength={200} value={spec.parameter} onChange={event => changeSpec(index, { parameter: event.target.value })}/></label><p className="subtle mb-3">稳定标识 {spec.key}</p>
                  <div className="grid gap-3 sm:grid-cols-2"><label>值类型<select value={spec.value_type} onChange={event => changeSpec(index, { value_type: event.target.value as DefinitionSpec["value_type"], value: null, lower: null, upper: null, text: null, tolerance: null })}><option value="number">数值</option><option value="range">上下限</option><option value="text">文字要求</option></select></label><label>信息状态<select value={spec.availability} onChange={event => changeSpec(index, { availability: event.target.value as DefinitionSpec["availability"], value: null, lower: null, upper: null, text: null, tolerance: null })}>{Object.entries(availabilityLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
                  {spec.availability === "known" && (spec.value_type === "text" ? <label>文字目标<textarea required maxLength={2000} value={spec.text ?? ""} onChange={event => changeSpec(index, { text: nullable(event.target.value) })}/></label> : <><div className="grid gap-3 sm:grid-cols-2">{(spec.value_type === "range" ? ["lower", "upper"] : ["value", "lower", "upper"]).map(key => <label key={key}>{({ lower: "下限", upper: "上限", value: "目标值" } as Record<string, string>)[key]}<input inputMode="decimal" value={spec[key as "value" | "lower" | "upper"] ?? ""} onChange={event => changeSpec(index, { [key]: nullable(event.target.value) })}/></label>)}<label>单位<input required maxLength={80} value={spec.unit ?? ""} onChange={event => changeSpec(index, { unit: nullable(event.target.value) })}/></label><label>允差（未知留空）<input inputMode="decimal" value={spec.tolerance ?? ""} onChange={event => changeSpec(index, { tolerance: nullable(event.target.value) })}/></label></div></>)}
                  <label>测试条件（每行一项）<textarea value={spec.test_conditions.join("\n")} onChange={event => changeSpec(index, { test_conditions: lines(event.target.value) })}/></label><label>判定方法（未知留空）<textarea maxLength={2000} value={spec.method ?? ""} onChange={event => changeSpec(index, { method: nullable(event.target.value) })}/></label><label>验收判据（未知留空）<textarea maxLength={2000} value={spec.acceptance_criterion ?? ""} onChange={event => changeSpec(index, { acceptance_criterion: nullable(event.target.value) })}/></label>
                  <label>事实性质<select value={spec.nature} onChange={event => changeSpec(index, { nature: event.target.value as DefinitionSpec["nature"] })}>{Object.entries(natureLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
                  <label>该条依据 / 未知 / 冲突 / 不适用说明<textarea required maxLength={2000} value={spec.reason} onChange={event => changeSpec(index, { reason: event.target.value })}/></label>
                  <label>本条负责人<select value={spec.owner_id === principalId ? principalId : spec.owner_id ? "other" : ""} onChange={event => changeSpec(index, { owner_id: event.target.value === principalId ? principalId : null })}><option value="">尚未指定</option><option value={principalId}>我负责后续核对</option>{spec.owner_id && spec.owner_id !== principalId && <option value="other">保留原负责人</option>}</select></label>
                  <fieldset className="mb-3 min-w-0"><legend className="mb-2 text-sm font-medium">该条精确出处（至少一条）</legend>{payload.sources.length === 0 && <p className="subtle">先为定义选原文依据。</p>}{payload.sources.map(ref => <label key={referenceKey(ref)} className="flex items-start gap-2 text-sm font-normal"><input type="checkbox" className="!w-auto !inline-block !mt-1 shrink-0" checked={spec.sources.some(item => referenceKey(item) === referenceKey(ref))} onChange={event => changeSpec(index, { sources: event.target.checked ? [...spec.sources, plainReference(ref)] : spec.sources.filter(item => referenceKey(item) !== referenceKey(ref)) })}/><span className="min-w-0 break-words">第{ref.line}行 · {ref.quote}</span></label>)}</fieldset>
                  <Button type="button" variant="ghost" onClick={() => edit({ ...payload, specs: payload.specs.filter((_, position) => position !== index) })}><Trash/>从新草稿移除此条</Button>
                </div>
              </details>)}
            </section>
            <label>草稿受众<select value={payload.visibility} onChange={event => edit({ ...payload, visibility: event.target.value as DefinitionPayload["visibility"] })}><option value="private">仅我可见</option><option value="category" disabled={privateSource || !!(payload.parent_definition_id && items.find(item => item.id === payload.parent_definition_id)?.visibility !== "category")}>品类授权成员</option></select></label>
            {privateSource && <p className="subtle mb-3">含私人来源，整份定义保持仅你可见。</p>}
            <label>保存 / 续版原因<textarea required minLength={3} maxLength={2000} value={payload.change_reason} onChange={event => edit({ ...payload, change_reason: event.target.value })}/></label>
            {invalidSources && <p className="mb-3 text-destructive">所选来源版本已改变或失效，请重新核对引用。</p>}
            <p className="subtle mb-3">未提交输入保存在本机，刷新可继续。保存会创建不可变草稿版本，原版本保持；正式发布尚未开放。</p>
            <Button disabled={busy || !!pending || payload.sources.length === 0 || invalidSources || (!!latest && payload.parent_definition_id !== latest.id)}>{busy ? "正在保存…" : payload.parent_definition_id ? "保存新草稿版本" : "保存首版草稿"}</Button>
          </fieldset>
        </form>
      </ReadingPanel>
      </div>
      <ReadingPanel title="已保存定义" count={items.length}>
        {loading ? <p role="status" className="subtle">正在读取定义版本…</p> : items.length === 0 ? <p className="subtle">还没有可见定义版本。先核对原文，再保存首版草稿。</p> : <div className="space-y-4">{items.map((item, index) => <ReadingRecord key={item.id} id={`definition-${item.id}`} title={`${item.title} · v${item.revision}`} open={index === 0} meta={<><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time> · 草稿 · {item.visibility === "private" ? "仅本人" : item.visibility === "audience" ? "指定评审人" : "品类授权成员"}{item.source_status !== "current" && " · 来源待重核"}</>}>
          <p className="break-words">{item.purpose}</p>{listFields.map(([key, label]) => item[key].length > 0 && <section key={key}><h4 className="subtle mb-1">{label}</h4><ul className="list-disc space-y-1 pl-5">{item[key].map((value, position) => <li className="break-words" key={position}>{value}</li>)}</ul></section>)}
          {item.specs.length > 0 && <section className="space-y-3"><h4 className="font-medium">规格与核对条件</h4>{item.specs.map(spec => <article key={spec.key} className="min-w-0 border-t border-border pt-3"><p className="break-words font-medium">{spec.parameter}</p><p className="my-2 break-words font-mono">{specificationValue(spec)}</p><p className="subtle">{natureLabels[spec.nature]} · 待专业确认 · {spec.owner_id === principalId ? "我负责" : spec.owner_id ? "有原负责人" : "负责人待定"}</p><p className="mt-2 break-words text-sm">依据：{spec.reason}</p><p className="subtle mt-1 break-words">条件：{spec.test_conditions.join("；") || "尚未明确"}</p><p className="subtle break-words">方法：{spec.method ?? "尚未明确"} · 判据：{spec.acceptance_criterion ?? "尚未明确"}</p></article>)}</section>}
          <details><summary className="cursor-pointer text-sm font-medium"><FileText className="mr-1 inline-block size-4"/>原文依据与版本</summary><ul className="mt-3 space-y-3">{item.sources.map(ref => <li key={referenceKey(ref)} className="min-w-0 border-l-2 border-border pl-3"><p className="subtle">{ref.title} · v{ref.expected_revision} · 第{ref.line}行 · {ref.status === "active" ? "当前来源有效" : "来源待重核"}</p><blockquote className="mt-1 break-words text-sm">{ref.quote}</blockquote></li>)}</ul></details>
          <p className="subtle break-words">本版原因：{item.change_reason}{item.parent_definition_id ? " · 固定前一草稿，历史未覆盖" : " · 首版"}</p>
          {item.differences.length > 0 && <details><summary className="cursor-pointer text-sm font-medium">与固定父版的变化 · {item.differences.length}处</summary><div className="mt-3 space-y-3">{item.differences.map(change => <div key={change.path} className="min-w-0 rounded-lg border border-border p-3"><p className="mb-2 text-sm font-medium">{pathLabels[change.path] ?? `规格 ${change.path.replace("specs/", "")}`}</p><div className="grid gap-3 sm:grid-cols-2"><div><p className="subtle">前版</p><div className="break-words whitespace-pre-wrap text-sm">{changeValue(change.before)}</div></div><div><p className="subtle">此版</p><div className="break-words whitespace-pre-wrap text-sm">{change.after == null ? "从新版本移除，前版保留" : changeValue(change.after)}</div></div></div></div>)}</div></details>}
          {compact ? <details className="border-t border-border pt-3"><summary className="cursor-pointer text-xs font-medium">维护定义与条目</summary><div className="mt-3"><DefinitionDraftActions definition={item} product={product} principalId={principalId} sources={sources} api={api} onSaved={definitionSaved} isLatest={isLatestDefinition(item, items)} onAccessDenied={clearPrivate}/></div></details> : <DefinitionDraftActions definition={item} product={product} principalId={principalId} sources={sources}
            api={api} onSaved={definitionSaved} isLatest={isLatestDefinition(item, items)} onAccessDenied={clearPrivate}/>}
        </ReadingRecord>)}</div>}
        {hasMore && <p className="subtle mt-4">显示最近100个可见版本，历史仍保留。</p>}
      </ReadingPanel>
    </div>
  </section>;
}
