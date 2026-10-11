"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowsClockwise, GitBranch, Plus, Trash } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { plainReference, referenceKey, sourceLines, specificationValue, type DefinitionApi, type DefinitionList, type DefinitionPayload, type DefinitionReadSpec, type DefinitionReference, type DefinitionRevision, type DefinitionSource, type DefinitionSpec } from "@/lib/product-view";
import { changeLabels, fieldLabels, kindLabels, nativeParentBlocker, nativeRebaseBlocker, variantSpec, type DerivePayload, type RebasePayload, type Variant, type VariantCommand, type VariantComparison, type VariantList, type VariantOverrides, type VariantPreview } from "@/lib/variant-view";
import { ReadingPanel, ReadingRecord } from "./reading";

type Props = { product: { id: string; category_id?: string; name: string; purpose: string; revision: number }; principalId: string; sources: DefinitionSource[]; api: DefinitionApi; onSaved: () => void | Promise<void> };
type Editor = { name: string; kind: Variant["kind"]; scope: string; parentId: string; visibility: "private" | "category" | "audience"; fields: Record<string, string>; specs: NonNullable<VariantOverrides["specs"]> | null; references: DefinitionReference[]; reason: string };
type Choice = { selection: "parent" | "child" | ""; reason: string };
type ContentField = "title" | "purpose" | "use_cases" | "requirements" | "constraints" | "unknowns" | "exclusions";
type Preview = VariantPreview & { command: VariantCommand };
type PreparedPreview = { command: VariantCommand; confirmation_token: string; expires_at: string; review: Omit<VariantPreview, "confirmation_token"> };
const blank: Editor = { name: "", kind: "configuration", scope: "", parentId: "", visibility: "private", fields: {}, specs: null, references: [], reason: "" };
const entries = (text: string) => text.split("\n").map(value => value.trim()).filter(Boolean);

function detail(value: unknown): ReactNode {
  if (value == null) return <span className="subtle">未包含</span>;
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return <ul className="space-y-1">{value.map((item, index) => <li key={index}>{detail(item)}</li>)}</ul>;
  if (typeof value === "object" && typeof (value as { parameter?: string }).parameter === "string") {
    const spec = value as DefinitionReadSpec;
    return <div className="space-y-1"><p>{spec.parameter} · {specificationValue(spec)}</p><p className="subtle">条件：{spec.test_conditions?.join("；") || "待确认"}</p><p className="subtle">方法：{spec.method ?? "待确认"} · 判据：{spec.acceptance_criterion ?? "待确认"}</p><p className="subtle">说明：{spec.reason}</p></div>;
  }
  return String(value);
}

function uniqueRefs(refs: DefinitionReference[]) {
  return [...new Map(refs.map(ref => [referenceKey(ref), plainReference(ref)])).values()];
}
function readSet(refs: DefinitionReference[]) {
  return [...new Map(refs.map(ref => [ref.artifact_id, { artifact_id: ref.artifact_id, expected_revision: ref.expected_revision }])).values()];
}

export function ProductVariants(props: Props) {
  return <VariantsPanel key={`${props.principalId}:${props.product.category_id ?? ""}:${props.product.id}`} {...props}/>;
}

