"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { EmbeddingConnectionPicker } from "./embedding-connection-picker";
import { proofClockCurrent } from "@/lib/proof-clock";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import { canReconcileEmbeddingCall, embeddingCategoryName, embeddingDollars, embeddingMicroDollars, embeddingReceiptMatches, embeddingStateName, newEmbeddingCommand, parseEmbeddingPending, validEmbeddingPreview, type EmbeddingCall, type EmbeddingCategory, type EmbeddingCommand, type EmbeddingMetadata, type EmbeddingPreview, type EmbeddingProfile, type EmbeddingReading, type ReconcileEmbeddingCall, type SaveEmbeddingProfile } from "@/lib/embedding-settings";

const inputClass = "w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";
const boxClass = "min-w-0 space-y-3 rounded-lg border border-border bg-card p-4";
type Prepare = (operation: EmbeddingCommand["operation"], payload: EmbeddingCommand["payload"]) => Promise<void>;

export function EmbeddingProfileEditor({ profile, budget, disabled = false, onPreview, api }: { profile: EmbeddingProfile | null; budget: EmbeddingReading["budget"]; disabled?: boolean; onPreview?: Prepare; api?: WorkspaceTransport }) {
  const prefix = useId();
  const [metadata, setMetadata] = useState<EmbeddingMetadata>(() => profile ? structuredClone(profile.metadata) : { base_url: "", model: "", model_version: "", dimensions: 0, connection_id: "", data_categories: ["internal"], include_customer_original: false });
  const [enabled, setEnabled] = useState(profile?.enabled ?? false);
  const [amount, setAmount] = useState(embeddingDollars(budget?.limit_micro_usd ?? 0));
  const [error, setError] = useState(""), [connectionEditing, setConnectionEditing] = useState(false);
  const unavailable = disabled || !onPreview || connectionEditing;
  function change<K extends keyof EmbeddingMetadata>(key: K, value: EmbeddingMetadata[K]) { setMetadata(current => ({ ...current, [key]: value })); setError(""); }
  function category(category: EmbeddingCategory, checked: boolean) {
    setMetadata(current => ({ ...current, data_categories: checked ? [...current.data_categories.filter(item => item !== category), category] : current.data_categories.filter(item => item !== category), ...(category === "customer_original" ? { include_customer_original: checked } : {}) }));
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (unavailable || !onPreview) return; setError("");
    try {
      const payload: SaveEmbeddingProfile = { profile_id: profile?.profile_id ?? crypto.randomUUID(), expected_revision: profile?.revision ?? 0, metadata: { ...metadata, base_url: metadata.base_url.trim().replace(/\/+$/, ""), model: metadata.model.trim(), model_version: metadata.model_version.trim(), connection_id: metadata.connection_id.trim() }, enabled, expected_budget_revision: budget?.revision ?? 0, index_budget_micro_usd: embeddingMicroDollars(amount) };
      await onPreview("embedding.profile.save", payload);
    } catch (failure) { setError((failure as Error).message); }
  }
  return <div className="min-w-0 space-y-3">{api && <EmbeddingConnectionPicker api={api} disabled={disabled || !onPreview} onEditingChange={setConnectionEditing} onChoose={connection => { setMetadata(current => ({ ...current, ...connection })); setEnabled(false); setError(""); }}/>}<form onSubmit={submit} className="min-w-0 space-y-3">
    <h3 className="font-medium">{profile ? `修改第 ${profile.revision} 版配置` : "新增独立 Embedding 配置"}</h3>
    <fieldset disabled={unavailable} className="grid min-w-0 gap-3 sm:grid-cols-2">
      <label className="grid gap-1 text-sm" htmlFor={`${prefix}-base`}>Embedding 服务端点<input id={`${prefix}-base`} className={inputClass} type="url" required maxLength={500} autoComplete="off" placeholder="https://api.example.com/v1" value={metadata.base_url} onChange={event => change("base_url", event.target.value)}/></label>
      <label className="grid gap-1 text-sm" htmlFor={`${prefix}-model`}>Embedding 模型 ID<input id={`${prefix}-model`} className={inputClass} required maxLength={160} autoComplete="off" value={metadata.model} onChange={event => change("model", event.target.value)}/></label>
      <label className="grid gap-1 text-sm" htmlFor={`${prefix}-version`}>模型版本<input id={`${prefix}-version`} className={inputClass} required maxLength={160} autoComplete="off" value={metadata.model_version} onChange={event => change("model_version", event.target.value)}/></label>
      <label className="grid gap-1 text-sm" htmlFor={`${prefix}-dimensions`}>向量维度<input id={`${prefix}-dimensions`} className={inputClass} type="number" required min={1} max={2000} step={1} value={metadata.dimensions || ""} onChange={event => change("dimensions", Number(event.target.value))}/></label>
      <label className="grid gap-1 text-sm sm:col-span-2" htmlFor={`${prefix}-connection`}>独立凭据连接 ID<input id={`${prefix}-connection`} className={inputClass} required autoComplete="off" maxLength={36} placeholder="已登记的独立 Embedding 连接 ID" value={metadata.connection_id} onChange={event => change("connection_id", event.target.value)}/><span className="text-xs text-muted-foreground">填写服务器登记的公开连接 ID；独立凭据由服务器安全绑定，聊天连接不会自动复用。</span></label>
      <label className="grid gap-1 text-sm" htmlFor={`${prefix}-budget`}>租户索引预算（USD）<input id={`${prefix}-budget`} className={inputClass} required inputMode="decimal" autoComplete="off" value={amount} onChange={event => setAmount(event.target.value)}/><span className="text-xs text-muted-foreground">跨品类共用，包含已发生和保守占账费用。</span></label>
      <div className="space-y-2 text-sm"><p>允许后台索引的数据类别</p>{(["public", "synthetic", "internal", "customer"] as const).map(item => <label className="flex items-center gap-2" key={item} htmlFor={`${prefix}-${item}`}><input id={`${prefix}-${item}`} type="checkbox" checked={metadata.data_categories.includes(item)} onChange={event => category(item, event.target.checked)}/>{embeddingCategoryName(item)}</label>)}</div>
      <label className="flex items-start gap-2 text-sm sm:col-span-2" htmlFor={`${prefix}-original`}><input className="mt-1" id={`${prefix}-original`} type="checkbox" checked={metadata.include_customer_original} onChange={event => category("customer_original", event.target.checked)}/><span>另行包含客户原件<span className="mt-1 block text-xs text-muted-foreground">确认启用后，可读且符合出站类别限制的客户原件会发送给此 Embedding 服务商。</span></span></label>
      <label className="flex items-start gap-2 text-sm sm:col-span-2" htmlFor={`${prefix}-enabled`}><input className="mt-1" id={`${prefix}-enabled`} type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)}/><span>启用后台 Embedding 索引<span className="mt-1 block text-xs text-muted-foreground">保存停用配置不会出站。启用须在下一步核对服务商、数据类别、预计来源与费用，再一次确认。</span></span></label>
    </fieldset>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <Button type="submit" disabled={unavailable}>核对配置并预览</Button>
  </form></div>;
}

