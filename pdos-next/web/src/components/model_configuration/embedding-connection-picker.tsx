"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { embeddingConnectionFrom, embeddingConnectionMetadata, newEmbeddingConnectionRequest, type EmbeddingConnection, type EmbeddingConnectionForm } from "@/lib/embedding-connections";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import type { AddConnectionRequest } from "./connection-editor";
import type { ModelConnection } from "./contracts";
import type { EmbeddingMetadata } from "@/lib/embedding-settings";

const inputClass = "w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";
const emptyForm: EmbeddingConnectionForm = { name: "", base: "", model: "", version: "", key: "", priced: false, source: "", inputRate: "", requestFee: "0", byteBound: "", framing: "", verified: false };

export function EmbeddingConnectionEditor({ disabled = false, onSave, onCancel }: { disabled?: boolean; onSave: (request: AddConnectionRequest) => Promise<void>; onCancel: () => void }) {
  const prefix = useId(), [form, setForm] = useState(emptyForm), [pending, setPending] = useState<AddConnectionRequest | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const locked = useRef(false), epoch = useRef(0);
  useEffect(() => { const current = ++epoch.current; return () => { epoch.current = current + 1; }; }, []);
  function change<K extends keyof EmbeddingConnectionForm>(key: K, value: EmbeddingConnectionForm[K]) { setForm(current => ({ ...current, [key]: value })); setError(""); }
  async function send(request: AddConnectionRequest) {
    if (locked.current || disabled) return; const current = epoch.current; locked.current = true; setBusy(true); setError("");
    try { await onSave(request); if (epoch.current === current) { setForm(emptyForm); setPending(null); } }
    catch (failure) {
      if (epoch.current !== current) return;
      const status = (failure as { status?: number }).status;
      if (status === undefined || status >= 500) { setPending(request); setError("安全保存结果尚未确认，保留原请求可再次核对。刷新后先查看已保存连接。"); }
      else { setPending(null); setError(status === 403 ? "当前没有保存连接的管理员权限。" : "保存未完成，请核对连接、价格与服务器安全存储。"); }
    } finally { locked.current = false; if (epoch.current === current) setBusy(false); }
  }
  function submit(event: FormEvent) {
    event.preventDefault(); if (disabled || busy || pending) return;
    try { void send(newEmbeddingConnectionRequest(form)); } catch (failure) { setError((failure as Error).message); }
  }
  const unavailable = disabled || busy || !!pending;
  return <form onSubmit={submit} className="min-w-0 space-y-3 rounded-lg border border-border p-3" aria-label="新增独立 Embedding 凭据连接">
    <h4 className="text-sm font-medium">新增独立 Embedding 连接</h4>
    <p className="text-xs text-muted-foreground">API Key 直接保存到现有服务器安全存储。保存连接不会切换当前聊天模型，也不会启用后台索引。换 Key 时新增一份连接，再在配置预览中一次确认使用新连接。</p>
    <div className="grid min-w-0 gap-3 sm:grid-cols-2">
      <fieldset disabled={unavailable} className="contents">
        {([{ key: "name", label: "显示名称", max: 120, required: false }, { key: "model", label: "Embedding 模型 ID", max: 160, required: true }, { key: "base", label: "Embedding 基础 URL", max: 500, required: true }, { key: "version", label: "模型版本", max: 160, required: true }] as const).map(field => <label key={field.key} className="grid min-w-0 gap-1 text-sm" htmlFor={`${prefix}-${field.key}`}>{field.label}<input className={inputClass} id={`${prefix}-${field.key}`} type={field.key === "base" ? "url" : "text"} required={field.required} maxLength={field.max} autoComplete="off" value={form[field.key]} onChange={event => change(field.key, event.target.value)}/>{field.key === "base" && <span className="text-xs text-muted-foreground">填写基础地址，不含 /embeddings。</span>}</label>)}
        <label className="grid min-w-0 gap-1 text-sm sm:col-span-2" htmlFor={`${prefix}-key`}>独立 API Key<input className={inputClass} id={`${prefix}-key`} required type="password" maxLength={8192} autoComplete="new-password" spellCheck={false} value={form.key} onChange={event => change("key", event.target.value)}/><span className="text-xs text-muted-foreground">密钥不进入配置预览、历史、回执或本地恢复记录。</span></label>
        <details className="space-y-3 sm:col-span-2"><summary className="cursor-pointer text-sm">Embedding 价格与计量（USD）</summary><div className="mt-3 space-y-3"><label className="flex items-center gap-2 text-sm" htmlFor={`${prefix}-priced`}><input id={`${prefix}-priced`} type="checkbox" checked={form.priced} onChange={event => change("priced", event.target.checked)}/>同时保存已核对的计量资料</label><p className="text-xs text-muted-foreground">不填可先保存连接；启用索引前须有有效计量。本次核对有效期为 30 天。Embedding 只计输入 tokens 和请求费用。</p>{form.priced && <>
          <label className="grid gap-1 text-sm" htmlFor={`${prefix}-source`}>价格与计费依据<input className={inputClass} id={`${prefix}-source`} required maxLength={2000} value={form.source} onChange={event => change("source", event.target.value)}/></label>
          <div className="grid gap-3 sm:grid-cols-2">{([{ key: "inputRate", label: "输入 / 百万 tokens（USD）" }, { key: "requestFee", label: "每次请求费用（USD）" }, { key: "byteBound", label: "每 UTF-8 字节的 token 上界" }, { key: "framing", label: "额外封装 token 上界" }] as const).map(field => <label key={field.key} className="grid gap-1 text-sm" htmlFor={`${prefix}-${field.key}`}>{field.label}<input className={inputClass} id={`${prefix}-${field.key}`} type="number" required min={field.key === "byteBound" ? 1 : 0} step={field.key === "framing" ? 1 : "any"} value={form[field.key]} onChange={event => change(field.key, event.target.value)}/></label>)}</div>
          <label className="flex items-start gap-2 text-sm" htmlFor={`${prefix}-verified`}><input className="mt-1" id={`${prefix}-verified`} type="checkbox" checked={form.verified} onChange={event => change("verified", event.target.checked)}/>我已核对以上输入价格、请求费用和文本计费上界，覆盖此 Embedding 模型全部费用。</label>
        </>}</div></details>
      </fieldset>
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <div className="flex flex-wrap gap-2">{pending ? <Button type="button" disabled={disabled || busy} onClick={() => void send(pending)}>核对原连接保存请求</Button> : <Button type="submit" disabled={disabled || busy}>{busy ? "正在安全保存…" : "安全保存此独立连接"}</Button>}<Button type="button" variant="outline" disabled={busy} onClick={() => { setForm(emptyForm); setPending(null); onCancel(); }}>关闭</Button></div>
  </form>;
}

