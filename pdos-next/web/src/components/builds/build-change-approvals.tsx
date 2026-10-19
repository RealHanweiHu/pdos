"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowClockwise, CheckCircle, ShieldCheck, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { ChangeEffectivityReading } from "@/components/change_control/reading";
import { orderPlanReading, type OrderApi, type OrderReadSource, type OrderSource } from "@/lib/build-change-orders-view";
import {
  approvalDisciplineNames, approvalInputs, blankApprovalDraft, blankApprovalLocal, makeApprovalCommand,
  readApprovalScope, restoreApprovals, validApprovalPreview, validApprovalReceipt,
  type ApprovalDraft, type ApprovalLocal, type ApprovalOrder, type ApprovalPending, type ApprovalPreview, type ApprovalScope,
} from "@/lib/build-change-approvals-view";
import { qualityRecord, qualitySource, qualitySourceKey, qualityStable, validQualitySource } from "@/lib/build-quality-loop-view";
import { sourceLines, type DefinitionSource } from "@/lib/product-view";

type Props = { projectId?: string; changeId: string; product: { id: string; revision: number }; principalId: string; api: OrderApi; onSaved: () => void | Promise<void>; blocked?: boolean; onLockChange?: (locked: boolean) => void };
const time = (value: string | null) => value === null ? "未另设到期时点" : value === "server_on_save" ? "保存时由服务器记录" : Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "尚未提供";