function ReconciliationEditor({ call, disabled, onPreview }: { call: EmbeddingCall; disabled: boolean; onPreview: Prepare }) {
  const prefix = useId(), [tokens, setTokens] = useState(""), [amount, setAmount] = useState(""), [evidence, setEvidence] = useState(""), [error, setError] = useState("");
  return <form className="space-y-3" onSubmit={event => { event.preventDefault(); if (disabled) return; setError(""); void (async () => {
    try { if (!/^\d+$/.test(tokens)) throw new Error("请填写实际输入 tokens 整数。"); const payload: ReconcileEmbeddingCall = { call_id: call.call_id, expected_revision: call.revision, input_tokens: Number(tokens), actual_micro_usd: embeddingMicroDollars(amount), evidence_ref: evidence.trim() }; await onPreview("embedding.call.reconcile", payload); }
    catch (failure) { setError((failure as Error).message); }
  })(); }}>
    <p className="text-sm text-muted-foreground">仅对账原调用费用；不会重发请求、恢复索引或改变原结果未知事实。</p>
    <fieldset disabled={disabled} className="grid min-w-0 gap-3 sm:grid-cols-2">
      <label className="grid gap-1 text-sm" htmlFor={`${prefix}-tokens`}>实际输入 tokens<input className={inputClass} id={`${prefix}-tokens`} type="number" min={0} max={2147483647} step={1} required value={tokens} onChange={event => setTokens(event.target.value)}/></label>
      <label className="grid gap-1 text-sm" htmlFor={`${prefix}-cost`}>实际费用（USD）<input className={inputClass} id={`${prefix}-cost`} inputMode="decimal" autoComplete="off" required value={amount} onChange={event => setAmount(event.target.value)}/></label>
      <label className="grid gap-1 text-sm sm:col-span-2" htmlFor={`${prefix}-evidence`}>对账凭证引用<input className={inputClass} id={`${prefix}-evidence`} required minLength={3} maxLength={500} autoComplete="off" value={evidence} onChange={event => setEvidence(event.target.value)}/></label>
    </fieldset>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}<Button variant="outline" type="submit" disabled={disabled}>核对原费用并预览</Button>
  </form>;
}

