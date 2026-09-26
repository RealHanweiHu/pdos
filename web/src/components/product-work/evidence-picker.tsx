"use client";

import type { Evidence } from "./product-work-api";

export function EvidencePicker({ options, selected, onChange }: { options: Evidence[]; selected: string[]; onChange: (value: string[]) => void }) {
  return <details className="rounded-md border p-2"><summary className="cursor-pointer text-sm">关联证据快照（已选 {selected.length}）</summary>
    {options.length === 0 && <p className="mt-2 text-sm text-muted-foreground">尚无可用共享证据。请先在「研究」区登记来源、采集页面，再返回此处刷新。</p>}
    <div className="mt-2 max-h-72 space-y-2 overflow-y-auto">{options.map((source) => <label key={source.id} className="flex items-start gap-2 text-sm"><input type="checkbox" checked={selected.includes(source.id)} onChange={(event) => onChange(event.target.checked ? [...selected, source.id] : selected.filter((id) => id !== source.id))} /><span>{source.name} · {source.source_version ? `版本 ${source.source_version} · ` : "未标版本 · "}{new Date(source.captured_at).toLocaleString()}<span className="block break-all text-xs text-muted-foreground">{source.url ?? "来源快照"} · 摘要 {source.reference.digest.slice(0, 12)} · {source.taint}{source.is_stale ? " · 已陈旧" : ""}{source.superseded ? " · 已有新版" : ""}{source.has_conflict ? " · 有冲突" : ""}</span></span></label>)}</div>
  </details>;
}

