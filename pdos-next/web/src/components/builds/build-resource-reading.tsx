"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowClockwise } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { Build } from "@/lib/build-preparation-view";
import { resourceInspectBody, resourceOperations, resourceReading, type ResourceInspectBody, type ResourceReading } from "@/lib/build-resource-reading";
import { safeStartError, type BuildStartApi, type ScopeDraft } from "@/lib/build-start-view";
import { originalLocation } from "@/lib/original-location";
import type { DefinitionReference, DefinitionSource } from "@/lib/product-view";
import { utcText } from "@/lib/project-plan-view";

type Props = { productId: string; build: Build; scope: ScopeDraft; sources: DefinitionSource[]; api: BuildStartApi };
const kinds = { equipment: "设备", fixture: "夹具", person: "人员", line: "产线", tooling: "工装" };
function Originals({ refs, sources }: { refs: DefinitionReference[]; sources: DefinitionSource[] }) {
  return refs.map((ref, index) => {
    const source = sources.find(row => row.id === ref.artifact_id);
    return <blockquote key={index} className="border-l-2 border-primary pl-3 text-sm [overflow-wrap:anywhere]"><p className="font-medium">{source?.title ?? "固定原文，名称待核对"} · v{ref.expected_revision} · 第{ref.line}行{originalLocation(source, ref.line) && ` · ${originalLocation(source, ref.line)}`}</p><p className="mt-1 whitespace-pre-wrap">{ref.quote}</p></blockquote>;
  });
}

export function BuildResourceReading({ productId, build, scope, sources, api }: Props) {
  const [operation, setOperation] = useState(""), [reading, setReading] = useState<ResourceReading | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const alive = useRef(true), locked = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function read() {
    if (locked.current) return;
    let body: ResourceInspectBody;
    try { body = resourceInspectBody(build, scope, operation); }
    catch (failure) { setReading(null); setError(failure instanceof Error ? failure.message : "请核对本轮用途、工序和完整窗口。"); return; }
    locked.current = true; setBusy(true); setReading(null); setError("");
    try {
      const result = await api<unknown>(`v1/products/${productId}/builds/${build.id}/resources/inspect`, body);
      if (alive.current) setReading(resourceReading(result, productId, build, body));
    } catch (failure) { if (alive.current) setError(safeStartError(failure, true).message); }
    finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  return <section className="min-w-0 space-y-4 rounded-lg border border-border p-3 sm:p-4" aria-label="固定工序资源依据">
    <div><h3 className="font-semibold">本工序资源依据</h3><p className="subtle mt-2">采用上方用途、数量、场地和完整窗口，读取固定轮次的资源声明与原件。验收、校准和资格分别保留待核对。</p></div>
    <label>固定制造工序<select value={operation} disabled={busy} onChange={event => { setOperation(event.target.value); setReading(null); setError(""); }}><option value="">选择本轮工序</option>{resourceOperations(build).map(row => <option key={row.key} value={row.key}>{row.name}</option>)}</select></label>
    <Button variant="outline" disabled={busy || !operation} onClick={() => void read()}><ArrowClockwise/>{busy ? "正在读取完整资源依据…" : "读取本工序资源依据"}</Button>
    {error && <p role="alert" className="text-sm text-destructive [overflow-wrap:anywhere]">{error}</p>}
    {reading && <div className="min-w-0 space-y-4" role="status">
      <p className="text-sm">{reading.state === "known" ? `本次已读固定关系 ${reading.relations.length} 条` : reading.state === "historical" ? "历史资源声明，当前适用性待核对" : "本轮资源依据未知，未取得可用的固定声明"} · 读回有效至 {reading.valid_until ? utcText(reading.valid_until) : "待核对"}</p>
      {reading.nature === "synthetic" && <p className="rounded-lg border border-primary p-3 text-sm">合成验证事实，真实制造资源仍待核对。</p>}
      {reading.resources.map(row => <article key={row.resource.id} className="min-w-0 space-y-3 border-t border-border pt-3">
        <h4 className="font-medium [overflow-wrap:anywhere]">{kinds[row.resource.kind]} · {row.resource.id} · 固定v{row.resource.revision}</h4>
        <p className="text-sm">验收：未知 · 校准：未知 · 资格：未知</p>
        {reading.relations.filter(relation => relation.resource.id === row.resource.id).map((relation, index) => <div key={index} className="space-y-3"><p className="text-sm">本工序声明使用量：{relation.units}</p><Originals refs={relation.relation_originals} sources={sources}/><details><summary className="cursor-pointer text-sm">关系原件定位</summary><p className="mt-2 text-sm [overflow-wrap:anywhere]">固定事实v{relation.relation_source.revision} · {relation.relation_source.id}<br/>{relation.relation_source.position}</p></details></div>)}
        <details><summary className="cursor-pointer text-sm">资源原文依据</summary><div className="mt-3 space-y-3"><Originals refs={row.originals} sources={sources}/></div></details>
      </article>)}
      <p className="subtle">资源使用声明尚不构成验收、校准、专业资格或开工许可；资源与作业文件、控制计划、试产及放行的完整关系待补。</p>
      <details><summary className="cursor-pointer text-sm">全部固定来源 · {reading.required_source_read_set.length}份</summary><ul className="mt-3 space-y-2 text-sm">{reading.required_source_read_set.map(ref => <li key={ref.artifact_id} className="[overflow-wrap:anywhere]">{sources.find(source => source.id === ref.artifact_id)?.title ?? ref.artifact_id} · v{ref.expected_revision}</li>)}</ul></details>
    </div>}
  </section>;
}
