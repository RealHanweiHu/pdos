"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { sourceLines, type DefinitionApi, type DefinitionRevision, type DefinitionSource } from "@/lib/product-view";
import { emptyItem, itemProblem, itemReferences, itemSummary, projectItem, projectReference, type ItemContent, type ItemReference, type ItemWatermark, type StoredItem } from "@/lib/definition-item-editor";
import { ReadingPanel } from "./reading";

export type EditableDefinition = Omit<DefinitionRevision, "specs" | "status"> & {
  category_id: string; variant_id: string | null; sealed: boolean; status: string;
  specs: StoredItem[]; item_versions: ItemWatermark[];
};
type Props = { definition: EditableDefinition; product: { id: string; revision: number }; principalId: string; sources: DefinitionSource[];
  api: DefinitionApi; onSaved: () => void | Promise<void>; isLatest?: boolean; onAccessDenied?: () => void };
type Operation = { op: "upsert"; item_id?: string; base_version?: number; content: ItemContent; source_refs: ItemReference[] }
  | { op: "remove"; item_id: string; base_version: number };
type Command = { command_id: string; idempotency_key: string; category_id: string; product_id: string; expected_revision: number;
  source_read_set: { artifact_id: string; expected_revision: number }[];
  operation: "product.definition.draft" | "product.definition.item.patch";
  payload: { mode: "inherit_parent"; parent_definition_id: string; expected_parent_revision: number; change_reason: string }
    | { definition_id: string; ops: Operation[]; confirmation_token?: string } };
type Receipt = { id: string; category_id: string; product_id: string; operation: string; subject_type: string;
  subject_id: string; subject_revision: number; writer_id: string; requester_id: string; agent_run_id?: string | null;
  result: { inherited_from?: string; definition_id?: string; changes?: { item_id: string; item_version: number; key: string; removed: boolean }[] } };
type Journal = { state: "unknown" | "rejected" | "complete"; command: Command; receipt?: Receipt; reason?: string; hidden?: boolean };
type Editor = { content: ItemContent; refs: ItemReference[]; watermark: ItemWatermark | null };
type Removal = { command: Command; name: string; value: string; version: number; effect: string };
type Failure = Error & { status?: number; code?: string; detail?: { reason?: string } };
const nullable = (value: string) => value.trim() || null;
const uuid = /^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/i;
const refsLabel: Record<ItemReference["type"], string> = { human: "具名陈述", artifact: "原文资料", original: "原始文件", snapshot: "网页快照", knowledge: "品类知识", parameter: "规格字典", definition: "固定定义", claim: "事实" };
const staleReasons = new Set(["definition_item_moved", "definition_item_removed", "definition_not_current", "parent_version_moved", "product_version_moved", "definition_consumed"]);
// These responses precede effects; execute checks both saved-receipt paths before owner validation.
const editRejections = new Set(["definition_locked", "definition_item_key_immutable", "definition_item_key_taken",
  "parameter_key_mismatch", "parameter_unit_mismatch", "parameter_type_mismatch", "assignee_not_member", "quote_not_in_source", "human_source_invalid"]);