export function EmbeddingUsage({ reading, disabled, onPreview, onMore }: { reading: EmbeddingReading; disabled: boolean; onPreview: Prepare; onMore: () => void }) {
  return <div className="min-w-0 space-y-3">
    <div className="space-y-1 text-sm"><h3 className="font-medium">索引预算与批次</h3>{reading.budget ? <p>租户索引预算：{embeddingDollars(reading.budget.limit_micro_usd)} USD · 已计费 {embeddingDollars(reading.budget.spent_micro_usd)} · 占用 {embeddingDollars(reading.budget.held_micro_usd)} · 第 {reading.budget.revision} 版</p> : <p>尚未建立租户索引预算。</p>}<p className="text-muted-foreground">批次与调用记录显示当前品类；预算在租户内累计。</p>{Object.keys(reading.batch_counts).length ? <ul className="flex flex-wrap gap-x-4 gap-y-1">{Object.entries(reading.batch_counts).map(([state, count]) => <li key={state}>{embeddingStateName(state)} {count}</li>)}</ul> : <p className="text-muted-foreground">当前品类尚无后台索引批次。</p>}</div>
    <details><summary className="cursor-pointer text-sm font-medium">查看后台调用与费用记录（{reading.calls.length} 条已读取）</summary><div className="mt-3 space-y-3">{reading.calls.map(call => <article key={call.call_id} className="min-w-0 space-y-2 rounded-lg border border-border p-3 text-sm">
      <p>{embeddingStateName(call.state)} · {new Date(call.created_at).toLocaleString("zh-CN")}</p><p className="break-all">服务商：{call.provider ?? "待核对"} · {call.data_categories.map(embeddingCategoryName).join("、")}</p><p>{call.source_count} 个来源 · {call.character_count} 字符 · 第 {call.attempt} 次尝试</p><p>已计 {embeddingDollars(call.charged_micro_usd)} USD · 原预留 {embeddingDollars(call.reserved_micro_usd)} USD · {call.usage_known ? `输入 ${call.input_tokens} tokens` : "用量未知，保守占账"}</p><p className="break-all text-xs text-muted-foreground">调用 {call.call_id} · 版本 {call.revision}<br/>批次 {call.batch_id} · {embeddingStateName(call.batch_state)}</p>
      {canReconcileEmbeddingCall(call) && <details><summary className="cursor-pointer">核对这次原调用费用</summary><div className="mt-3"><ReconciliationEditor call={call} disabled={disabled} onPreview={onPreview}/></div></details>}
    </article>)}{!reading.calls.length && <p className="text-sm text-muted-foreground">当前没有后台 Embedding 调用记录。</p>}{reading.next_cursor && <Button variant="outline" disabled={disabled} onClick={onMore}>读取更多调用记录</Button>}</div></details>
  </div>;
}

