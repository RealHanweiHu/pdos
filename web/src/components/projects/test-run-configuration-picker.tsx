"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import { SampleConfigurationSnapshot } from "./sample-configuration-snapshot";

type Revision = Record<string, unknown> & { id: string; source_document_id: string | null };
export function TestRunConfigurationPicker({ projectId, sampleId, value, busy, onSelect }: {
  projectId: string; sampleId: string; value: string; busy: boolean;
  onSelect: (revision: Revision | null) => void;
}) {
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [loaded, setLoaded] = useState(false), [loading, setLoading] = useState(false);
  const [next, setNext] = useState<number | null>(null), [error, setError] = useState<string | null>(null);
  async function load(before?: number) {
    setLoading(true); setError(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/npi/samples/${sampleId}/configuration-history${before ? `?before_number=${before}` : ""}`, { cache: "no-store" });
      const data: unknown = await response.json();
      if (!response.ok || !isRecord(data) || !Array.isArray(data.revisions)) throw new Error("配置历史暂不可用，请重新读取");
      const rows = data.revisions.map((item): Revision => {
        if (!isRecord(item) || typeof item.id !== "string") throw new Error("配置版本资料不完整");
        return { ...item, id: item.id, source_document_id: typeof item.source_document_id === "string" ? item.source_document_id : null };
      });
      setRevisions(previous => before ? [...previous, ...rows.filter(r => !previous.some(p => p.id === r.id))] : rows);
      setNext(typeof data.next_before === "number" ? data.next_before : null); setLoaded(true);
    } catch (e) { setError(e instanceof Error ? e.message : "配置历史暂不可用"); }
    finally { setLoading(false); }
  }
  const selected = revisions.find(r => r.id === value);
  return <div className="space-y-2 rounded-md border p-3 text-xs">
    <p>核对测试当时使用的已保存版本。无法还原时选择“配置未知”，并记录原因。</p>
    <Button type="button" size="sm" variant="outline" disabled={busy || loading || !sampleId} onClick={() => void load()}>读取样机配置历史</Button>
    {loaded && <label className="block">当次配置版本<select className="mt-1 w-full rounded-md border bg-background p-2" value={value} disabled={busy || loading} onChange={e => onSelect(revisions.find(r => r.id === e.target.value) ?? null)}><option value="">请选择并核对下方快照</option>{revisions.map(r => <option key={r.id} value={r.id}>版本 {String(r.revision_number)} · {String(r.created_by_name ?? "登记人未知")} · {String(r.created_at ?? "登记时间未知")}</option>)}</select></label>}
    {loaded && !revisions.length && <p>尚无已保存的配置版本，请选择未知或由工程人员补齐真实配置记录。</p>}
    {next !== null && <Button type="button" size="sm" variant="outline" disabled={busy || loading} onClick={() => void load(next)}>读取更早版本</Button>}
    {selected && <><SampleConfigurationSnapshot revision={selected} />{selected.source_document_id && <p>此版本来自报告，选择后会绑定同一报告作为测试证据；保存前请核对证据文档。</p>}</>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
  </div>;
}
