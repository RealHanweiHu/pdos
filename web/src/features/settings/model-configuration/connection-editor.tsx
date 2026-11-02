"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import type { ModelConnection, ModelMetadata } from "./contracts";

const inputClass = "w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const rateFields = [["input_per_million", "输入 / 百万 tokens"], ["output_per_million", "输出 / 百万 tokens"], ["cache_read_per_million", "缓存读取 / 百万 tokens"], ["cache_creation_per_million", "缓存创建 / 百万 tokens"], ["request_fee", "每次请求费用"], ["text_tokens_per_utf8_byte", "每 UTF-8 字节的 token 上界"], ["text_framing_tokens", "额外封装 token 上界"]] as const;
type RateKey = typeof rateFields[number][0];
export type AddConnectionRequest = { request_id: string; name: string; metadata: ModelMetadata; api_key: string; pricing: Record<string, unknown> | null };

export function ConnectionEditor({ api, onSaved, onCancel }: { api: WorkspaceTransport; onSaved: (connection: ModelConnection) => void; onCancel: () => void }) {
  const [name, setName] = useState(""), [key, setKey] = useState("");
  const [base, setBase] = useState(""), [model, setModel] = useState(""), [version, setVersion] = useState("");
  const [protocol, setProtocol] = useState<ModelMetadata["protocol"]>("openai-compatible");
  const [mode, setMode] = useState<ModelMetadata["openai_response_mode"]>("tools");
  const [parameter, setParameter] = useState<ModelMetadata["openai_output_parameter"]>("max_tokens");
  const [streaming, setStreaming] = useState(true), [tokens, setTokens] = useState(2048);
  const [contextWindow, setContextWindow] = useState("");
  const [priced, setPriced] = useState(false), [source, setSource] = useState("");
  const [rates, setRates] = useState<Record<RateKey, string>>({ input_per_million: "0", output_per_million: "0", cache_read_per_million: "0", cache_creation_per_million: "0", request_fee: "0", text_tokens_per_utf8_byte: "1", text_framing_tokens: "4096" });
  const [confirmed, setConfirmed] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [pending, setPending] = useState<AddConnectionRequest | null>(null);
  const locked = useRef(false), disposed = useRef(false);
  useEffect(() => { disposed.current = false; return () => { disposed.current = true; }; }, []);
  async function send(request: AddConnectionRequest) {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError("");
    try {
      const saved = await api<ModelConnection>("v1/model-connections", request);
      if (disposed.current) return;
      setKey(""); setPending(null);
      if (!disposed.current) onSaved(saved);
    } catch (failure) {
      if (disposed.current) return;
      const status = (failure as { status?: number }).status;
      if (status === undefined || status >= 500) {
        setPending(request); setError("保存结果尚未确认，请核对原保存请求。刷新后可先查看已保存列表。");
      } else {
        setPending(null); setError(status === 403 ? "当前没有管理模型服务商的权限。" : "保存未完成，请核对配置、价格资料和服务器安全存储。");
      }
    } finally { locked.current = false; if (!disposed.current) setBusy(false); }
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || pending) return;
    if (priced && !confirmed) { setError("请确认已核对价格及计费上界。"); return; }
    const checked = new Date();
    const pricing = priced ? { ...rates, text_framing_tokens: Number(rates.text_framing_tokens), source: source.trim(), text_billing_source: source.trim(), verified_at: checked.toISOString(), valid_until: new Date(checked.getTime() + 30 * 86400000).toISOString(), currency: "USD", output_cap_covers_all_billing: true, covers_all_fees: true } : null;
    void send({ request_id: crypto.randomUUID(), name: name.trim() || model.trim(), api_key: key.trim(), pricing,
      metadata: { protocol, base_url: base.trim().replace(/\/$/, ""), model: model.trim(), model_version: version.trim() || model.trim(), max_output_tokens: tokens, context_window_tokens: contextWindow === "" ? null : Number(contextWindow), openai_output_parameter: parameter, openai_response_mode: protocol === "openai-compatible" ? mode : "auto", streaming, timeout_seconds: 30, response_bytes: 1048576 } });
  }
  return <form onSubmit={submit} className="space-y-4 rounded-lg border border-border bg-card p-4" aria-label="添加模型服务商">
    <div><h2 className="text-base font-semibold">添加服务商</h2><p className="mt-1 text-sm text-muted-foreground">保存连接后，可在列表中确认切换。</p></div>
    <fieldset disabled={busy || !!pending} className="grid min-w-0 gap-3 sm:grid-cols-2">
      <label className="grid gap-1 text-sm">显示名称<input className={inputClass} value={name} onChange={e => setName(e.target.value)} maxLength={120} placeholder="例如：我的服务商" autoComplete="off"/></label>
      <label className="grid gap-1 text-sm">模型名称<input required className={inputClass} value={model} onChange={e => setModel(e.target.value)} maxLength={200} placeholder="服务商提供的模型 ID" autoComplete="off"/></label>
      <label className="grid gap-1 text-sm sm:col-span-2">Base URL<input required type="url" className={inputClass} value={base} onChange={e => setBase(e.target.value)} maxLength={500} placeholder="https://api.example.com/v1" autoComplete="off"/><span className="text-xs text-muted-foreground">填写基础地址，不含 /chat/completions。</span></label>
      <label className="grid gap-1 text-sm sm:col-span-2">API Key<input required type="password" className={inputClass} value={key} onChange={e => setKey(e.target.value)} maxLength={8192} autoComplete="new-password" spellCheck={false}/><span className="text-xs text-muted-foreground">保存到服务器安全存储，已保存的 Key 只显示掩码。</span></label>
      <details className="sm:col-span-2"><summary className="cursor-pointer text-sm">高级接口选项</summary><div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-sm">协议<select className={inputClass} value={protocol} onChange={e => setProtocol(e.target.value as ModelMetadata["protocol"])}><option value="openai-compatible">OpenAI 兼容</option><option value="anthropic-native">Anthropic 原生</option></select></label>
        <label className="grid gap-1 text-sm">模型版本<input className={inputClass} value={version} onChange={e => setVersion(e.target.value)} maxLength={200} placeholder="留空沿用模型名称"/></label>
        <label className="grid gap-1 text-sm">输出参数<select className={inputClass} disabled={protocol !== "openai-compatible"} value={parameter} onChange={e => setParameter(e.target.value as typeof parameter)}><option value="max_tokens">max_tokens</option><option value="max_completion_tokens">max_completion_tokens</option></select></label>
        <label className="grid gap-1 text-sm">响应格式<select className={inputClass} disabled={protocol !== "openai-compatible"} value={mode} onChange={e => setMode(e.target.value as typeof mode)}><option value="tools">工具调用</option><option value="json_schema">JSON Schema</option><option value="json_object">JSON 对象</option><option value="text">JSON 文本</option></select></label>
        <label className="grid gap-1 text-sm">最大输出 tokens<input required className={inputClass} type="number" min={1} max={32768} step={1} value={tokens} onChange={e => setTokens(Number(e.target.value))}/></label>
        <label className="grid gap-1 text-sm">上下文窗口（tokens）<input className={inputClass} type="number" min={1024} max={10000000} step={1} value={contextWindow} onChange={e => setContextWindow(e.target.value)}/><span className="text-xs text-muted-foreground">不填时按 32,000 估算</span></label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={streaming} onChange={e => setStreaming(e.target.checked)}/>接口支持流式响应</label>
      </div></details>
      <details className="sm:col-span-2"><summary className="cursor-pointer text-sm">价格与计量（USD）</summary><div className="mt-3 space-y-3">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={priced} onChange={e => setPriced(e.target.checked)}/>同时保存已核对的计费资料</label>
        <p className="text-xs text-muted-foreground">实际调用前需要有效价格与计费资料；本次核对有效期为 30 天。</p>
        {priced && <><label className="grid gap-1 text-sm">价格及计费依据<input required className={inputClass} value={source} onChange={e => setSource(e.target.value)} maxLength={2000} placeholder="服务商价格页面或合同依据"/></label><div className="grid gap-3 sm:grid-cols-2">{rateFields.map(([field, label]) => <label key={field} className="grid gap-1 text-sm">{label}<input required className={inputClass} type="number" min={field === "text_tokens_per_utf8_byte" ? 1 : 0} step={field === "text_framing_tokens" ? 1 : "any"} value={rates[field]} onChange={e => setRates(current => ({ ...current, [field]: e.target.value }))}/></label>)}</div><label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)}/>我已核对全部费用及文本计费上界，输出上限包含思考等全部计费 tokens。</label></>}
      </div></details>
    </fieldset>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <div className="flex flex-wrap gap-2">{pending ? <Button type="button" disabled={busy} onClick={() => void send(pending)}>核对原保存请求</Button> : <Button type="submit" disabled={busy}>{busy ? "正在安全保存…" : "保存服务商"}</Button>}<Button type="button" variant="outline" disabled={busy} onClick={() => { disposed.current = true; setKey(""); setPending(null); onCancel(); }}>关闭</Button></div>
  </form>;
}