export function EmbeddingReview({ preview }: { preview: EmbeddingPreview }) {
  const payload = preview.command.payload, review = preview.review;
  return <div className="min-w-0 space-y-3 text-sm">
    {"profile_id" in payload ? <>
      <h3 className="text-base font-semibold">一次确认：{payload.enabled ? "启用后台 Embedding 索引" : "保存停用的 Embedding 配置"}</h3>
      <p>保存为第 {String(review.next_revision)} 版。{payload.enabled ? "确认生效后，后台批次可将符合条件的资料发送给下列服务商。" : "停止新批次与向量召回，退役向量进入清理；检索使用关键词。"}</p>
      <p className="break-all">服务商端点：{payload.metadata.base_url}</p><p>服务商身份：{typeof review.provider === "string" ? review.provider : "停用保存，当前身份未绑定"}</p><p className="break-all">模型：{payload.metadata.model} · 版本 {payload.metadata.model_version} · {payload.metadata.dimensions} 维</p>
      <p>数据类别：{payload.metadata.data_categories.map(embeddingCategoryName).join("、")}</p><p>客户原件：{payload.metadata.include_customer_original ? "已单独选择包含" : "不包含"}</p>
      <p>独立凭据：{review.credential_status === "bound" ? "已绑定" : "尚未绑定，启用前须由服务器核对"}</p>
      <p>预计来源：{review.expected_sources === null ? "停用保存不估算" : `${String(review.expected_sources)} 个`}{review.estimate_truncated === true ? "（当前可读范围的有界估算，尚有来源未计入）" : ""}</p>
      <p>预计费用：{typeof review.estimated_cost_micro_usd === "number" ? `${embeddingDollars(review.estimated_cost_micro_usd)} USD` : "停用保存不估算"} · 租户索引预算 {embeddingDollars(payload.index_budget_micro_usd)} USD</p>
      <p className="text-muted-foreground">估算限当前本人可读来源，实际批次分别核对和计费。默认检索仍为关键词；混合检索须按同题集实测收益决定。</p>
    </> : <><h3 className="text-base font-semibold">一次确认：核对原 Embedding 费用</h3><p className="break-all">原调用 {payload.call_id} · 第 {payload.expected_revision} 版</p><p>原计费 {embeddingDollars(Number(review.charged_micro_usd))} → 实际 {embeddingDollars(payload.actual_micro_usd)} USD · 输入 {payload.input_tokens} tokens</p><p className="break-all">凭证：{payload.evidence_ref}</p><p>仅对账原费用；不重新调用、不恢复索引、不改变原结果未知事实。</p></>}
    <p className="text-xs text-muted-foreground">本次确认有效至 {new Date(preview.expires_at).toLocaleString("zh-CN")}。</p>
  </div>;
}

