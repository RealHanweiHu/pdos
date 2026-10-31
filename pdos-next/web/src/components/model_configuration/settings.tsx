"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { readinessText, validateRequest, type ModelConfigurationProps, type ModelMetadata } from "./contracts";

const emptyMetadata: ModelMetadata = {
  protocol: "openai-compatible", base_url: "", model: "", model_version: "",
  max_output_tokens: 2048, context_window_tokens: null, openai_output_parameter: "max_completion_tokens",
  openai_response_mode: "tools", streaming: true,
  timeout_seconds: 30, response_bytes: 1048576,
};
const inputClass = "w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";

export function ModelConfigurationSettings(props: ModelConfigurationProps) {
  return <section className="grid min-w-0 gap-4 rounded-lg border border-border bg-card p-4" aria-label="租户模型配置">
    <div><h2 className="text-base font-semibold">模型设置</h2><p className="mt-1 text-sm text-muted-foreground">支持任意提供 OpenAI 兼容 Chat Completions API 的服务商，也保留 Anthropic 原生协议。填写服务商的基础 URL 和模型 ID，密钥由服务端安全绑定。</p><p className="mt-1 text-sm text-muted-foreground">配置用于当前租户。保存或启用后，仍须核对用途资格、本次材料授权与预算。</p></div>
    {props.reading ? <div className="grid gap-1 text-sm">
      <p>当前版本：{props.reading.revision} · {props.reading.enabled ? "已启用配置" : "已停用"}</p>
      <p>密钥：{props.reading.credential_display}</p>
      <p>上下文窗口：{props.reading.metadata.context_window_tokens ?? "未填写（按 32,000 估算）"}</p>
      <p className="break-all text-muted-foreground">{props.reading.metadata.model} · {props.reading.metadata.model_version}</p>
    </div> : <p className="text-sm text-muted-foreground">尚未保存模型配置。</p>}
    <p role="status" className="text-sm">{readinessText(props.readiness)}</p>
    <SettingsEditor key={`${props.reading?.version_id ?? "new"}:${props.reading?.revision ?? 0}`} {...props} />
  </section>;
}

