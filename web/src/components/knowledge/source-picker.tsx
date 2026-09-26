"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

export type SourceSelection = { kind: "document" | "specification" | "evidence_snapshot"; id: string; expected_version: string };
type SourceOption = SourceSelection & { title: string; version_label: string; available: boolean; reason: string | null };
const labels = { document: "文档", specification: "规格", evidence_snapshot: "证据快照" };
function parse(value: unknown): SourceOption[] {
  if (!isRecord(value) || !Array.isArray(value.items)) throw new Error("来源列表不完整");
  return value.items.map(item => {
    if (!isRecord(item) || !["document", "specification", "evidence_snapshot"].includes(String(item.kind)) ||
        typeof item.id !== "string" || !/^[0-9a-f-]{36}$/.test(item.id) || typeof item.expected_version !== "string" ||
        typeof item.title !== "string" || typeof item.version_label !== "string" || typeof item.available !== "boolean" ||
        !(item.reason === null || typeof item.reason === "string")) throw new Error("来源版本不完整");
    return item as SourceOption;
  });
}
export function SourcePicker({ projectId, value, onChange }: { projectId: string; value: SourceSelection[]; onChange: (next: SourceSelection[]) => void }) {
  const [options, setOptions] = useState<SourceOption[] | null>(null);
  const [known, setKnown] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = (item: SourceSelection) => `${item.kind}:${item.id}`;
  async function load() {
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/memory-source-options?q=${encodeURIComponent(query)}`, { cache: "no-store" });
      const body: unknown = await responseBody(response).catch(() => null);
      if (!response.ok) throw new Error(isRecord(body) && isRecord(body.detail) && typeof body.detail.message === "string" ? body.detail.message : "当前不能读取来源");
      const loaded = parse(body); setOptions(loaded);
      setKnown(previous => ({ ...previous, ...Object.fromEntries(loaded.map(item => [key(item), item.title])) }));
    } catch (error) { setError(error instanceof Error ? error.message : "来源暂不可用"); }
    finally { setBusy(false); }
  }
  return <fieldset className="space-y-2 rounded-lg border p-3"><legend className="px-1 text-xs font-medium">适用依据与版本（最多20项）</legend>
    <div className="flex flex-wrap gap-2"><input aria-label="查找知识依据" maxLength={200} className="min-w-0 flex-1 rounded-md border bg-background px-2 py-1 text-sm" placeholder="按名称、规格编号或快照摘要查找" value={query} onChange={event => setQuery(event.target.value)} /><Button type="button" size="sm" variant="outline" disabled={busy} onClick={load}>{busy ? "查找中…" : "查找依据"}</Button></div>
    <p className="text-xs text-muted-foreground">每类展示最近200条匹配结果；未找到时可缩小搜索。提交时再次核对所选版本。</p>
    {value.length > 0 && <ul className="space-y-1">{value.map(item => <li key={key(item)} className="flex items-center justify-between gap-2 text-xs"><span className="break-all">已选 {labels[item.kind]} · {known[key(item)] ?? item.id} · {item.expected_version.slice(0, 12)}</span><Button type="button" size="sm" variant="ghost" onClick={() => onChange(value.filter(selected => key(selected) !== key(item)))}>移除</Button></li>)}</ul>}
    {options && <div className="max-h-64 space-y-2 overflow-y-auto">{options.length === 0 && <p className="text-xs text-muted-foreground">当前没有匹配的来源。</p>}{options.map(item => {
      const selected = value.find(s => key(s) === key(item));
      const changed = selected && selected.expected_version !== item.expected_version;
      return <label key={key(item)} className="flex items-start gap-2 rounded-md border p-2 text-xs"><input type="checkbox" className="mt-0.5" disabled={!item.available || (!selected && value.length >= 20)} checked={Boolean(selected)} onChange={event => onChange(event.target.checked ? [...value, { kind: item.kind, id: item.id, expected_version: item.expected_version }] : value.filter(s => key(s) !== key(item)))} /><span className="min-w-0 break-words"><strong>{labels[item.kind]} · {item.title}</strong><span className="mt-1 block text-muted-foreground">{item.version_label}{!item.available ? ` · ${item.reason}` : ""}</span>{changed && <span className="block text-destructive">所选旧版本已变化，请移除后重新选择。</span>}</span></label>;
    })}</div>}
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
  </fieldset>;
}