export function ConnectedEmbeddingSettings({ api, categoryId, principalId }: { api: WorkspaceTransport; categoryId: string; principalId: string }) {
  const [reading, setReading] = useState<EmbeddingReading | null>(null), [selected, setSelected] = useState("");
  const [preview, setPreview] = useState<EmbeddingPreview | null>(null), [pending, setPending] = useState<EmbeddingCommand | null>(null);
  const [busy, setBusy] = useState(true), [broken, setBroken] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const epoch = useRef(0), locked = useRef(false), dialog = useRef<HTMLDialogElement>(null), noticeFocus = useRef<HTMLParagraphElement>(null);
  const key = `pdos-embedding-settings:v1:${principalId}:${categoryId}`;
  useEffect(() => { if (preview && !dialog.current?.open) dialog.current?.showModal(); else if (!preview) dialog.current?.close(); }, [preview]);
  useEffect(() => { if (notice) noticeFocus.current?.focus(); }, [notice]);
  async function load(current: number, after?: string) {
    const value = await api<EmbeddingReading>(`v1/embedding-profile?page_size=20${after ? `&after=${encodeURIComponent(after)}` : ""}`);
    if (!Number.isSafeInteger(value.category_revision) || value.category_revision < 1 || value.default_retrieval !== "keyword" || value.scope !== "current_requester_readable") throw new Error("当前配置范围或版本无法核对，请重新读取。");
    if (epoch.current === current) setReading(previous => after && previous ? { ...value, calls: [...previous.calls, ...value.calls.filter(call => !previous.calls.some(old => old.call_id === call.call_id))] } : value);
    return value;
  }
  useEffect(() => {
    const current = ++epoch.current; locked.current = true;
    void (async () => {
      try { const raw = localStorage.getItem(key); if (raw) { try { const original = parseEmbeddingPending(raw, categoryId); if (epoch.current === current) setPending(original); } catch (failure) { if (epoch.current === current) setBroken(true); throw failure; } } }
      catch (failure) { if (epoch.current === current) setError((failure as Error).message); }
      try { await load(current); } catch (failure) { if (epoch.current === current) setError((failure as Error).message); }
      finally { if (epoch.current === current) { locked.current = false; setBusy(false); } }
    })();
    return () => { epoch.current = current + 1; };
    // The parent remounts on principal/category changes; opening only reads metadata.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, categoryId, key]);
  async function run(action: (current: number) => Promise<void>) {
    if (locked.current) return; const current = epoch.current; locked.current = true; setBusy(true); setError("");
    try { await action(current); } catch (failure) { if (epoch.current === current) setError((failure as Error).message); throw failure; }
    finally { if (epoch.current === current) { locked.current = false; setBusy(false); } }
  }
  const prepare: Prepare = async (operation, payload) => {
    if (pending || preview || broken) return;
    await run(async current => {
      const value = await load(current);
      const original = newEmbeddingCommand(categoryId, value.category_revision, operation, payload);
      const result = await api<EmbeddingPreview>("v1/commands/preview", original);
      if (!validEmbeddingPreview(result, original)) throw new Error("预览与本次原配置或费用不一致，请重新核对。");
      if (epoch.current === current) { setPreview(result); setNotice(""); }
    });
  };
  async function save(original: EmbeddingCommand, current: number) {
    localStorage.setItem(key, JSON.stringify(original));
    if (epoch.current === current) { setPending(original); setPreview(null); }
    try {
      const receipt = await api<unknown>("v1/commands", original);
      if (!embeddingReceiptMatches(receipt, original, principalId)) throw new Error("回执与原请求不一致，请保留同一请求继续核对。");
    } catch (failure) {
      const status = (failure as { status?: number }).status;
      if (epoch.current === current && status !== undefined && status >= 400 && status < 500) { localStorage.removeItem(key); setPending(null); }
      throw failure;
    }
    localStorage.removeItem(key);
    if (epoch.current === current) { setPending(null); setNotice(original.operation === "embedding.call.reconcile" ? "原调用费用已对账，未重发 Embedding 请求。" : "Embedding 配置已保存，默认检索仍为关键词。"); }
    try { await load(current); } catch { if (epoch.current === current) setError("已取得保存回执；当前配置读取失败，请刷新核对。"); }
  }
  const disabled = busy || !reading || !!pending || !!preview || broken;
  const profile = reading?.profiles.find(item => item.profile_id === selected) ?? null;
  return <section className={boxClass} aria-label="独立 Embedding 索引设置">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-base font-semibold">企业资料 Embedding</h2><Button size="sm" variant="outline" disabled={busy} onClick={() => void run(async current => { await load(current); }).catch(() => {})}>读取配置与费用</Button></div>
    <p className="text-sm text-muted-foreground">独立配置后台语义索引。当前默认使用关键词检索；打开本页只读取设置与记录。</p>
    {busy && <p role="status" className="text-sm">正在核对 Embedding 设置…</p>}{error && <p role="alert" className="break-words text-sm text-destructive">{error}</p>}{notice && <p ref={noticeFocus} tabIndex={-1} role="status" className="text-sm">{notice}</p>}
    {!reading && !busy && <p className="text-sm text-muted-foreground">仅当前本人租户管理员可读取和办理独立 Embedding 配置。</p>}
    {reading && <>
      <div className="space-y-2"><h3 className="text-sm font-medium">当前配置版本</h3>{reading.profiles.length ? <ul className="divide-y divide-border">{reading.profiles.map(item => <li key={item.profile_id} className="flex min-w-0 flex-wrap items-center justify-between gap-2 py-2"><div className="min-w-0 text-sm"><p className="break-all">{item.metadata.model} · 第 {item.revision} 版 · {item.enabled ? "已启用" : "已停用"}</p><p className="break-all text-xs text-muted-foreground">{item.metadata.base_url} · {item.metadata.dimensions} 维 · 独立凭据{item.credential_status === "bound" ? "已绑定" : "待绑定"}</p></div><Button variant="outline" size="sm" disabled={disabled} onClick={() => setSelected(item.profile_id)}>修改或停用</Button></li>)}</ul> : <p className="text-sm text-muted-foreground">尚未保存独立 Embedding 配置。</p>}{reading.profiles_truncated && <p className="text-sm text-muted-foreground">当前仅显示前 100 份配置，列表未完整。</p>}</div>
      {selected && <Button variant="ghost" size="sm" disabled={disabled} onClick={() => setSelected("")}>改为新增独立配置</Button>}
      <EmbeddingProfileEditor key={`${profile?.profile_version_id ?? "new"}:${reading.budget?.revision ?? 0}`} profile={profile} budget={reading.budget} disabled={disabled} onPreview={prepare} api={api}/>
      <EmbeddingUsage reading={reading} disabled={disabled} onPreview={prepare} onMore={() => void run(async current => { await load(current, reading.next_cursor!); }).catch(() => {})}/>
    </>}
    {pending && <div className="space-y-3 rounded-lg border border-primary/40 p-3 text-sm"><p>原{pending.operation === "embedding.call.reconcile" ? "费用对账" : "配置保存"}结果尚待核对。保留同一请求，重开本页不会自动提交。</p><Button disabled={busy || !reading} onClick={() => void run(current => save(pending, current)).catch(() => {})}>核对并重试原请求</Button></div>}
    {broken && <Button variant="outline" disabled={busy || !reading} onClick={() => { try { localStorage.removeItem(key); setBroken(false); setError(""); } catch { setError("恢复记录暂时无法移除。"); } }}>已核对当前配置，移除损坏的恢复记录</Button>}
    <dialog ref={dialog} aria-label="一次确认 Embedding 设置或费用" className="m-auto max-h-[85dvh] w-[calc(100%-2rem)] max-w-2xl overflow-y-auto rounded-lg border border-border bg-background p-5 text-foreground backdrop:bg-black/50" onCancel={event => { event.preventDefault(); if (!busy) setPreview(null); }}>{preview && <div className="space-y-4 [overflow-wrap:anywhere]"><EmbeddingReview preview={preview}/><div className="flex flex-wrap justify-end gap-2"><Button variant="outline" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button><Button disabled={busy || !proofClockCurrent("T1", preview.expires_at)} onClick={() => { if (!proofClockCurrent("T1", preview.expires_at)) { setPreview(null); setError("本次确认已过期，请重新预览。"); return; } void run(current => save(preview.command, current)).catch(() => {}); }}>本人一次确认保存</Button></div></div>}</dialog>
  </section>;
}