function Evidence({ reference, sources }: { reference: OrderReadSource; sources: DefinitionSource[] }) {
  if (!validQualitySource(reference)) return <p className="subtle">{reference.kind === "command" ? "固定保存回执" : "固定领域依据"} · v{reference.revision}；保留其真实出处。</p>;
  const row = sources.find(source => source.id === reference.id && source.revision === reference.revision), line = Number(reference.position.split(";")[0].slice(5));
  return <blockquote className="space-y-1 border-l-2 border-primary pl-3 text-sm [overflow-wrap:anywhere]"><p className="font-medium">{row?.title ?? "固定原文名称待核对"} · v{reference.revision} · 第 {line} 行</p><p className="whitespace-pre-wrap">{row ? sourceLines(row.content)[line - 1] ?? "原行尚未返回" : "当前原文不可读，请重新核对。"}</p></blockquote>;
}
function EvidenceChoice({ sources, chosen, disabled, onChange }: { sources: DefinitionSource[]; chosen: OrderSource[]; disabled: boolean; onChange: (sources: OrderSource[]) => void }) {
  const [id, setId] = useState(""), [line, setLine] = useState(1), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const alive = useRef(true), selection = useRef(0), selected = sources.find(row => row.id === id);
  const invalidate = useCallback(() => { selection.current++; }, []);
  useEffect(() => { alive.current = true; return () => { alive.current = false; invalidate(); }; }, [invalidate]);
  async function choose() {
    if (!selected || disabled || busy) return;
    const read = ++selection.current; setBusy(true); setError("");
    try { const ref = await qualitySource(selected, line); if (alive.current && read === selection.current) onChange(chosen.some(row => qualitySourceKey(row) === qualitySourceKey(ref)) ? chosen : [...chosen, ref]); }
    catch (failure) { if (alive.current && read === selection.current) setError(failure instanceof Error ? failure.message : "请核对所选原文完整行。"); }
    finally { if (alive.current && read === selection.current) setBusy(false); }
  }
  return <fieldset disabled={disabled || busy} className="space-y-3"><legend className="mb-2 font-medium">本人本次批准的精确原文依据</legend><div className="grid gap-3 sm:grid-cols-2"><label>当前可读原文<select value={id} onChange={event => { selection.current++; setId(event.target.value); setLine(1); }}><option value="">明确选择原文</option>{sources.map(row => <option key={row.id} value={row.id} disabled={row.status !== "active"}>{row.title} · v{row.revision}{row.status !== "active" ? " · 当前不可采用" : ""}</option>)}</select></label><label>完整行号<input type="number" min={1} step={1} value={line} onChange={event => { selection.current++; setLine(Number(event.target.value)); }}/></label></div>{selected && <blockquote className="whitespace-pre-wrap border-l-2 border-border pl-3 text-sm [overflow-wrap:anywhere]">{sourceLines(selected.content)[line - 1] ?? "本行尚未在原文中返回"}</blockquote>}<Button type="button" variant="outline" disabled={!selected || selected.status !== "active"} onClick={() => void choose()}>采用这一完整行作为批准依据</Button>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}{chosen.map(ref => <div key={qualitySourceKey(ref)} className="flex items-start gap-3 rounded-lg border border-border p-3"><div className="min-w-0 grow"><Evidence reference={ref} sources={sources}/></div><Button variant="ghost" size="icon" aria-label="移除此条批准依据" onClick={() => onChange(chosen.filter(row => qualitySourceKey(row) !== qualitySourceKey(ref)))}><X/></Button></div>)}</fieldset>;
}
const checkLabels: Record<string, string> = { authority: "服务器核对的具名职责与资格", policy: "当前正式政策", authorized: "当前操作授权", qualified: "当前用途专业资格", roles: "具名专业职责", missing: "尚未满足的条件", reason_codes: "服务器拒绝条件", code: "核对原因", detail: "具体缺项", reason: "具体原因", unknown: "仍然未知的影响", effect: "本次实际作用", required_disciplines: "须具名决定的专业", valid_from: "政策生效起点", valid_until: "政策有效至", expires_at: "有效至", nature: "事实性质", text: "具名说明", purpose: "固定用途", engineering: "工程", manufacturing: "制造", customer: "客户", regulatory: "法规", synthetic: "本地合成演练", real: "真实事实" };
function ServerChecks({ value }: { value: unknown }) {
  if (value == null) return <p className="subtle">尚未返回，不能据此认定条件已满足。</p>;
  if (typeof value === "boolean") return <span>{value ? "是" : "否"}</span>;
  if (typeof value === "string") return <span className="whitespace-pre-wrap text-sm [overflow-wrap:anywhere]">{checkLabels[value] ?? value}</span>;
  if (Array.isArray(value)) return value.length ? <ul className="list-disc space-y-2 pl-5">{value.map((row, index) => <li key={index}><ServerChecks value={row}/></li>)}</ul> : <p className="subtle">本类未列出条件；不据此补足未知范围。</p>;
  if (!qualityRecord(value)) return null;
  return <dl className="space-y-3">{Object.entries(value).filter(([key]) => !!checkLabels[key]).map(([key, row]) => <div key={key}><dt className="subtle mb-1">{checkLabels[key]}</dt><dd><ServerChecks value={row}/></dd></div>)}</dl>;
}
function Decisions({ order, principalId, sources }: { order: ApprovalOrder; principalId: string; sources: DefinitionSource[] }) {
  return <div className="grid gap-3 sm:grid-cols-2">{order.required_disciplines.map(role => { const decision = order.approvals.find(row => row.discipline === role); return <section key={role} className="space-y-3 rounded-lg border border-border p-3"><h4 className="font-medium">{approvalDisciplineNames[role]} · {decision ? "已有具名批准记录" : "尚无具名批准记录"}</h4>{decision ? <><p className="text-sm">{decision.actor_id === principalId ? "当前登录本人" : "其他具名批准人"} · {time(decision.at)}<br/>批准有效期：{time(decision.expires_at)}</p><p className="whitespace-pre-wrap text-sm">{decision.text}</p>{decision.sources.map((ref, index) => <Evidence key={index} reference={ref} sources={sources}/>)}<details><summary className="cursor-pointer text-sm">查看固定具名身份</summary><p className="mt-2 break-all text-sm">{decision.actor_id}</p></details></> : <p className="subtle">仅显示实际决定；选择专业或取得预览均不代表已经批准。</p>}</section>; })}</div>;
}

