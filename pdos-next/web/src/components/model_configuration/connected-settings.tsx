"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { proofClockCurrent } from "@/lib/proof-clock";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import type { ConfigurationReading, ModelConnection, ModelMetadata, SaveConfiguration } from "./contracts";
import { ConnectionEditor } from "./connection-editor";
import { ModelConfigurationSettings } from "./settings";

type Reading = { configuration: ConfigurationReading | null; category_revision: number; can_edit: boolean };
type Preview = { command: Record<string, unknown>; expires_at: string; review: { next_revision: number; enabled: boolean; credential_status: string; metadata: ModelMetadata } };

export function ConnectedModelSettings({ api }: { api: WorkspaceTransport }) {
  const [reading, setReading] = useState<Reading | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [pending, setPending] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [connections, setConnections] = useState<ModelConnection[]>([]);
  const [connectionError, setConnectionError] = useState("");
  const [adding, setAdding] = useState(false);
  const active = useRef(true);
  const locked = useRef(false);
  const readGeneration = useRef(0);
  const load = useCallback(async () => {
    const generation = ++readGeneration.current;
    const [current, saved] = await Promise.allSettled([
      api<Reading>("v1/model-configuration"),
      api<{ connections: ModelConnection[] }>("v1/model-connections"),
    ]);
    if (!active.current || generation !== readGeneration.current) return;
    if (current.status === "rejected") throw current.reason;
    setReading(current.value);
    if (saved.status === "fulfilled") { setConnections(saved.value.connections); setConnectionError(""); }
    else { setConnections([]); setConnectionError("服务商列表暂不可用，请核对管理员权限及服务器安全存储。"); }
  }, [api]);
  useEffect(() => {
    active.current = true;
    const timer = setTimeout(() => { void load().catch(failure => { if (active.current) setError((failure as Error).message); }); }, 0);
    return () => { clearTimeout(timer); active.current = false; };
  }, [load]);

  async function prepare(request: SaveConfiguration) {
    if (!reading || locked.current || pending) return;
    locked.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const value = await api<Preview>("v1/commands/preview", {
        command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(),
        operation: "model.configuration.save", product_id: null,
        expected_revision: reading.category_revision, source_read_set: [], payload: request,
      });
      if (active.current) setPreview(value);
    } catch (failure) {
      if (active.current) setError((failure as Error).message);
      throw failure;
    } finally { locked.current = false; if (active.current) setBusy(false); }
  }

  async function save(original: Preview) {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError("");
    try {
      await api("v1/commands", original.command);
    } catch (failure) {
      if (active.current) {
        setError((failure as Error).message);
        // Retain the exact confirmed request only while its outcome is unknown.
        const status = (failure as { status?: number }).status;
        setPending(status === undefined || status >= 500 ? original : null);
        if (status !== undefined && status < 500) setPreview(null);
      }
      locked.current = false; if (active.current) setBusy(false);
      return;
    }
    if (active.current) {
      setPending(null); setPreview(null);
      setNotice("模型配置已保存。调用仍须核对当前资格、材料授权与预算。");
    }
    try { await load(); }
    catch (failure) { if (active.current) setError(`保存已完成；当前配置读取失败：${(failure as Error).message}`); }
    finally { locked.current = false; if (active.current) setBusy(false); }
  }

  return <div className="space-y-4">
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="text-sm">{notice}</p>}
    <Button variant="outline" disabled={busy} onClick={() => { setError(""); void load().catch(failure => setError((failure as Error).message)); }}>读取当前模型设置</Button>
    <section className="space-y-3 rounded-lg border border-border bg-card p-4" aria-label="已保存的模型服务商">
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-base font-semibold">模型服务商</h2><Button variant="outline" disabled={!reading?.can_edit || busy || !!pending || !!preview || adding} onClick={() => setAdding(true)}>添加服务商</Button></div>
      {connectionError && <p role="status" className="text-sm text-muted-foreground">{connectionError}</p>}
      {!connectionError && connections.length === 0 && <p className="text-sm text-muted-foreground">尚未添加服务商。</p>}
      <ul className="divide-y divide-border">{connections.map((connection, index) => {
        const current = reading?.configuration;
        const selected = !!current?.enabled && (connection.id ? current.metadata.connection_id === connection.id : !current.metadata.connection_id && current.metadata.protocol === connection.metadata.protocol && current.metadata.base_url.replace(/\/$/, "") === connection.metadata.base_url.replace(/\/$/, "") && current.metadata.model === connection.metadata.model && current.metadata.model_version === connection.metadata.model_version);
        return <li key={connection.id ?? `host-${index}`} className="flex min-w-0 flex-wrap items-center justify-between gap-3 py-3"><div className="min-w-0 flex-1"><p className="text-sm font-medium">{connection.name}{selected && <span className="ml-2 text-xs text-primary">当前使用</span>}</p><p className="break-all text-xs text-muted-foreground">{connection.metadata.model} · {connection.metadata.base_url}</p><p className="mt-1 text-xs text-muted-foreground">{connection.credential_display} · {connection.pricing_configured ? "已填写计费资料" : "计费资料待填写"}</p></div><Button variant="outline" disabled={selected || !reading?.can_edit || busy || !!pending || !!preview || adding} onClick={() => void prepare({ expected_revision: current?.revision ?? 0, metadata: connection.metadata, enabled: true }).catch(() => {})}>{selected ? "使用中" : "切换使用"}</Button></li>;
      })}</ul>
    </section>
    {adding && <ConnectionEditor api={api} onSaved={() => { setAdding(false); setNotice("服务商已保存，请在列表中选择并确认切换。"); void load().catch(() => setError("已保存，列表读取失败，请刷新核对。")); }} onCancel={() => { setAdding(false); void load().catch(() => {}); }}/>}
    {reading && <div hidden={adding || !!preview || !!pending}><ModelConfigurationSettings reading={reading.configuration} canEdit={reading.can_edit}
      readiness={{ state: "unavailable", code: !reading.configuration ? "MODEL_NOT_CONFIGURED" : !reading.configuration.enabled ? "MODEL_DISABLED" : "RUN_CHECK_REQUIRED" }}
      onPreview={prepare} pending={busy || !!pending || !!preview || adding} /></div>}
    {preview && !pending && <section className="rounded-lg border p-4 space-y-3" aria-label="确认模型设置">
      <p>保存为第 {preview.review.next_revision} 版，{preview.review.enabled ? "启用" : "停用"}此配置。</p>
      <p className="break-all text-sm">{preview.review.metadata.model} · {preview.review.metadata.base_url}</p>
      <p className="text-sm text-muted-foreground">凭据绑定：{preview.review.credential_status === "bound" ? "已绑定" : "尚不可用"}。配置变化后需重新核对资格。</p>
      <Button disabled={busy || !proofClockCurrent("T1", preview.expires_at)} onClick={() => void save(preview)}>确认保存并使用</Button>
      <Button variant="outline" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button>
    </section>}
    {pending && <section className="rounded-lg border p-4 space-y-3"><p>原保存请求的结果尚未确认，请核对同一请求。</p><Button disabled={busy} onClick={() => void save(pending)}>核对原保存请求</Button></section>}
  </div>;
}
