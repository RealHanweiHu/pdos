"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { EvidencePicker } from "./evidence-picker";
import { SourceCitations } from "./source-citations";
import { ProductRequestError, request, type Evidence, type SourceRef } from "./product-work-api";

type DefinitionRef = { id: string; version: number; revision: number; digest: string; release_id: string };
type Locator = { system_kind: "erp" | "plm"; source_system: string; master_kind: "material" | "product" | "cad_revision"; external_id: string; external_revision: string; external_as_of: string; sources: SourceRef[] };
export type MasterReference = Locator & { id: string; action: "register" | "correct" | "withdraw"; previous_id: string | null; reason: string; created_by_user_id: string; created_at: string; definition_ref: DefinitionRef; product_snapshot: unknown; context_status: "current" | "stale" | "no_current_release"; version: number };
export type MasterReferenceList = { product: { id: string; version: number; code: string; name: string; level: string; lifecycle: string }; current_definition: DefinitionRef | null; context_digest: string; items: MasterReference[] };
type Save = Locator & { request_id: string; expected_context_digest: string; action: MasterReference["action"]; previous_id: string | null; reason: string };
type Draft = Omit<Save, "request_id" | "expected_context_digest">;
type Props = { base: string; productId: string; canManage: boolean; disabled?: boolean; evidence: Evidence[]; onPendingChange?: (pending: boolean) => void; onAuthorityLost?: (message: string) => void };
const field = "mt-1 block w-full rounded-md border bg-background px-3 py-2 text-sm";
const actions = { register: "新登记", correct: "纠正", withdraw: "撤回" };
const kinds = { material: "物料", product: "产品", cad_revision: "CAD 修订" };
const empty = (): Draft => ({ action: "register", previous_id: null, system_kind: "erp", source_system: "", master_kind: "material", external_id: "", external_revision: "", external_as_of: "", sources: [], reason: "" });