export function BuildChangeApprovals(props: Props) { return <ApprovalPanel key={`${props.principalId}:${props.product.id}:${props.projectId ?? ""}:${props.changeId}`} {...props}/>; }
function ApprovalPanel({ product, principalId, api, onSaved, changeId, projectId = "", blocked = false, onLockChange }: Props) {
  const [local, setLocal] = useState<ApprovalLocal>(blankApprovalLocal), [data, setData] = useState<ApprovalScope | null>(null), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState(""), [inputs, setInputs] = useState<unknown>(null), [preview, setPreview] = useState<ApprovalPreview | null>(null), [previewScope, setPreviewScope] = useState("");
  const state = useRef(local), alive = useRef(true), restored = useRef(false), sequence = useRef(0), lock = useRef(false), scopeRef = useRef(""), dialog = useRef<HTMLDialogElement>(null), trigger = useRef<HTMLElement | null>(null);
  const invalidateReads = useCallback(() => { sequence.current++; }, []);
  const storageKey = `pdos-next:build-change-approvals:${principalId}:${product.id}:project:${projectId}:change:${changeId}`;
  const scope = JSON.stringify(qualityStable([principalId, product.id, product.revision, projectId, changeId, data])), pending = local.pending, draft = local.drafts[local.selectedOrderId] ?? blankApprovalDraft(), selected = data?.orders.find(row => row.id === local.selectedOrderId), latest = data?.orders.at(-1);
  useEffect(() => { scopeRef.current = scope; }, [scope]);
  const activePreview = preview && previewScope === scope ? preview : null, unlocked = !blocked && !loading && !!data && !busy && !pending && !preview;
  useEffect(() => { onLockChange?.(busy || !!pending || !!preview); }, [busy, pending, preview, onLockChange]);
  useEffect(() => () => { onLockChange?.(false); }, [onLockChange]);
  function save(patch: Partial<ApprovalLocal>): boolean {
    const next = { ...state.current, ...patch }; state.current = next; setLocal(next);
    try { localStorage.setItem(storageKey, JSON.stringify({ schema_version: 1, product_id: product.id, principal_id: principalId, project_id: projectId, change_id: changeId, ...next })); return true; }
    catch { setNotice("本机恢复记录暂不可保存；本次尚未发送。请保留本页，恢复后继续同一原请求。"); return false; }
  }
  const refresh = useCallback(async () => {
    const read = ++sequence.current, current = () => alive.current && read === sequence.current;
    try { const value = await readApprovalScope(api, product.id, changeId, projectId, current); if (!value || !current()) return; setData(value); setLoading(false); setError(""); }
    catch (failure) { if (!current()) return; setData(null); setInputs(null); setPreview(null); setLoading(false); throw failure; }
  }, [api, product.id, changeId, projectId]);
  useEffect(() => {
    alive.current = true;
    void Promise.resolve().then(() => {
      if (!alive.current) return;
      if (!restored.current) { try { const value = restoreApprovals(JSON.parse(localStorage.getItem(storageKey) ?? "null"), product.id, principalId, projectId, changeId); if (value) { state.current = value; setLocal(value); } } catch { /* Only this exact named project/Change slot can restore. */ } restored.current = true; }
      return refresh();
    }).catch(failure => { if (alive.current) setError(failure instanceof Error ? failure.message : "当前变更令读取失败，请重新读取。"); });
    return () => { alive.current = false; invalidateReads(); };
  }, [refresh, storageKey, product.id, principalId, projectId, changeId, invalidateReads]);
  useEffect(() => { if (activePreview) { if (!dialog.current?.open) dialog.current?.showModal(); } else { dialog.current?.close(); if (preview) void Promise.resolve().then(() => { if (alive.current) { setPreview(null); setNotice("项目、变更版本或固定计划已变化，旧预览已废弃，请重新核对。"); } }); } }, [activePreview, preview]);
  function reread() { if (lock.current || blocked) return; setPreview(null); setInputs(null); setLoading(true); void refresh().catch(failure => { if (alive.current) setError(failure instanceof Error ? failure.message : "当前正式依据读取失败。"); }); }
  function chooseOrder(id: string) { if (!unlocked) return; save({ selectedOrderId: id, drafts: id && !state.current.drafts[id] ? { ...state.current.drafts, [id]: blankApprovalDraft() } : state.current.drafts }); setInputs(null); }
  function edit(patch: Partial<ApprovalDraft>) { if (!unlocked || !selected) return; save({ drafts: { ...state.current.drafts, [selected.id]: { ...(state.current.drafts[selected.id] ?? blankApprovalDraft()), ...patch } } }); }
  function closePreview() { if (lock.current || state.current.pending) return; setPreview(null); dialog.current?.close(); trigger.current?.focus(); }
  async function perform(waiting: ApprovalPending, element?: HTMLElement) {
    if (lock.current || blocked || loading || !data || waiting.command.payload.change_id !== changeId || waiting.orderId !== state.current.selectedOrderId) return;
    const originalScope = scopeRef.current; sequence.current++; lock.current = true; setBusy(true); setError(""); setNotice(""); if (element) trigger.current = element;
    let current = waiting, committed = false;
    try {
      if (!save({ pending: current })) return;
      if (current.stage === "inputs") {
        const value = await api<unknown>(`v1/products/${product.id}/change-execution/inputs`, current.command);
        if (!alive.current) return;
        setInputs(value);
        const command = approvalInputs(value, current.command);
        if (!command) { save({ pending: null }); setError("服务器尚未允许本次具名批准；请核对下方真实条件和缺项，本次未提交。"); return; }
        current = { ...current, stage: "preview", command }; if (!save({ pending: current })) return;
      }
      if (current.stage === "preview") {
        const value = await api<unknown>("v1/commands/preview", current.command);
        if (!alive.current) return;
        if (originalScope !== scopeRef.current) { save({ pending: null }); setNotice("固定范围已变化，返回预览已废弃，请重新核对。"); return; }
        if (!validApprovalPreview(value, current.command, data, current.orderId, principalId)) throw new Error("未取得与本变更令、计划和本人专业一致的具名实质预览，请保留原请求重新核对。");
        save({ pending: null }); setPreview(value); setPreviewScope(originalScope); return;
      }
      const value = await api<unknown>("v1/commands", current.command);
      if (!validApprovalReceipt(value, current.command, principalId)) throw new Error("尚未取得同一具名提交的确定回执，请保留原请求核对。");
      committed = true;
      if (!alive.current) return;
      save({ pending: null }); setPreview(null); setInputs(null); dialog.current?.close(); setNotice("已取得本专业具名批准的保存回执。其他专业、实际实施与生效仍以各自真实事实为准。"); await refresh(); await onSaved();
    } catch (failure) {
      if (!alive.current) return;
      const status = qualityRecord(failure) && typeof failure.status === "number" ? failure.status : undefined;
      setPreview(null); dialog.current?.close();
      if (committed) { setNotice("已取得确定批准回执，随后读取失败。请重新读取实际事实，不重复批准。"); }
      else if (status === 401 || status === 403) { setData(null); setInputs(null); setError("当前项目、原文或具名权限不可用；原请求已保留，请先重新读取当前范围。"); }
      else { setError(failure instanceof Error ? failure.message : "当前批准条件尚未满足或未取得确定回执，请保留同一原请求核对。"); if (current.stage !== "execute" && [400, 404, 409, 410, 422].includes(status ?? 0)) save({ pending: null }); }
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function prepare(element: HTMLElement) {
    if (!unlocked || !data) return;
    try { const command = makeApprovalCommand(product, data, local.selectedOrderId, draft, crypto.randomUUID(), crypto.randomUUID()); void perform({ stage: "inputs", orderId: local.selectedOrderId, command }, element); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "请完整核对本人专业、具名说明与原文依据。"); }
  }
  const canPrepare = unlocked && selected?.id === latest?.id && data?.context.change.status === "review";
  return <section className="space-y-4 rounded-lg border border-border p-4 [&_*]:min-w-0 [overflow-wrap:anywhere]" aria-label="变更令具名专业批准"><header className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="flex items-center gap-2 font-semibold"><ShieldCheck/>3 · 本变更令的具名专业批准</h3><p className="subtle mt-2">按实际待批准计划分别办理本专业决定。权限、资格、提出者独立性和当前版本由服务器核对。</p></div><Button variant="outline" disabled={busy || blocked} onClick={reread}><ArrowClockwise/>重新读取专业决定</Button></header>
    {loading && <p role="status" className="subtle">正在读取本项目、所选变更的当前正式计划与真实专业决定…</p>}{error && <p role="alert" className="rounded-lg border border-destructive p-3 text-sm">{error}</p>}{notice && <p role="status" className="rounded-lg border border-border p-3 text-sm">{notice}</p>}
    {pending && <div className="space-y-3 rounded-lg border border-primary p-3"><p className="text-sm">{!data ? "当前范围不可读，原请求已保留；重新读取当前权限后才能继续核对。" : pending.stage === "execute" ? "原具名提交的结果尚待核对。显式重放会使用同一原提交；若此前未到达服务器，会继续此前已明确确认的批准，不新建决定。" : "原范围核对尚未完成；仅继续同一原请求，取得实质预览后仍须本人明确确认。"}</p><Button disabled={busy || blocked || loading || !data} onClick={event => void perform(pending, event.currentTarget)}>{pending.stage === "execute" ? "重放并核对同一原提交" : "继续核对同一原请求"}</Button></div>}
    {data && <><p className="text-sm">{String(data.context.change.request.title ?? "所选变更")} · 当前 v{data.context.change.revision} · {data.context.change.status === "review" ? "待专业决定" : data.context.change.status === "approved" ? "专业批准已登记" : "当前状态仅供核对"}</p>{data.context.policy?.nature === "synthetic" && <p className="rounded-lg border border-primary p-3 text-sm">本地合成演练；此处决定不代表真实生产资格或阶段验收。</p>}{data.context.missing.length > 0 && <section className="rounded-lg border border-border p-3"><ServerChecks value={{ missing: data.context.missing }}/></section>}
      <label className="block">明确选择已保存变更令<select disabled={!unlocked} value={local.selectedOrderId} onChange={event => chooseOrder(event.target.value)}><option value="">选择正式计划，不默认首条</option>{data.orders.map((order, index) => <option key={order.id} value={order.id}>变更令 {index + 1} · {order === latest ? "当前办理计划" : "历史计划，仅供阅读"} · {order.approvals.length}/{order.required_disciplines.length} 项专业决定</option>)}</select></label>{!data.orders.length && <p className="subtle">尚无已保存变更令。先准备正式计划，再分别办理专业决定。</p>}
      {selected && <><Decisions order={selected} principalId={principalId} sources={data.sources}/><details className="rounded-lg border border-border p-3"><summary className="cursor-pointer font-medium">查看本变更令完整固定计划与逐对象处置</summary><div className="mt-3"><ChangeEffectivityReading plan={orderPlanReading(selected.plan, Array.isArray(data.context.change.request.audience) ? data.context.change.request.audience.map(String) : [])}/></div></details>
        {selected.id === latest?.id && data.context.change.status === "review" ? <><fieldset disabled={!canPrepare} className="space-y-4"><label className="block">本人本次办理的专业<select value={draft.discipline} onChange={event => edit({ discipline: event.target.value as ApprovalDraft["discipline"] })}><option value="">明确选择本人专业</option>{selected.required_disciplines.map(role => <option key={role} value={role} disabled={selected.approvals.some(row => row.discipline === role)}>{approvalDisciplineNames[role]}{selected.approvals.some(row => row.discipline === role) ? " · 已有决定" : " · 待本人具名核对"}</option>)}</select></label><label className="block">本人具名批准说明<textarea required rows={4} maxLength={2000} value={draft.text} onChange={event => edit({ text: event.target.value })}/></label><label className="block">本次批准有效至（可选，含时区）<input value={draft.expiresAt} placeholder="留空不另设到期时点" onChange={event => edit({ expiresAt: event.target.value })}/></label><p className="subtle">不补为当前时间，不延长固定计划、政策或来源的有效期。</p><EvidenceChoice key={selected.id} sources={data.sources} chosen={draft.sources} disabled={!canPrepare} onChange={sources => edit({ sources })}/></fieldset><Button disabled={!canPrepare || !draft.discipline || !draft.text.trim() || !draft.sources.length} onClick={event => prepare(event.currentTarget)}>核对本专业具名批准的实质预览</Button></> : <p className="subtle">本计划当前不开放新专业批准；已有记录保留阅读，修订后须按新的固定计划重新办理。</p>}
      </>}
    </>}
    {inputs !== null && <details className="rounded-lg border border-border p-3" open><summary className="cursor-pointer font-medium">本次服务器实质核对与缺项</summary><div className="mt-3"><ServerChecks value={qualityRecord(inputs) ? inputs.review ?? inputs : inputs}/></div></details>}
    <dialog ref={dialog} className="m-auto max-h-[85dvh] w-[calc(100%-2rem)] max-w-3xl overflow-y-auto rounded-lg border border-border bg-background p-5 text-foreground backdrop:bg-black/50" onCancel={event => { event.preventDefault(); closePreview(); }}>{activePreview && data && selected && <div className="space-y-4"><div className="flex items-start justify-between gap-3"><h3 className="font-semibold">以当前本人具名批准{approvalDisciplineNames[activePreview.command.payload.discipline]}范围</h3><Button variant="ghost" size="icon" disabled={busy || !!pending} aria-label="关闭本次具名批准预览" onClick={closePreview}><X/></Button></div><p className="text-sm">{activePreview.review.effect}</p><p className="whitespace-pre-wrap text-sm">{activePreview.command.payload.text}</p><p className="subtle">批准有效至：{time(activePreview.command.payload.expires_at)}。决定人是当前登录本人；决定时间及正式决定身份在实际保存时由服务器记录。</p>{activePreview.command.payload.sources.map(ref => <Evidence key={qualitySourceKey(ref)} reference={ref} sources={data.sources}/>)}<ServerChecks value={{ authority: activePreview.review.authority, policy: activePreview.review.policy, unknown: activePreview.review.unknown }}/><ChangeEffectivityReading plan={orderPlanReading(selected.plan, Array.isArray(data.context.change.request.audience) ? data.context.change.request.audience.map(String) : [])}/><p className="subtle">{activePreview.expires_at === null ? "提交时仍需重核当前固定依据与本人权限。" : `本次预览有效至 ${time(activePreview.expires_at)}。`}本次只办理上述专业批准，其他专业与实际实施保持独立。</p><div className="flex flex-wrap gap-3"><Button disabled={busy || !!pending || blocked} onClick={() => { const original = { ...activePreview.command, payload: { ...activePreview.command.payload, approval_token: undefined } }; if (!validApprovalPreview(activePreview, original, data, selected.id, principalId)) { closePreview(); setError("本次预览已过期或固定内容已变化，请重新核对。"); return; } void perform({ stage: "execute", orderId: selected.id, command: activePreview.command }); }}><CheckCircle/>本人具名批准上述本专业范围</Button><Button variant="outline" disabled={busy || !!pending} onClick={closePreview}>返回核对</Button></div></div>}</dialog>
  </section>;
}