function rejected(failure: Failure) {
  if (failure.status === 422 && failure.code === "VALIDATION_FAILED" && failure.detail?.reason === "INVALID_PAYLOAD") return true;
  return failure.status === 409 && ((failure.code === "VERSION_CONFLICT" && staleReasons.has(failure.detail?.reason ?? ""))
    || (failure.code === "VALIDATION_FAILED" && editRejections.has(failure.detail?.reason ?? "")));
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, child]) => `${JSON.stringify(key)}:${canonical(child)}`).join(",")}}`;
  return JSON.stringify(value);
}
function matchesReceipt(receipt: Receipt, command: Command, principalId: string): boolean {
  if (!receipt || !uuid.test(receipt.id) || receipt.category_id !== command.category_id || receipt.product_id !== command.product_id
    || receipt.operation !== command.operation || receipt.subject_type !== "definition_revision" || !uuid.test(receipt.subject_id)
    || receipt.writer_id !== principalId || receipt.requester_id !== principalId || receipt.agent_run_id) return false;
  if ("parent_definition_id" in command.payload) return receipt.subject_id !== command.payload.parent_definition_id
    && receipt.subject_revision === command.payload.expected_parent_revision + 1 && receipt.result?.inherited_from === command.payload.parent_definition_id;
  return receipt.subject_id === command.payload.definition_id && receipt.result?.definition_id === command.payload.definition_id
    && command.payload.ops.every(op => receipt.result.changes?.some(change => op.op === "remove"
      ? change.item_id === op.item_id && change.item_version === op.base_version + 1 && change.removed
      : !change.removed && change.key === op.content.key && (op.item_id ? change.item_id === op.item_id && change.item_version === op.base_version! + 1 : change.item_version === 1)));
}
function recovered(value: unknown, props: Props): Journal | null {
  if (!value || typeof value !== "object") return null;
  const entry = value as Journal, command = entry.command;
  if (!command || !["unknown", "rejected", "complete"].includes(entry.state) || !uuid.test(command.command_id) || !uuid.test(command.idempotency_key)
    || command.category_id !== props.definition.category_id || command.product_id !== props.product.id || !command.payload) return null;
  const valid = command.operation === "product.definition.draft" && "parent_definition_id" in command.payload && command.payload.mode === "inherit_parent" && command.payload.parent_definition_id === props.definition.id
    || command.operation === "product.definition.item.patch" && "definition_id" in command.payload && command.payload.definition_id === props.definition.id && Array.isArray(command.payload.ops);
  if (!valid || entry.state === "complete" && (!entry.receipt || !matchesReceipt(entry.receipt, command, props.principalId))) return null;
  return entry;
}

export function DefinitionDraftActions(props: Props) {
  return <DraftActions key={`${props.principalId}:${props.definition.category_id}:${props.product.id}:${props.definition.id}`} {...props}/>;
}
function DraftActions(props: Props) {
  const { product, principalId, api, onSaved, onAccessDenied } = props;
  const storageKey = `pdos-next:definition-actions:${principalId}:${props.definition.category_id}:${product.id}:${props.definition.id}`;
  const [definition, setDefinition] = useState<EditableDefinition | null>(props.definition);
  const [latest, setLatest] = useState(props.isLatest ?? false);
  const [productRevision, setProductRevision] = useState(product.revision);
  const [journal, setJournal] = useState<Journal | null>(null);
  const [ready, setReady] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [reason, setReason] = useState("");
  const [editor, setEditor] = useState<Editor | null>(null), [removal, setRemoval] = useState<Removal | null>(null);
  const [sourceId, setSourceId] = useState(""), [line, setLine] = useState("1"), [quote, setQuote] = useState(""), [statement, setStatement] = useState("");
  const alive = useRef(false), lock = useRef(false), denied = useRef(false), generation = useRef(0);
  useEffect(() => {
    alive.current = true;
    const epoch = generation.current;
    void Promise.resolve().then(() => {
      if (!alive.current || epoch !== generation.current) return;
      try {
        const raw = window.sessionStorage.getItem(storageKey);
        if (raw) {
          const entry = recovered(JSON.parse(raw), props);
          if (!entry) throw new Error("原操作恢复记录不完整，请核对原回执后再办理。");
          setJournal(entry);
          if (entry.hidden) { denied.current = true; setDefinition(null); }
        }
        setReady(true);
      } catch (failure) { setError((failure as Error).message); }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- generation invalidates this scope's pending callbacks.
    return () => { alive.current = false; generation.current++; };
    // The keyed wrapper fixes this scope; a parent refresh never replaces a pending command.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);
  useEffect(() => {
    if (!denied.current) { setDefinition(props.definition); setLatest(props.isLatest ?? false); }
  }, [props.definition, props.isLatest]);
  const pending = !!journal && journal.state !== "complete";
  const disabled = !ready || busy || pending || !definition;
  const patchable = !!definition && latest && definition.status === "draft" && !definition.sealed;
  function clearPrivate() {
    denied.current = true; setDefinition(null); setEditor(null); setRemoval(null); setReason("");
    setSourceId(""); setLine("1"); setQuote(""); setStatement(""); onAccessDenied?.();
  }
  function fail(failure: unknown) {
    const value = failure as Failure;
    if (value.status === 401 || value.status === 403) clearPrivate();
    setError(value.message || "当前结果不可用，请保留原请求核对。");
  }
  function remember(entry: Journal) {
    window.sessionStorage.setItem(storageKey, JSON.stringify(entry)); setJournal(entry);
  }
  function command(payload: Command["payload"], operation: Command["operation"]): Command {
    return { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), category_id: props.definition.category_id,
      product_id: product.id, expected_revision: Math.max(productRevision, product.revision), source_read_set: [], operation, payload };
  }
  async function reload(release = false) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); const epoch = ++generation.current;
    try {
      const [result, workspace] = await Promise.all([
        api<{ items: EditableDefinition[] }>(`v1/products/${product.id}/definitions`),
        api<{ product: { id: string; category_id: string; revision: number } }>(`v1/products/${product.id}/workspace`),
      ]);
      if (!alive.current || epoch !== generation.current) return;
      if (workspace.product?.id !== product.id || workspace.product.category_id !== props.definition.category_id || !Number.isSafeInteger(workspace.product.revision) || workspace.product.revision < 1) throw new Error("重新读取的型号范围不匹配，请保留原操作核对。");
      const current = result.items.find(item => item.id === props.definition.id && item.category_id === props.definition.category_id && item.product_id === product.id);
      if (!current) { clearPrivate(); throw new Error("当前固定定义不可读取，请返回定义列表核对。"); }
      const isLatest = !result.items.some(item => item.variant_id === current.variant_id && item.revision > current.revision);
      if (release) { window.sessionStorage.removeItem(storageKey); setJournal(null); setEditor(null); setRemoval(null); setReason(""); }
      denied.current = false; setDefinition(current); setLatest(isLatest); setProductRevision(workspace.product.revision);
      setNotice(release ? "已重新读取。请重新选择条目或续版并确认，旧请求不会重发。" : "已按当前权限读取固定定义。");
    } catch (failure) { if (alive.current && epoch === generation.current) fail(failure); }
    finally { lock.current = false; if (alive.current && epoch === generation.current) setBusy(false); }
  }
  async function submit(request: Command) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice(""); const epoch = ++generation.current;
    let committed = false;
    try {
      // Failed write-ahead storage stops sending. Leaving never cancels an in-flight command.
      remember({ state: "unknown", command: request });
      const receipt = await api<Receipt>("v1/commands", request);
      if (!matchesReceipt(receipt, request, principalId)) throw new Error("回执与原操作尚未匹配，请按原请求核对。");
      committed = true;
      const complete: Journal = { state: "complete", command: request, receipt };
      // Preserve success for remount even when this scope was left while awaiting the receipt.
      try { window.sessionStorage.setItem(storageKey, JSON.stringify(complete)); } catch { /* Exact original request remains safe to replay. */ }
      if (!alive.current || epoch !== generation.current) return;
      setJournal(complete); setEditor(null); setRemoval(null); setReason(""); setNotice("保存已成功，原版本与来源保留。");
      await onSaved();
    } catch (failure) {
      const value = failure as Failure;
      if (!committed && (rejected(value) || value.status === 401 || value.status === 403)) {
        const entry: Journal = { state: rejected(value) ? "rejected" : "unknown", command: request,
          reason: value.detail?.reason, hidden: value.status === 401 || value.status === 403 };
        try { window.sessionStorage.setItem(storageKey, JSON.stringify(entry)); } catch { /* Preserve the original request. */ }
        if (alive.current && epoch === generation.current) setJournal(entry);
      }
      if (!alive.current || epoch !== generation.current) return;
      if (committed) { if (value.status === 401 || value.status === 403) clearPrivate(); setError(`保存已成功；最新内容读取失败，可重新读取。${value.message}`); }
      else fail(failure);
    } finally { lock.current = false; if (alive.current && epoch === generation.current) setBusy(false); }
  }
  function continueDraft() {
    if (disabled || !definition || !latest) return;
    if (reason.trim().length < 3) { setError("请填写至少三个字的续版原因。"); return; }
    void submit(command({ mode: "inherit_parent", parent_definition_id: definition.id, expected_parent_revision: definition.revision, change_reason: reason.trim() }, "product.definition.draft"));
  }
  function editItem(row?: StoredItem) {
    if (disabled || !patchable) return;
    const watermark = row ? definition?.item_versions.find(item => item.key === row.key) : null;
    if (row && !watermark) { setError("条目版本信息缺失，请重新读取后再编辑。"); return; }
    setEditor({ content: row ? projectItem(row) : emptyItem(), refs: row ? itemReferences(row) : [], watermark: watermark ?? null });
    setStatement(""); setQuote(""); setError("");
  }
  function editContent(change: Partial<ItemContent>) { if (editor) setEditor({ ...editor, content: { ...editor.content, ...change } }); }
  function saveItem() {
    if (disabled || !patchable || !definition || !editor) return;
    const content = projectItem(editor.content);
    for (const name of Object.keys(content) as (keyof ItemContent)[]) if (typeof content[name] === "string") Object.assign(content, { [name]: (content[name] as string).trim() });
    content.test_conditions = content.test_conditions.map(item => item.trim()).filter(Boolean);
    const problem = itemProblem(content, editor.refs);
    if (problem) { setError(problem); return; }
    const op: Operation = { op: "upsert", content, source_refs: editor.refs.map(projectReference), ...(editor.watermark ? { item_id: editor.watermark.item_id, base_version: editor.watermark.item_version } : {}) };
    void submit(command({ definition_id: definition.id, ops: [op] }, "product.definition.item.patch"));
  }
  async function prepareRemoval(row: StoredItem) {
    if (disabled || !patchable || !definition || lock.current) return;
    const watermark = definition.item_versions.find(item => item.key === row.key);
    if (!watermark) { setError("条目版本信息缺失，请重新读取。"); return; }
    const original = command({ definition_id: definition.id, ops: [{ op: "remove", item_id: watermark.item_id, base_version: watermark.item_version }] }, "product.definition.item.patch");
    lock.current = true; setBusy(true); setError(""); const epoch = ++generation.current;
    try {
      const result = await api<{ command: Command; review: { definition_id: string; effect: string } }>("v1/commands/preview", original);
      if (!alive.current || epoch !== generation.current) return;
      const prepared = result.command;
      if (!prepared || prepared.command_id !== original.command_id || prepared.idempotency_key !== original.idempotency_key || prepared.category_id !== original.category_id
        || prepared.product_id !== original.product_id || prepared.operation !== original.operation || prepared.expected_revision !== original.expected_revision
        || canonical(prepared.source_read_set) !== canonical(original.source_read_set) || !("definition_id" in prepared.payload) || !("definition_id" in original.payload)
        || prepared.payload.definition_id !== definition.id || canonical(prepared.payload.ops) !== canonical(original.payload.ops) || result.review?.definition_id !== definition.id) throw new Error("移除预览与所选条目不一致，请重新读取。");
      setRemoval({ command: prepared, name: row.parameter, value: itemSummary(projectItem(row)), version: watermark.item_version, effect: result.review.effect });
    } catch (failure) { if (alive.current && epoch === generation.current) fail(failure); }
    finally { lock.current = false; if (alive.current && epoch === generation.current) setBusy(false); }
  }
  function addSource() {
    if (!editor) return;
    const source = props.sources.find(item => item.id === sourceId), number = Number(line), text = quote.trim();
    if (!source || source.status !== "active" || !Number.isSafeInteger(number) || number < 1 || !text || !sourceLines(source.content)[number - 1]?.includes(text)) { setError("请选择有效资料，并核对摘录位于所填原文行。"); return; }
    const ref = projectReference({ type: "artifact", id: source.id, version: source.revision, line: number, quote: text });
    setEditor({ ...editor, refs: [...editor.refs.filter(item => canonical(item) !== canonical(ref)), ref] }); setQuote("");
  }
  function structuredEntries(field: "exceptions" | "applicable_variants", label: string) {
    if (!editor) return null;
    return <details className="rounded-lg border border-border p-3"><summary>{label} · {editor.content[field].length}</summary><div className="mt-3 space-y-3">
      {editor.content[field].map((entry, index) => <div key={index} className="rounded-lg border border-border p-3">{Object.entries(entry).map(([key, value]) => <label key={key}>{({ text: "说明", key: "变体标识", applies_to: "适用范围", condition: "适用条件" } as Record<string, string>)[key] ?? key}
        {typeof value === "string" ? <input value={value} onChange={event => editContent({ [field]: editor.content[field].map((old, position) => position === index ? { ...old, [key]: event.target.value } : old) })}/> : <span className="block text-sm text-muted-foreground">保留原结构化记录</span>}</label>)}
        <Button type="button" variant="ghost" onClick={() => editContent({ [field]: editor.content[field].filter((_, position) => position !== index) })}>移除此{label}</Button></div>)}
      <Button type="button" variant="outline" onClick={() => editContent({ [field]: [...editor.content[field], field === "exceptions" ? { text: "" } : { key: "" }] })}>添加{label}</Button>
    </div></details>;
  }
  return <ReadingPanel title="定义续版与条目修订"><div className="min-w-0 space-y-4">
    {error && <p role="alert" className="break-words text-destructive">{error}</p>}{notice && <p role="status" className="break-words">{notice}</p>}
    {journal?.state === "complete" && <p role="status" className="break-all text-sm">已取得保存回执：{journal.receipt?.id}</p>}
    {pending && <section className="rounded-lg border border-primary p-3 space-y-3"><p>{journal?.state === "rejected" ? "原操作已明确拒绝，未新增修改。请重新读取，再准备新操作。" : "原操作结果仍待核对。离开页面不会撤销已发送请求。"}</p>
      {journal?.reason === "definition_consumed" && <p>此版本已被固定引用，请保留原版并从最新固定版本续版。</p>}
      {journal?.state === "unknown" ? <Button disabled={busy || !ready} onClick={() => void submit(journal.command)}>按原请求核对结果</Button> : <Button disabled={busy || !ready} onClick={() => void reload(true)}>重新读取后准备新操作</Button>}
    </section>}
    {!definition ? <p className="text-sm text-muted-foreground">当前定义内容已隐藏。恢复权限后可明确重新读取；待核对原请求保留。</p> : <>
      <p className="text-sm">固定定义 v{definition.revision} · {definition.status === "published" ? "已发布" : definition.sealed ? "已封存" : "草稿"}。续版保留完整内容与原来源，新版为独立草稿。</p>
      {!latest && <p className="text-sm text-muted-foreground">请在当前最新的同类定义版本办理续版或条目修订。</p>}
      <fieldset disabled={disabled || !latest} className="min-w-0 space-y-3"><label>续版原因<textarea aria-label="续版原因" value={reason} maxLength={2000} onChange={event => setReason(event.target.value)}/></label><Button type="button" disabled={disabled || !latest} onClick={continueDraft}>保留完整内容，创建新草稿</Button></fieldset>
      {patchable && <section className="space-y-3"><div className="flex flex-wrap items-center justify-between gap-3"><h4 className="font-medium">当前条目</h4><Button disabled={disabled} variant="outline" onClick={() => editItem()}>新增规格条目</Button></div>
        {definition.specs.map(row => <div key={row.key} className="rounded-lg border border-border p-3"><p className="break-words">{row.parameter} · {itemSummary(projectItem(row))}</p><div className="mt-2 flex flex-wrap gap-2"><Button disabled={disabled} size="sm" variant="outline" onClick={() => editItem(row)}>修订{row.parameter}</Button><Button disabled={disabled} size="sm" variant="ghost" onClick={() => void prepareRemoval(row)}>移除{row.parameter}</Button></div></div>)}
      </section>}
      {editor && <form className="space-y-4 rounded-lg border border-border p-4" onSubmit={event => { event.preventDefault(); saveItem(); }}><fieldset disabled={disabled || !patchable} className="min-w-0 space-y-3">
        <h4 className="font-medium">{editor.watermark ? `修订条目 · v${editor.watermark.item_version}` : "新增规格条目"}</h4>
        <div className="grid gap-3 sm:grid-cols-2"><label>条目标识<input aria-label="条目标识" value={editor.content.key} readOnly={!!editor.watermark} onChange={event => editContent({ key: event.target.value })}/></label><label>参数名称<input aria-label="参数名称" value={editor.content.parameter} onChange={event => editContent({ parameter: event.target.value })}/></label></div>
        {editor.content.parameter_id && <p className="break-all text-sm text-muted-foreground">保留规格字典绑定 · 版本 {editor.content.parameter_version} · {editor.content.parameter_id}</p>}
        <div className="grid gap-3 sm:grid-cols-2"><label>值类型<select aria-label="值类型" value={editor.content.value_type} onChange={event => editContent({ value_type: event.target.value as ItemContent["value_type"], value: null, lower: null, upper: null, text_value: null, tolerance: null })}>{Object.entries({ number: "数值", range: "范围", text: "文字", boolean: "是 / 否", enum: "枚举选项" }).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label>信息状态<select aria-label="信息状态" value={editor.content.availability} onChange={event => editContent({ availability: event.target.value as ItemContent["availability"], value: null, lower: null, upper: null, text_value: null, tolerance: null, item_status: "unknown" })}>{Object.entries({ known: "已知", unknown: "未知", conflicted: "存在冲突", not_applicable: "不适用" }).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
        {editor.content.availability === "known" && (editor.content.value_type === "boolean" ? <label>实际值<select aria-label="实际值" value={editor.content.text_value ?? ""} onChange={event => editContent({ text_value: nullable(event.target.value) })}><option value="">请选择</option><option value="true">是</option><option value="false">否</option></select></label> : ["text", "enum"].includes(editor.content.value_type) ? <label>实际值<input aria-label="实际值" value={editor.content.text_value ?? ""} onChange={event => editContent({ text_value: nullable(event.target.value) })}/></label> : <div className="grid gap-3 sm:grid-cols-2">{(editor.content.value_type === "range" ? ["lower", "upper"] as const : ["value", "lower", "upper"] as const).map(name => <label key={name}>{name === "lower" ? "下限" : name === "upper" ? "上限" : "目标值"}<input aria-label={name} inputMode="decimal" value={editor.content[name] ?? ""} onChange={event => editContent({ [name]: nullable(event.target.value) })}/></label>)}<label>允差<input inputMode="decimal" value={editor.content.tolerance ?? ""} onChange={event => editContent({ tolerance: nullable(event.target.value) })}/></label></div>)}
        {editor.content.availability === "known" && ["number", "range"].includes(editor.content.value_type) && <p className="text-sm text-muted-foreground">填写目标值，或填写上下限；原文未给的端点留空。</p>}
        {([ ["unit", "单位"], ["condition_note", "工况说明"], ["verification_method", "核对方法"], ["acceptance_criterion", "验收判据"], ["reason", "依据或未知说明"] ] as const).map(([name, label]) => <label key={name}>{label}<textarea aria-label={label} value={editor.content[name] ?? ""} onChange={event => editContent({ [name]: nullable(event.target.value) })}/></label>)}
        <label>测试条件（每行一项）<textarea value={editor.content.test_conditions.join("\n")} onChange={event => editContent({ test_conditions: event.target.value.split("\n") })}/></label>
        <div className="grid gap-3 sm:grid-cols-2"><label>要求程度<select value={editor.content.modality ?? ""} onChange={event => editContent({ modality: (event.target.value || null) as ItemContent["modality"] })}>{Object.entries({ "": "未记录", must: "必须", should: "应当", may: "可以", prohibited: "禁止", unstated: "未说明" }).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label>事实性质<select value={editor.content.nature} onChange={event => editContent({ nature: event.target.value as ItemContent["nature"] })}>{Object.entries({ observed: "亲历观察", extracted: "原文抽取", computed: "确定性计算", inferred: "推断", decided: "人的取舍" }).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label>确认状态<select aria-label="确认状态" value={editor.content.item_status} onChange={event => editContent({ item_status: event.target.value as ItemContent["item_status"] })}>{Object.entries({ unknown: "未知 / 未确认", expert_pending: "待专业核对", confirmed: "本人确认", ai_draft: "保留候选状态" }).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label>负责人<select value={editor.content.owner_id ?? ""} onChange={event => editContent({ owner_id: event.target.value || null })}><option value="">未指定</option><option value={principalId}>我负责</option>{editor.content.owner_id && editor.content.owner_id !== principalId && <option value={editor.content.owner_id}>保留原负责人</option>}</select></label></div>
        {structuredEntries("exceptions", "例外")}{structuredEntries("applicable_variants", "适用变体")}
        <section className="space-y-3"><h4 className="font-medium">固定来源</h4>{editor.refs.map((ref, index) => <div key={index} className="rounded-lg border border-border p-3 text-sm"><p className="break-words">{ref.type === "human" && ref.id === principalId ? "本人的具名陈述" : props.sources.find(source => source.id === ref.id)?.title ?? refsLabel[ref.type]} · v{ref.version}{ref.line ? ` · 原文第${ref.line}行` : ""}</p>{(ref.quote || ref.statement) && <p className="break-words">{ref.quote ?? ref.statement}</p>}<details className="mt-2"><summary className="cursor-pointer text-muted-foreground">核对固定来源编号</summary><p className="break-all mt-1">{ref.id}</p></details><Button type="button" variant="ghost" size="sm" onClick={() => setEditor({ ...editor, refs: editor.refs.filter((_, position) => position !== index) })}>移除此来源</Button></div>)}
          <label>原文资料<select aria-label="原文资料" value={sourceId} onChange={event => { setSourceId(event.target.value); setQuote(""); }}><option value="">选择实际资料</option>{props.sources.filter(item => item.status === "active").map(item => <option key={item.id} value={item.id}>{item.title} · v{item.revision}</option>)}</select></label>
          <label>原文行号<input aria-label="原文行号" inputMode="numeric" value={line} onChange={event => setLine(event.target.value)}/></label><label>精确摘录<textarea aria-label="精确摘录" value={quote} onChange={event => setQuote(event.target.value)}/></label><Button type="button" variant="outline" onClick={addSource}>加入原文来源</Button>
          <label>本人具名陈述<textarea aria-label="本人具名陈述" value={statement} onChange={event => setStatement(event.target.value)} placeholder="仅填写你本人实际作出的陈述"/></label><Button type="button" variant="outline" disabled={!statement.trim()} onClick={() => { if (statement.trim()) { setEditor({ ...editor, refs: [...editor.refs, projectReference({ type: "human", id: principalId, version: 1, statement: statement.trim() })] }); setStatement(""); } }}>加入本人陈述</Button>
        </section><div className="flex flex-wrap gap-2"><Button type="submit" disabled={disabled || !patchable}>保存此条修订</Button><Button type="button" variant="outline" onClick={() => setEditor(null)}>取消本次编辑</Button></div>
      </fieldset></form>}
      {removal && <section role="group" aria-label="确认移除条目" className="space-y-3 rounded-lg border border-primary p-4"><h4 className="font-medium">确认从当前草稿移除</h4><p>{removal.name} · {removal.value} · 条目 v{removal.version}</p><p className="text-sm">{removal.effect}</p><div className="flex flex-wrap gap-2"><Button disabled={disabled || !patchable} onClick={() => void submit(removal.command)}>确认移除此条</Button><Button disabled={busy || pending} variant="outline" onClick={() => setRemoval(null)}>保留此条</Button></div></section>}
    </>}
    <Button variant="outline" disabled={busy || !ready || pending} onClick={() => void reload()}>重新读取固定定义</Button>
  </div></ReadingPanel>;
}
