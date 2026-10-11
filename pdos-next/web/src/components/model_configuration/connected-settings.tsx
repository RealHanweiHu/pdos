"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { proofClockCurrent } from "@/lib/proof-clock";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import type { ConfigurationReading, SaveConfiguration } from "./contracts";
import { ModelConfigurationSettings } from "./settings";

type Reading = { configuration: ConfigurationReading | null; category_revision: number; can_edit: boolean };
type Preview = { command: Record<string, unknown>; expires_at: string; review: { next_revision: number; enabled: boolean; credential_status: string } };

export function ConnectedModelSettings({ api }: { api: WorkspaceTransport }) {
  const [reading, setReading] = useState<Reading | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [pending, setPending] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const active = useRef(true);
  const locked = useRef(false);
  const load = useCallback(async () => {
    const value = await api<Reading>("v1/model-configuration");
    if (active.current) setReading(value);
  }, [api]);
  useEffect(() => {
    active.current = true;
    void load().catch(failure => { if (active.current) setError((failure as Error).message); });
    return () => { active.current = false; };
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
    {reading && <ModelConfigurationSettings reading={reading.configuration} canEdit={reading.can_edit}
      readiness={{ state: "unavailable", code: !reading.configuration ? "MODEL_NOT_CONFIGURED" : !reading.configuration.enabled ? "MODEL_DISABLED" : "RUN_CHECK_REQUIRED" }}
      onPreview={prepare} pending={busy || !!pending || !!preview} />}
    {preview && !pending && <section className="rounded-lg border p-4 space-y-3" aria-label="确认模型设置">
      <p>保存为第 {preview.review.next_revision} 版，{preview.review.enabled ? "启用" : "停用"}此配置。</p>
      <p className="text-sm text-muted-foreground">凭据绑定：{preview.review.credential_status === "bound" ? "已绑定" : "尚不可用"}。配置变化后需重新核对资格。</p>
      <Button disabled={busy || !proofClockCurrent("T1", preview.expires_at)} onClick={() => void save(preview)}>确认保存此配置</Button>
      <Button variant="outline" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button>
    </section>}
    {pending && <section className="rounded-lg border p-4 space-y-3"><p>原保存请求的结果尚未确认，请核对同一请求。</p><Button disabled={busy} onClick={() => void save(pending)}>核对原保存请求</Button></section>}
  </div>;
}