export function ProductMasterReferences(props: Props) {
  return <MasterReferencesPanel key={JSON.stringify([props.base, props.productId])} {...props} />;
}
function MasterReferencesPanel({ base, productId, canManage, disabled = false, evidence, onPendingChange, onAuthorityLost }: Props) {
  const [data, setData] = useState<MasterReferenceList | null>(null), [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState(""), [denied, setDenied] = useState(false), [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [pending, setPending] = useState(false);
  const live = useRef(true), readRevision = useRef(0), writeLock = useRef(false), original = useRef<Save | null>(null);
  const callbacks = useRef({ onPendingChange, onAuthorityLost });
  useEffect(() => { callbacks.current = { onPendingChange, onAuthorityLost }; }, [onPendingChange, onAuthorityLost]);
  const path = `${base}/products/${productId}/master-references`;
  const release = useCallback(() => { original.current = null; setPending(false); callbacks.current.onPendingChange?.(false); }, []);
  const authorityLost = useCallback((message: string) => {
    if (!live.current) return;
    readRevision.current += 1; writeLock.current = false; setBusy(false); setData(null); setDraft(null); setDenied(true); setLoading(false); setError(message);
    if (original.current) release();
    callbacks.current.onAuthorityLost?.(message);
  }, [release]);
  const fail = useCallback((failure: unknown) => {
    const message = failure instanceof Error ? failure.message : "交接引用暂不可用";
    if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) authorityLost(message); else setError(message);
  }, [authorityLost]);
  async function load() {
    if (!live.current || original.current || writeLock.current || disabled) return;
    const revision = ++readRevision.current; setLoading(true); setError("");
    try { const value = await request<MasterReferenceList>(path); if (live.current && revision === readRevision.current) { setData(value); setDenied(false); setDraft(null); } }
    catch (failure) { if (live.current && revision === readRevision.current) fail(failure); }
    finally { if (live.current && revision === readRevision.current) setLoading(false); }
  }
  useEffect(() => {
    live.current = true; const revision = ++readRevision.current;
    void request<MasterReferenceList>(path).then(value => { if (live.current && revision === readRevision.current) { setData(value); setDenied(false); } }).catch(failure => { if (live.current && revision === readRevision.current) fail(failure); }).finally(() => { if (live.current && revision === readRevision.current) setLoading(false); });
    return () => { live.current = false; readRevision.current += 1; if (original.current) { original.current = null; callbacks.current.onPendingChange?.(false); } };
  }, [path, fail]);
  const replaced = new Set(data?.items.map(item => item.previous_id).filter(Boolean));
  const canStart = canManage && !disabled && !pending && !busy && !loading && !denied;
  function edit(item?: MasterReference, action: MasterReference["action"] = "register") {
    if (!canStart || original.current || writeLock.current || (action !== "withdraw" && !data?.current_definition)) return;
    setError(""); setDraft(item ? { action, previous_id: item.id, system_kind: item.system_kind, source_system: item.source_system, master_kind: item.master_kind, external_id: item.external_id, external_revision: item.external_revision, external_as_of: item.external_as_of, sources: item.sources, reason: "" } : empty());
  }
  async function save(retry = false) {
    if (!live.current || writeLock.current || !canManage || (!retry && (disabled || original.current)) || !data || denied) return;
    let body = original.current;
    if (!body) {
      if (retry || !draft || (draft.action !== "withdraw" && !data.current_definition)) return;
      if (!draft.sources.length) { setError("请关联至少一个实际来源快照"); return; }
      body = JSON.parse(JSON.stringify({ ...draft, expected_context_digest: data.context_digest, request_id: crypto.randomUUID() })) as Save;
      original.current = body; setPending(true); callbacks.current.onPendingChange?.(true);
    }
    writeLock.current = true; const revision = ++readRevision.current; setLoading(false); setBusy(true); setError("");
    try {
      const value = await request<MasterReferenceList>(path, "POST", body);
      if (!live.current || revision !== readRevision.current) return;
      release(); setData(value); setDraft(null); setDenied(false);
    } catch (failure) {
      if (!live.current || revision !== readRevision.current) return;
      if (failure instanceof ProductRequestError && failure.status < 500 && ![408, 429].includes(failure.status)) release();
      fail(failure);
    } finally { if (live.current && revision === readRevision.current) { writeLock.current = false; setBusy(false); } }
  }
  return <section className="space-y-3 rounded-lg border p-4" aria-label="ERP/PLM交接引用">
    <div><h4 className="font-semibold">ERP/PLM交接引用</h4><p className="mt-1 text-sm text-muted-foreground">外部主数据由 ERP/PLM 维护，登记仅记录引用。此处登记不代表外部已确认。</p></div>
    <Button type="button" variant="outline" size="sm" disabled={disabled || pending || busy || loading} onClick={() => void load()}>{denied ? "重新核对交接引用权限" : "刷新交接引用"}</Button>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {denied ? <p className="text-sm">交接引用权限需重新核对，已隐藏登记、来源与历史资料。</p> : <>
      {data ? <><p className="text-sm">对象：{data.product.name} · {data.product.code} · {data.product.level}</p><p className="text-sm">{data.current_definition ? `当前已发布定义：${data.current_definition.revision} · v${data.current_definition.version}` : "当前没有已发布定义，新登记与纠正暂不可用；可撤回仍有效的旧引用。"}</p></> : <p className="text-sm">{loading ? "正在读取交接引用…" : "交接引用暂不可用，可刷新重试。"}</p>}
      {data && <><Button type="button" size="sm" disabled={!canStart || !data.current_definition || !!draft} onClick={() => edit()}>新登记交接引用</Button>{data.items.length === 0 && <p className="text-sm text-muted-foreground">尚无交接引用。</p>}
        <div className="space-y-3">{data.items.map(item => <article key={item.id} className="space-y-2 rounded-md border p-3"><h5 className="font-medium">{actions[item.action]} · {item.source_system} / {kinds[item.master_kind]} / {item.external_id}</h5><p className="text-xs">{item.system_kind.toUpperCase()} · 外部修订 {item.external_revision} · 来源时点 {new Date(item.external_as_of).toLocaleString()}</p><p className="text-xs">固定已发布定义：{item.definition_ref.revision} · v{item.definition_ref.version} · {item.definition_ref.digest.slice(0, 12)}</p><p className="break-all text-xs">登记人：{item.created_by_user_id} · {new Date(item.created_at).toLocaleString()} · {replaced.has(item.id) || item.action === "withdraw" ? "历史登记" : "当前登记"}</p><p className="text-sm">原因：{item.reason}</p>{item.context_status !== "current" && <p role="status" className="text-sm text-amber-700 dark:text-amber-400">{item.context_status === "no_current_release" ? "当前已无已发布定义，原引用保留待复查。" : "当前定义或对象已变化，原引用保留，需要复查。"}</p>}<SourceCitations base={base} references={item.sources} evidence={evidence} onAuthorityLost={authorityLost}/>{canManage && !replaced.has(item.id) && item.action !== "withdraw" && <div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={!canStart || !data.current_definition || !!draft} onClick={() => edit(item, "correct")}>纠正此引用</Button><Button type="button" size="sm" variant="outline" disabled={!canStart || !!draft} onClick={() => edit(item, "withdraw")}>撤回此引用</Button></div>}</article>)}</div>
      </>}
      {draft && <form className="space-y-3 rounded-md border p-3" onSubmit={event => { event.preventDefault(); void save(); }}><h5 className="font-medium">{actions[draft.action]}交接引用</h5><fieldset disabled={disabled || pending || busy || !canManage} className="space-y-3">
        {draft.action === "withdraw" ? <p className="text-sm">撤回只追加记录，保留 {draft.source_system} / {draft.external_id} / {draft.external_revision} 与原来源，不修改外部主数据。</p> : <><div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">外部系统类别<select className={field} value={draft.system_kind} onChange={event => { const system_kind = event.target.value as Locator["system_kind"]; setDraft({ ...draft, system_kind, master_kind: system_kind === "erp" ? "material" : "cad_revision" }); }}><option value="erp">ERP</option><option value="plm">PLM</option></select></label><label className="text-sm">主数据对象<select className={field} value={draft.master_kind} onChange={event => setDraft({ ...draft, master_kind: event.target.value as Locator["master_kind"] })}>{Object.entries(kinds).filter(([key]) => key === "product" || (draft.system_kind === "erp" ? key === "material" : key === "cad_revision")).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>{([['source_system','系统标识'],['external_id','外部对象标识'],['external_revision','外部修订']] as const).map(([key,label]) => <label key={key} className="text-sm">{label}<input required maxLength={256} className={field} value={draft[key]} onChange={event => setDraft({ ...draft, [key]: event.target.value })}/></label>)}<label className="text-sm">外部来源时点<input required type="datetime-local" className={field} value={draft.external_as_of ? (() => { const value = new Date(draft.external_as_of); return new Date(value.getTime() - value.getTimezoneOffset() * 60000).toISOString().slice(0,16); })() : ""} onChange={event => setDraft({ ...draft, external_as_of: event.target.value ? new Date(event.target.value).toISOString() : "" })}/></label></div><EvidencePicker options={evidence} selected={draft.sources.map(ref => ref.ref_id)} onChange={ids => setDraft({ ...draft, sources: ids.flatMap(id => { const source = evidence.find(item => item.id === id); return source ? [source.reference] : []; }) })}/></>}
        <label className="block text-sm">登记原因<textarea required maxLength={2048} className={field} value={draft.reason} onChange={event => setDraft({ ...draft, reason: event.target.value })}/></label><div className="flex gap-2"><Button disabled={!canManage || !draft.sources.length}>保存交接引用</Button><Button type="button" variant="outline" onClick={() => { if (!original.current && !writeLock.current) setDraft(null); }}>取消登记</Button></div>
      </fieldset></form>}
    </>}
    {pending && <div className="space-y-2 text-sm"><p role="status">保存结果尚未确认，已保留完整原请求。请先重试原请求再修改或离开。</p><Button type="button" variant="outline" disabled={busy || !canManage} onClick={() => void save(true)}>按原请求重试交接登记</Button></div>}
  </section>;
}