function SettingsEditor({ reading, canEdit, onPreview, pending }: ModelConfigurationProps) {
  const prefix = useId();
  const [metadata, setMetadata] = useState<ModelMetadata>(() => reading ? {
    ...reading.metadata, openai_response_mode: reading.metadata.openai_response_mode ?? "auto",
    streaming: reading.metadata.streaming ?? true,
  } : emptyMetadata);
  const [enabled, setEnabled] = useState(reading?.enabled ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(true);
  const locked = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const unavailable = !canEdit || !onPreview || !!pending || busy;
  function change<K extends keyof ModelMetadata>(field: K, value: ModelMetadata[K]) {
    setMetadata(current => ({ ...current, [field]: value })); setError("");
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (unavailable || !onPreview || locked.current) return;
    const request = { expected_revision: reading?.revision ?? 0, metadata, enabled };
    const validation = validateRequest(request);
    if (validation) { setError(validation); return; }
    locked.current = true; setBusy(true); setError("");
    try { await onPreview(request); }
    catch { if (active.current) setError("未取得有效预览，请核对权限和当前版本后重试。"); }
    finally { locked.current = false; if (active.current) setBusy(false); }
  }
  return <form className="grid min-w-0 gap-3" onSubmit={submit}>
    {!canEdit && <p className="text-sm text-muted-foreground">仅当前授权管理员可修改模型配置。</p>}
    {!onPreview && <p className="text-sm text-muted-foreground">模型配置办理接口待接入，当前不能提交。</p>}
    <fieldset disabled={unavailable} className="grid min-w-0 gap-3 sm:grid-cols-2">
      <label htmlFor={`${prefix}-protocol`} className="grid gap-1 text-sm">协议
        <select id={`${prefix}-protocol`} disabled={!!metadata.connection_id} value={metadata.protocol} onChange={e => { change("protocol", e.target.value as ModelMetadata["protocol"]); change("openai_response_mode", "auto"); }} className={inputClass}>
          <option value="openai-compatible">OpenAI 兼容</option><option value="anthropic-native">Anthropic 原生</option>
        </select>
      </label>
      <label htmlFor={`${prefix}-base`} className="grid gap-1 text-sm">服务端点（基础 URL）
        <input id={`${prefix}-base`} type="url" required readOnly={!!metadata.connection_id} maxLength={500} autoComplete="off" placeholder="https://api.example.com/v1" value={metadata.base_url} onChange={e => change("base_url", e.target.value)} className={inputClass} />
      </label>
      <label htmlFor={`${prefix}-model`} className="grid gap-1 text-sm">模型 ID
        <input id={`${prefix}-model`} required readOnly={!!metadata.connection_id} maxLength={200} autoComplete="off" value={metadata.model} onChange={e => change("model", e.target.value)} className={inputClass} />
      </label>
      <label htmlFor={`${prefix}-version`} className="grid gap-1 text-sm">模型版本
        <input id={`${prefix}-version`} required readOnly={!!metadata.connection_id} maxLength={200} autoComplete="off" value={metadata.model_version} onChange={e => change("model_version", e.target.value)} className={inputClass} />
      </label>
      <label htmlFor={`${prefix}-tokens`} className="grid gap-1 text-sm">最大输出 tokens
        <input id={`${prefix}-tokens`} type="number" required min={1} max={32768} step={1} value={metadata.max_output_tokens} onChange={e => change("max_output_tokens", Number(e.target.value))} className={inputClass} />
      </label>
      <label htmlFor={`${prefix}-context-window`} className="grid gap-1 text-sm">上下文窗口（tokens）
        <input id={`${prefix}-context-window`} type="number" min={1024} max={10000000} step={1} value={metadata.context_window_tokens ?? ""} onChange={e => change("context_window_tokens", e.target.value === "" ? null : Number(e.target.value))} className={inputClass} />
        <span className="text-xs text-muted-foreground">不填时按 32,000 估算</span>
      </label>
      <label htmlFor={`${prefix}-parameter`} className="grid gap-1 text-sm">OpenAI 输出参数
        <select id={`${prefix}-parameter`} disabled={metadata.protocol !== "openai-compatible"} value={metadata.openai_output_parameter} onChange={e => change("openai_output_parameter", e.target.value as ModelMetadata["openai_output_parameter"])} className={inputClass}>
          <option value="max_completion_tokens">max_completion_tokens</option><option value="max_tokens">max_tokens</option>
        </select>
      </label>
      <label htmlFor={`${prefix}-format`} className="grid gap-1 text-sm">OpenAI 响应格式
        <select id={`${prefix}-format`} disabled={metadata.protocol !== "openai-compatible"} value={metadata.openai_response_mode} onChange={e => change("openai_response_mode", e.target.value as ModelMetadata["openai_response_mode"])} className={inputClass}>
          <option value="auto">原有适配（兼容已保存配置）</option><option value="tools">工具调用（无需 JSON Schema 扩展）</option><option value="json_schema">JSON Schema</option><option value="json_object">JSON 对象</option><option value="text">JSON 文本（无需格式扩展）</option>
        </select>
      </label>
      <label htmlFor={`${prefix}-streaming`} className="flex items-center gap-2 text-sm">
        <input id={`${prefix}-streaming`} type="checkbox" checked={metadata.streaming} onChange={e => change("streaming", e.target.checked)} />接口支持流式响应
      </label>
      <label htmlFor={`${prefix}-timeout`} className="grid gap-1 text-sm">超时（秒）
        <input id={`${prefix}-timeout`} type="number" required min={1} max={90} step="any" value={metadata.timeout_seconds} onChange={e => change("timeout_seconds", Number(e.target.value))} className={inputClass} />
      </label>
      <label htmlFor={`${prefix}-bytes`} className="grid gap-1 text-sm">响应上限（字节）
        <input id={`${prefix}-bytes`} type="number" required min={1024} max={2097152} step={1} value={metadata.response_bytes} onChange={e => change("response_bytes", Number(e.target.value))} className={inputClass} />
      </label>
      <label htmlFor={`${prefix}-enabled`} className="flex items-center gap-2 text-sm sm:col-span-2">
        <input id={`${prefix}-enabled`} type="checkbox" checked={enabled} onChange={e => { setEnabled(e.target.checked); setError(""); }} />启用此配置
      </label>
    </fieldset>
    {metadata.connection_id && <p className="text-sm text-muted-foreground">通过「添加服务商」保存新的地址、模型或 API Key，再从列表切换。</p>}
    <p className="text-sm text-muted-foreground">密钥由服务端安全绑定，此处仅显示掩码。任何配置或密钥版本变更都需重新核对资格。</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <Button type="submit" disabled={unavailable} className="w-fit">{busy ? "正在取得预览…" : "核对并预览"}</Button>
  </form>;
}
