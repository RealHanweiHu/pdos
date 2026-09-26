"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import { importRequest, TestImportPreview } from "./test-import-preview";

type Batch = { id: string; filename: string; status: string; created_at: string; run_count: number; skipped_count: number; superseded_by_batch_id: string | null };
const labels: Record<string, string> = { parsed: "待核对", confirmed: "已确认", failed: "解析未完成" };

export function TestImportHistory({ projectId, planId, onConfirmed }: {
  projectId: string; planId: string; onConfirmed?: () => Promise<void>;
}) {
  const [items, setItems] = useState<Batch[] | null>(null);
  const [before, setBefore] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ id: string; visit: number } | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function load(append = false) {
    setBusy(true); setError("");
    try {
      const value = await importRequest(`/api/projects/${projectId}/npi/test-plans/${planId}/imports${append && before ? `?before_id=${encodeURIComponent(before)}` : ""}`);
      if (!isRecord(value) || !Array.isArray(value.items) || !value.items.every(item => isRecord(item)
        && typeof item.id === "string" && typeof item.filename === "string" && typeof item.status === "string"
        && typeof item.created_at === "string" && typeof item.run_count === "number" && typeof item.skipped_count === "number"
        && (item.superseded_by_batch_id === null || typeof item.superseded_by_batch_id === "string"))) throw new Error("导入历史不完整，请重新读取。");
      const next = value.items as Batch[];
      setItems(old => append ? [...(old ?? []), ...next] : next);
      setBefore(typeof value.next_before_id === "string" ? value.next_before_id : null);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "导入历史暂不可用"); }
    finally { setBusy(false); }
  }
  return <details className="mt-3 rounded-md border p-3" onToggle={event => {
    if (event.currentTarget.open && items === null && !busy) void load();
  }}>
    <summary className="cursor-pointer text-sm font-medium">历史导入与继续核对</summary>
    <div className="mt-3 space-y-3 text-sm">
      <p className="text-xs text-muted-foreground">按上传时间显示本计划全部批次，包含没有生成测试记录和已被后续解析替代的批次。</p>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新导入历史</Button>
      {items?.length === 0 && <p>本计划尚无已保存的报告导入。</p>}
      {items?.map(item => <div key={item.id} className="space-y-1 rounded-md border p-2">
        <p className="break-words font-medium">{item.filename}</p>
        <p className="text-xs">{labels[item.status] ?? item.status}{item.superseded_by_batch_id ? " · 有后续解析版本" : ""} · {new Date(item.created_at).toLocaleString()}</p>
        <p className="text-xs">测试记录 {item.run_count} 条 · 跳过说明 {item.skipped_count} 处</p>
        <Button size="sm" variant="outline" onClick={() => setSelected(previous => ({ id: item.id, visit: (previous?.visit ?? 0) + 1 }))}>打开此批报告</Button>
      </div>)}
      {before && <Button size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>更早的导入</Button>}
      {selected && <TestImportPreview key={`${selected.id}:${selected.visit}`} projectId={projectId} batchId={selected.id} onConfirmed={async () => { await load(); await onConfirmed?.(); }} />}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