export function EmbeddingConnectionPicker({ api, disabled, onChoose, onEditingChange }: { api: WorkspaceTransport; disabled: boolean; onEditingChange: (editing: boolean) => void; onChoose: (metadata: Pick<EmbeddingMetadata, "connection_id" | "base_url" | "model" | "model_version">) => void }) {
  const prefix = useId(), epoch = useRef(0), [connections, setConnections] = useState<EmbeddingConnection[]>([]), [selected, setSelected] = useState(""), [adding, setAdding] = useState(false), [loading, setLoading] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  async function load(current: number) {
    const result = await api<{ connections: ModelConnection[] }>("v1/model-connections");
    if (epoch.current === current) { setConnections(result.connections.map(embeddingConnectionFrom).filter((row): row is EmbeddingConnection => row !== null)); setError(""); }
  }
  useEffect(() => {
    const current = ++epoch.current;
    const timer = setTimeout(() => { setLoading(true); void load(current).catch(() => { if (epoch.current === current) setError("已保存连接暂不可读，请核对管理员权限及安全存储。仍可填写已知的公开连接 ID。"); }).finally(() => { if (epoch.current === current) setLoading(false); }); }, 0);
    return () => { clearTimeout(timer); epoch.current = current + 1; };
    // Parent identity/category remounts this selector.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);
  const chosen = connections.find(row => row.id === selected);
  return <div className="min-w-0 space-y-3 rounded-lg border border-border p-3 sm:col-span-2" aria-label="选择或新增独立 Embedding 连接">
    <div className="flex flex-wrap items-center justify-between gap-2"><h4 className="text-sm font-medium">独立凭据连接</h4><Button type="button" variant="outline" size="sm" disabled={disabled || adding} onClick={() => { setAdding(true); onEditingChange(true); setNotice(""); }}>新增独立连接 / 换 Key</Button></div>
    <p className="text-xs text-muted-foreground">选择已保存且已核对支持 /embeddings 的 OpenAI 兼容连接，或添加一份独立连接。不会自动沿用当前聊天模型的 Key。要停止后台索引，请取消下方启用并预览确认。</p>
    {error && <p role="status" className="text-xs text-muted-foreground">{error}</p>}{notice && <p role="status" className="text-sm">{notice}</p>}
    <div className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1fr)_auto]"><label className="grid min-w-0 gap-1 text-sm" htmlFor={`${prefix}-saved`}>已保存连接<select className={inputClass} id={`${prefix}-saved`} value={selected} disabled={disabled || loading || adding} onChange={event => setSelected(event.target.value)}><option value="">{loading ? "正在读取连接…" : "明确选择一份连接"}</option>{connections.map(row => <option key={row.id} value={row.id}>{row.name} · {row.model} · {row.pricing_configured ? "已填计量" : "计量待填"}</option>)}</select></label><Button type="button" variant="outline" className="self-end" disabled={disabled || !chosen || adding} onClick={() => { if (chosen) { onChoose(embeddingConnectionMetadata(chosen)); setNotice("已带入此连接信息；请核对维度、类别与预算，再明确选择是否启用。"); } }}>带入配置表单</Button></div>
    {chosen && <p className="break-all text-xs text-muted-foreground">{chosen.base_url} · {chosen.model_version} · 服务商 {chosen.provider}。接口兼容和已填计量不代表服务可用或已获质量资格。</p>}
    <Button type="button" variant="ghost" size="sm" disabled={disabled || loading || adding} onClick={() => { const current = epoch.current; setLoading(true); void load(current).catch(() => { if (epoch.current === current) setError("连接暂不可读，请稍后重新读取。"); }).finally(() => { if (epoch.current === current) setLoading(false); }); }}>重新读取已保存连接</Button>
    {adding && <EmbeddingConnectionEditor disabled={disabled} onCancel={() => { setAdding(false); onEditingChange(false); }} onSave={async request => {
      const current = epoch.current;
      const result = await api<ModelConnection>("v1/model-connections", request);
      const saved = embeddingConnectionFrom(result);
      if (!saved) throw new Error("未取得匹配的公开连接信息，请核对原保存请求。");
      if (saved.base_url.replace(/\/+$/, "") !== request.metadata.base_url || saved.model !== request.metadata.model || saved.model_version !== request.metadata.model_version) throw new Error("保存回执与原连接配置不一致，请核对原请求。");
      if (epoch.current !== current) return;
      setConnections(rows => [...rows.filter(row => row.id !== saved.id), saved]); setSelected(saved.id); setAdding(false); onEditingChange(false); setNotice("独立连接已安全保存，当前聊天模型保持原选择。已带入配置表单；填写维度后再预览确认。"); onChoose(embeddingConnectionMetadata(saved));
    }}/>}
  </div>;
}