function VariantsPanel({ product, principalId, sources, api, onSaved }: Props) {
  const storageKey = `pdos-next:variants:${principalId}:${product.id}`;
  const [definitions, setDefinitions] = useState<DefinitionRevision[]>([]);
  const [variants, setVariants] = useState<Variant[]>([]);
  const [editor, setEditor] = useState<Editor>(blank);
  const [pending, setPending] = useState<VariantCommand | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [comparison, setComparison] = useState<VariantComparison | null>(null);
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [variantId, setVariantId] = useState("");
  const [newParentId, setNewParentId] = useState("");
  const [rebaseReason, setRebaseReason] = useState("");
  const [sourceId, setSourceId] = useState(sources.find(source => source.status === "active")?.id ?? "");
  const [quote, setQuote] = useState("");
  const [line, setLine] = useState(1);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [hidden, setHidden] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const alive = useRef(true);
  const lock = useRef(false);
  const compareEpoch = useRef(0);
  const parent = definitions.find(item => item.id === editor.parentId);
  const source = sources.find(item => item.id === sourceId);
  const editable = !busy && !pending;
  const parentBlocker = nativeParentBlocker(parent, definitions, product);
  const rebaseBlocker = nativeRebaseBlocker(variants.find(item => item.id === variantId), definitions.find(item => item.id === newParentId), definitions, product);

  const refresh = useCallback(async () => {
    const [defined, derived] = await Promise.all([api<DefinitionList>(`v1/products/${product.id}/definitions`), api<VariantList>(`v1/products/${product.id}/variants`)]);
    if (!alive.current) return;
    compareEpoch.current++; setComparison(null);
    setDefinitions(defined.items); setVariants(derived.items); setHidden(derived.unavailable_count);
    setNewParentId(current => defined.items.some(item => item.id === current) ? current : defined.items[0]?.id ?? "");
    setVariantId(current => derived.items.some(item => item.id === current) ? current : derived.items[0]?.id ?? "");
  }, [api, product.id]);
  useEffect(() => {
    alive.current = true;
    void refresh().catch(failure => { if (alive.current) setError(failure.message); });
    void Promise.resolve().then(() => {
      if (!alive.current) return;
      try {
        const local = JSON.parse(localStorage.getItem(storageKey) ?? "null");
        if (local?.editor && typeof local.editor.name === "string" && typeof local.editor.scope === "string" && Array.isArray(local.editor.references) && typeof local.editor.fields === "object") setEditor(local.editor);
        if (local?.pending?.operation?.startsWith("product.variant.") && typeof local.pending.idempotency_key === "string") setPending(local.pending);
      } catch { /* Local draft storage is optional. */ }
      setReady(true);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- This numeric request generation intentionally changes during cleanup; it is not a DOM ref.
    return () => { alive.current = false; compareEpoch.current++; };
  }, [refresh, storageKey]);
  useEffect(() => { if (preview) dialog.current?.showModal(); }, [preview]);
  function remember(next: Editor, waiting: VariantCommand | null) {
    try { localStorage.setItem(storageKey, JSON.stringify({ editor: next, pending: waiting })); } catch { /* Server action remains available. */ }
  }
  function edit(next: Editor) { setEditor(next); remember(next, pending); }
  function closePreview() { dialog.current?.close(); setPreview(null); trigger.current?.focus(); }
  function command(operation: VariantCommand["operation"], payload: DerivePayload | RebasePayload, refs: DefinitionReference[]): VariantCommand {
    return { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation, product_id: product.id, expected_revision: product.revision, source_read_set: readSet(refs), payload };
  }
  async function prepare(request: VariantCommand, element: HTMLElement) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice(""); trigger.current = element;
    try {
      const result = await api<PreparedPreview>("v1/commands/preview", request);
      if (!result.command || result.command.product_id !== product.id || result.command.operation !== request.operation || !result.confirmation_token || !result.review?.after) throw new Error("预览回执不完整，尚未提交；请重新核对范围。");
      if (alive.current) setPreview({ ...result.review, confirmation_token: result.confirmation_token, command: result.command });
    } catch (failure) { if (alive.current) setError((failure as Error).message); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  async function submit(request: VariantCommand) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice(""); setPending(request); remember(editor, request);
    let committed = false;
    try {
      const receipt = await api<{ id: string; subject_type: string; subject_id: string }>("v1/commands", request);
      if (!receipt.id || receipt.subject_type !== "variant_revision" || !receipt.subject_id) throw new Error("派生保存结果尚未确认，请按原请求重试。");
      if (!alive.current) return;
      committed = true; setPending(null); remember(editor, null); closePreview();
      setNotice("派生草稿版本已保存，固定父定义和此次选择；父版与历史保留。");
      await refresh(); await onSaved(); setComparison(null);
    } catch (failure) {
      if (!alive.current) return;
      const failed = failure as Error & { status?: number };
      if (failed.status && failed.status < 500) { setPending(null); remember(editor, null); closePreview(); }
      setError(committed ? `派生版本已保存；最新读取失败，可刷新。${failed.message}` : failed.message);
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function derive(element: HTMLElement) {
    if (!parent || parentBlocker) { setError(parentBlocker ?? "先选择可见的真实父定义版本。"); return; }
    if (editor.name.trim().length < 2 || !entries(editor.scope).length || editor.reason.trim().length < 3) { setError("请填写派生名称、适用范围与至少3字的原因。"); return; }
    const overrides: VariantOverrides = {};
    for (const key of Object.keys(fieldLabels)) {
      if (!Object.hasOwn(editor.fields, key)) continue;
      const value = editor.fields[key];
      if (key === "title" || key === "purpose") overrides[key] = value;
      else (overrides as Record<string, unknown>)[key] = entries(value);
    }
    if (editor.specs !== null) {
      try { overrides.specs = editor.specs.map(spec => ({ ...variantSpec({ ...spec, owner_id: null, state: "needs_confirmation" }), test_conditions: entries(spec.test_conditions.join("\n")) })); }
      catch (failure) { setError((failure as Error).message); return; }
    }
    const refs = uniqueRefs([...parent.sources, ...editor.references, ...(editor.specs ?? []).flatMap(spec => spec.sources)]);
    const body: DerivePayload = { name: editor.name, kind: editor.kind, applicability: entries(editor.scope), parent_definition_id: parent.id, expected_parent_revision: parent.revision, visibility: editor.visibility, overrides, sources: refs, reason: editor.reason };
    void prepare(command("product.variant.derive", body, refs), element);
  }
  async function compare() {
    if (lock.current) return;
    lock.current = true; const epoch = ++compareEpoch.current;
    setComparison(null); setBusy(true); setError("");
    try {
      const result = await api<VariantComparison>(`v1/products/${product.id}/variants/${variantId}/compare?parent_definition_id=${encodeURIComponent(newParentId)}`);
      if (!alive.current || epoch !== compareEpoch.current) return;
      if (result.variant_id !== variantId || result.new_parent_id !== newParentId) throw new Error("比较结果与所选固定版本不一致，请重新读取。");
      setComparison(result); setChoices({}); setRebaseReason("");
    } catch (failure) { if (alive.current && epoch === compareEpoch.current) setError((failure as Error).message); }
    finally { lock.current = false; if (alive.current && epoch === compareEpoch.current) setBusy(false); }
  }
  function rebase(element: HTMLElement) {
    if (!comparison) return;
    if (rebaseBlocker || comparison.variant_id !== variantId || comparison.new_parent_id !== newParentId) { setError(rebaseBlocker ?? "比较选择已变化，请重新读取。"); return; }
    if (rebaseReason.trim().length < 3) { setError("请填写至少3字的重核原因。"); return; }
    const selected = [];
    for (const change of comparison.changes) {
      const choice = choices[change.path];
      if (change.category === "conflict" && (!choice?.selection || choice.reason.trim().length < 3)) { setError("每个冲突须明确选父版或派生，并填写至少3字原因。"); return; }
      if (choice?.selection) {
        if (choice.reason.trim().length < 3) { setError("已作的差异选择须填写至少3字原因。"); return; }
        selected.push({ path: change.path, selection: choice.selection, reason: choice.reason });
      }
    }
    const body: RebasePayload = { variant_id: comparison.variant_id, expected_variant_revision: comparison.variant_revision, parent_definition_id: comparison.new_parent_id, expected_parent_revision: comparison.new_parent_revision, choices: selected, sources: comparison.sources, reason: rebaseReason };
    void prepare(command("product.variant.rebase", body, comparison.sources), element);
  }
  function specChange(index: number, changes: Partial<Omit<DefinitionSpec, "owner_id" | "state">>) {
    edit({ ...editor, specs: editor.specs?.map((spec, position) => index === position ? { ...spec, ...changes } : spec) ?? null });
  }

  return <section className="min-w-0 space-y-5" aria-label="型号派生与父版重核">
    <header className="flex flex-wrap justify-between gap-3"><div><h2 className="text-lg font-semibold"><GitBranch className="mr-2 inline-block text-primary"/>型号派生与父版重核</h2><p className="subtle mt-1">同一型号的客户、地区或配置草稿；固定父定义，明确差异与适用范围。</p></div><Button variant="outline" disabled={busy} onClick={() => { setError(""); void refresh().catch(failure => setError(failure.message)); }}><ArrowsClockwise/>刷新派生与定义</Button></header>
    {error && <p role="alert" className="break-words rounded-lg border border-destructive p-3 text-destructive">{error}</p>}{notice && <p role="status" className="rounded-lg border border-border p-3">{notice}</p>}
    {hidden > 0 && <p className="subtle">{hidden} 个历史派生版本的来源权限待重核，正文已隐藏。</p>}
    {pending && <div className="rounded-lg border border-primary p-4"><p className="mb-3">这次派生保存结果待确认，保留原请求编号与完整内容。</p><Button disabled={busy} onClick={() => void submit(pending)}>按原请求重试派生保存</Button></div>}
    <div className="grid min-w-0 items-start gap-5 xl:grid-cols-2">
      <ReadingPanel title="从定义派生"><fieldset disabled={!editable || !ready} className="min-w-0">
        <label>固定父定义版本<select value={editor.parentId} onChange={event => edit({ ...editor, parentId: event.target.value, fields: {}, specs: null, visibility: "private" })}><option value="">选择已保存定义</option>{definitions.map(item => { const issue = nativeParentBlocker(item, definitions, product); return <option key={item.id} value={item.id} disabled={!!issue}>{item.title} · v{item.revision}{issue ? " · 当前入口不可用" : " · 可派生"}</option>; })}</select></label>
        {parentBlocker && <p className="subtle mb-4">{parentBlocker}</p>}
        {definitions.length === 0 && <p className="subtle mb-4">先保存来源绑定的型号定义草稿。</p>}
        <label>派生名称<input maxLength={160} value={editor.name} onChange={event => edit({ ...editor, name: event.target.value })}/></label>
        <label>派生类别<select value={editor.kind} onChange={event => edit({ ...editor, kind: event.target.value as Variant["kind"] })}>{Object.entries(kindLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label>本派生适用范围（每行一项）<textarea maxLength={6000} value={editor.scope} onChange={event => edit({ ...editor, scope: event.target.value })}/></label>
        {parent && !parentBlocker && <section className="mb-5 space-y-3"><h3 className="font-medium">显式覆盖</h3><p className="subtle">未选择字段继承固定父版；每次保存都保持草稿，专业任命和确认状态不随父版继承。</p>{Object.entries(fieldLabels).map(([key, label]) => <div className="rounded-lg border border-border p-3" key={key}><label className="flex gap-2 items-center !mb-1"><input type="checkbox" className="!w-auto !inline-block !mt-0" checked={Object.hasOwn(editor.fields, key)} onChange={event => { const fields = { ...editor.fields }; if (event.target.checked) { const value = parent[key as ContentField]; fields[key] = Array.isArray(value) ? value.join("\n") : String(value); } else delete fields[key]; edit({ ...editor, fields }); }}/><span>覆盖{label}</span></label>{Object.hasOwn(editor.fields, key) ? <textarea maxLength={12000} aria-label={`派生覆盖${label}`} value={editor.fields[key]} onChange={event => edit({ ...editor, fields: { ...editor.fields, [key]: event.target.value } })}/> : <div className="break-words text-sm subtle">{detail(parent[key as ContentField])}</div>}</div>)}
          <label className="flex items-center gap-2"><input type="checkbox" className="!w-auto !inline-block !mt-0" checked={editor.specs !== null} onChange={event => edit({ ...editor, specs: event.target.checked ? parent.specs.map(variantSpec) : null })}/><span>覆盖可测规格</span></label>
          {editor.specs?.map((spec, index) => <details key={spec.key} className="rounded-lg border border-border p-3" open><summary className="cursor-pointer font-medium">{spec.parameter} · {spec.key}</summary><div className="mt-4"><label>信息状态<select value={spec.availability} onChange={event => specChange(index, { availability: event.target.value as DefinitionSpec["availability"], value: null, lower: null, upper: null, text: null, tolerance: null })}><option value="known">已知</option><option value="unknown">未知 / 待确认</option><option value="conflicted">冲突</option><option value="not_applicable">不适用（有依据）</option></select></label>{spec.availability === "known" && (spec.value_type === "text" ? <label>文字目标<textarea value={spec.text ?? ""} onChange={event => specChange(index, { text: event.target.value || null })}/></label> : <div className="grid gap-3 sm:grid-cols-2">{(spec.value_type === "range" ? ["lower", "upper"] : ["value"]).map(key => <label key={key}>{({ lower: "下限", upper: "上限", value: "目标值" } as Record<string, string>)[key]}<input inputMode="decimal" value={spec[key as "value" | "lower" | "upper"] ?? ""} onChange={event => specChange(index, { [key]: event.target.value || null })}/></label>)}<label>单位<input value={spec.unit ?? ""} maxLength={80} onChange={event => specChange(index, { unit: event.target.value || null })}/></label></div>)}<label>测试条件（每行一项）<textarea value={spec.test_conditions.join("\n")} onChange={event => specChange(index, { test_conditions: event.target.value.split("\n") })}/></label><label>判定方法<textarea value={spec.method ?? ""} onChange={event => specChange(index, { method: event.target.value || null })}/></label><label>验收判据<textarea value={spec.acceptance_criterion ?? ""} onChange={event => specChange(index, { acceptance_criterion: event.target.value || null })}/></label><label>覆盖依据 / 未知说明<textarea value={spec.reason} onChange={event => specChange(index, { reason: event.target.value })}/></label><p className="subtle mb-2">引用：{spec.sources.map(ref => `第${ref.line}行 ${ref.quote}`).join("；")}</p>{editor.references.length > 0 && <Button type="button" size="sm" variant="outline" onClick={() => specChange(index, { sources: uniqueRefs([...spec.sources, ...editor.references]) })}>把新增依据关联此规格</Button>}</div></details>)}
        </section>}
        <details className="mb-4 rounded-lg border border-border p-3"><summary className="cursor-pointer font-medium">新增派生依据 · {editor.references.length} 条</summary><div className="mt-4"><label>当前原始资料<select value={sourceId} onChange={event => { setSourceId(event.target.value); setQuote(""); }}><option value="">选择资料</option>{sources.map(item => <option key={item.id} value={item.id} disabled={item.status !== "active"}>{item.title}</option>)}</select></label>{source && <div className="max-h-48 overflow-auto mb-3">{sourceLines(source.content).map((text, index) => <button key={index} type="button" className="source-line" disabled={!text.trim() || source.status !== "active"} aria-pressed={line === index + 1 && !!quote && text.includes(quote)} onClick={() => { setLine(index + 1); setQuote(text.trim().slice(0, 4000)); }}><span className="subtle w-5 shrink-0">{index + 1}</span><span>{text}</span></button>)}</div>}<label>摘录 · 第{line}行<textarea maxLength={4000} value={quote} onChange={event => setQuote(event.target.value)}/></label><Button type="button" variant="outline" disabled={!source || !quote.trim()} onClick={() => { if (source) edit({ ...editor, references: uniqueRefs([...editor.references, { artifact_id: source.id, expected_revision: source.revision, line, quote: quote.trim() }]), visibility: source.visibility !== "category" ? "private" : editor.visibility }); }}><Plus/>加入派生依据</Button><ul className="mt-3 space-y-2">{editor.references.map(ref => <li className="break-words text-sm" key={referenceKey(ref)}>第{ref.line}行 · {ref.quote}<Button type="button" variant="ghost" size="sm" onClick={() => edit({ ...editor, references: editor.references.filter(item => referenceKey(item) !== referenceKey(ref)) })}><Trash/>移除</Button></li>)}</ul></div></details>
        <label>派生受众<select value={editor.visibility} onChange={event => edit({ ...editor, visibility: event.target.value as Editor["visibility"] })}><option value="private">仅我可见</option><option value="category" disabled={parent?.visibility !== "category" || editor.references.some(ref => sources.find(item => item.id === ref.artifact_id)?.visibility !== "category")}>品类授权成员</option></select></label>
        <label>派生原因<textarea maxLength={2000} value={editor.reason} onChange={event => edit({ ...editor, reason: event.target.value })}/></label><p className="subtle mb-3">先查看实际固定版本、差异、依据和影响，再一次确认保存。</p><Button disabled={!editable || !!parentBlocker} onClick={event => derive(event.currentTarget)}>查看派生保存范围…</Button>
      </fieldset></ReadingPanel>
      <div className="min-w-0 space-y-5"><ReadingPanel title="已保存派生" count={variants.length}>{variants.length === 0 && <p className="subtle">尚无可见派生草稿。</p>}<div className="space-y-4">{variants.map(item => <ReadingRecord key={item.id} id={`variant-${item.id}`} title={item.name} meta={`${kindLabels[item.kind]} · ${item.visibility === "private" ? "仅本人" : item.visibility === "audience" ? "指定评审人" : "品类授权成员"} · ${item.revisions.length}个草稿版本`}><div className="space-y-4">{item.revisions.map(revision => <article key={revision.id} className="min-w-0 space-y-3 border-t border-border pt-3"><p className="font-medium">派生 v{revision.revision} · 固定定义 v{revision.parent_revision}</p><p className="subtle">{revision.source_status === "current" ? "来源当前有效" : "来源待重核"} · {new Date(revision.created_at).toLocaleString()}</p><p className="break-words">适用：{revision.applicability.join("；")}</p><p className="break-words">{revision.effective_definition.title} · {revision.effective_definition.purpose}</p>{revision.effective_definition.specs.map(spec => <p className="break-words text-sm" key={spec.key}>{spec.parameter}：{specificationValue(spec)} · 待专业确认</p>)}<details><summary className="cursor-pointer text-sm">显式覆盖与原文依据</summary><div className="mt-3 space-y-3">{Object.entries(revision.overrides).map(([key, value]) => <section key={key}><h4 className="subtle">{fieldLabels[key] ?? "规格"}</h4><div className="break-words text-sm">{detail(value)}</div></section>)}{revision.effective_definition.sources.map(ref => <blockquote key={referenceKey(ref)} className="break-words border-l-2 border-border pl-3 text-sm">原文 v{ref.expected_revision} · 第{ref.line}行：{ref.quote}</blockquote>)}</div></details><p className="subtle break-words">原因：{revision.reason}</p>{revision.choices.length > 0 && <ul className="subtle">{revision.choices.map(choice => <li key={choice.path}>{fieldLabels[choice.path] ?? choice.path.replace("specs/", "规格 ")}：{choice.selection === "parent" ? "采用父版" : "保留派生"} · {choice.reason}</li>)}</ul>}</article>)}</div></ReadingRecord>)}</div></ReadingPanel>
        <ReadingPanel title="比较并重核父版"><fieldset disabled={!editable} className="min-w-0"><label>派生对象<select value={variantId} onChange={event => { setVariantId(event.target.value); setComparison(null); }}><option value="">选择真实派生</option>{variants.map(item => <option key={item.id} value={item.id}>{item.name} · v{item.revisions[0]?.revision}</option>)}</select></label><label>新的父定义版本<select value={newParentId} onChange={event => { setNewParentId(event.target.value); setComparison(null); }}><option value="">选择真实定义</option>{definitions.map(item => <option key={item.id} value={item.id} disabled={item.source_status !== "current"}>{item.title} · v{item.revision}</option>)}</select></label><Button variant="outline" disabled={!editable || !variantId || !newParentId} onClick={() => void compare()}>读取旧父 / 新父 / 当前派生差异</Button>
          {comparison && <div className="mt-4 space-y-4"><p className="text-sm">固定父 v{comparison.old_parent_revision} → 新父 v{comparison.new_parent_revision}；当前派生 v{comparison.variant_revision}；{comparison.conflict_count}处冲突。</p><p className="subtle">{rebaseBlocker ? "三方差异仅供核对，不会自动改变父版或派生。" : "只父版变化默认采用新父，只派生覆盖默认保留派生。冲突须逐项选择；读比较不改业务记录。"}</p>{comparison.changes.map(change => <section key={change.path} className="rounded-lg border border-border p-3"><h4 className="font-medium">{fieldLabels[change.path] ?? change.path.replace("specs/", "规格 ")}</h4><p className="subtle mt-1">{changeLabels[change.category]}</p><div className="mt-3 grid gap-3 sm:grid-cols-3">{([ ["旧父", change.old_parent], ["新父", change.new_parent], ["当前派生", change.current_child] ] as const).map(([label, value]) => <div key={label} className="min-w-0"><p className="subtle mb-1">{label}</p><div className="break-words whitespace-pre-wrap text-sm">{detail(value)}</div></div>)}</div><label className="mt-3">{change.category === "conflict" ? "必须明确选择" : "可明确覆盖默认处理"}<select disabled={!!rebaseBlocker} value={choices[change.path]?.selection ?? ""} onChange={event => setChoices({ ...choices, [change.path]: { selection: event.target.value as Choice["selection"], reason: choices[change.path]?.reason ?? "" } })}><option value="">{change.category === "conflict" ? "选择本处处理" : "沿默认处理"}</option><option value="parent">采用新父版</option><option value="child">保留当前派生</option></select></label>{choices[change.path]?.selection && <label>本处选择原因<textarea maxLength={2000} value={choices[change.path]?.reason ?? ""} onChange={event => setChoices({ ...choices, [change.path]: { selection: choices[change.path]?.selection ?? "", reason: event.target.value } })}/></label>}</section>)}{rebaseBlocker && <p className="subtle">{rebaseBlocker}</p>}<label>此次重核原因<textarea disabled={!!rebaseBlocker} maxLength={2000} value={rebaseReason} onChange={event => setRebaseReason(event.target.value)}/></label><Button disabled={!editable || !!rebaseBlocker} onClick={event => rebase(event.currentTarget)}>查看重核保存范围…</Button></div>}
        </fieldset></ReadingPanel>
      </div>
    </div>
    <dialog ref={dialog} className="!w-[min(760px,calc(100vw-32px))] max-h-[90vh] overflow-auto" onCancel={event => { event.preventDefault(); if (!busy) closePreview(); }}>
      {preview && <div className="space-y-4"><h2 className="text-lg font-semibold">确认本次派生草稿范围</h2><p>{preview.effect}</p><p className="text-sm">固定定义 v{preview.parent_revision} · {preview.variant_revision ? `当前派生 v${preview.variant_revision} → 新版本` : "创建首版派生"} · {preview.visibility === "private" ? "仅本人" : preview.visibility === "audience" ? "指定评审人" : "品类授权成员"}</p><p className="break-words text-sm">适用范围：{preview.applicability.join("；")}</p><div className="grid min-w-0 gap-4 sm:grid-cols-2"><section className="min-w-0"><h3 className="subtle mb-2">当前派生</h3>{preview.before ? <><p>{preview.before.title}</p><p className="break-words text-sm">{preview.before.purpose}</p>{preview.before.specs.map(spec => <p className="break-words text-sm" key={spec.key}>{spec.parameter}：{specificationValue(spec)}</p>)}</> : <p className="text-sm">尚未建立</p>}</section><section className="min-w-0"><h3 className="subtle mb-2">确认后保存</h3><p>{preview.after.title}</p><p className="break-words text-sm">{preview.after.purpose}</p>{preview.after.specs.map(spec => <p className="break-words text-sm" key={spec.key}>{spec.parameter}：{specificationValue(spec)}</p>)}{Object.entries(fieldLabels).filter(([key]) => !["title", "purpose"].includes(key)).map(([key, label]) => <div className="mt-2 text-sm" key={key}><p className="subtle">{label}</p><div className="break-words">{detail(preview.after[key as keyof DefinitionPayload])}</div></div>)}</section></div><details><summary className="cursor-pointer text-sm font-medium">核对最终原文依据</summary><ul className="mt-3 space-y-2">{preview.after.sources.map(ref => <li className="break-words text-sm" key={referenceKey(ref)}>原文 v{ref.expected_revision} · 第{ref.line}行：{ref.quote}</li>)}</ul></details><p className="break-words text-sm">原因：{preview.reason}</p><div className="flex flex-wrap justify-end gap-2"><Button variant="outline" disabled={busy} onClick={closePreview}>返回编辑</Button><Button disabled={busy || !!pending} onClick={() => void submit(preview.command)}>确认保存此派生草稿</Button></div></div>}
    </dialog>
  </section>;
}
