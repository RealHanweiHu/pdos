"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ProductAiRuns } from "./product-ai-runs";
import { ProductRequestError, request, type ProductCatalog } from "./product-work-api";

type Source = { kind: string; id: string; label: string; as_of: string };
type Options = { items: Source[]; next_offset: number | null; generation_message: string };
type Preparation = {
  digest: string;
  warnings: string[];
  coverage_limits: string[];
  references: { reference_id: string; label: string; href: string; fields: Record<string, unknown> }[];
};
const kinds = [
  ["research", "研究任务"], ["evidence", "来源原文"], ["competitor", "竞品记录"],
  ["segment", "市场细分"], ["opportunity", "机会与方案"], ["experiment", "实验"],
  ["strategy", "策略"], ["definition", "产品定义"], ["product", "产品对象"], ["work", "专业评审工作"],
];
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

type Props = {
  base: string; capability: string; initialRunId?: string; catalog: ProductCatalog; initialLine?: string;
  onLineChange?: (line: string) => void; disabled?: boolean;
};
export function ProductAiPreparation(props: Props) {
  return <PreparationPanel key={JSON.stringify([props.base, props.capability, props.initialLine ?? ""])} {...props}/>;
}
function PreparationPanel({ base, capability, catalog, initialLine = "", initialRunId, onLineChange, disabled = false }: Props) {
  const [line, setLine] = useState(initialLine), [kind, setKind] = useState("research"), [query, setQuery] = useState(""), [question, setQuestion] = useState("");
  const [options, setOptions] = useState<Options | null>(null), [selected, setSelected] = useState<Source[]>([]), [prepared, setPrepared] = useState<Preparation | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [denied, setDenied] = useState(false), [authority, setAuthority] = useState(0);
  const [recheckedCatalog, setRecheckedCatalog] = useState<{ value: ProductCatalog; parent: ProductCatalog } | null>(null);
  const [linkedRun, setLinkedRun] = useState<{ id: string; matched: boolean } | null>(null);
  const live = useRef(true), revision = useRef(0), reading = useRef(false);
  useEffect(() => { live.current = true; return () => { live.current = false; revision.current += 1; }; }, []);
  const captureAccess = useCallback(() => { const current = revision.current; return () => live.current && revision.current === current; }, []);
  const clearAuthority = useCallback((message: string) => {
    if (!live.current) return;
    revision.current += 1; reading.current = false;
    setLine(""); setKind("research"); setQuery(""); setQuestion(""); setOptions(null); setSelected([]); setPrepared(null); setRecheckedCatalog(null);
    setBusy(false); setDenied(true); setAuthority(value => value + 1); setError(message);
  }, []);
  useEffect(() => {
    if (!initialRunId) return;
    let active = true;
    const current = captureAccess();
    void request<{ items: { run_id: string; selection: { capability: string; product_line_id: string | null } }[] }>(`${base}/product-ai-run-read`, "POST", { run_id: initialRunId }).then(value => { if (!active || !current()) return; const item = value.items.find(item => item.run_id === initialRunId); setLinkedRun({ id: initialRunId, matched: !!item && item.selection.capability === capability && (item.selection.product_line_id ?? "") === line }); }).catch(failure => { if (!active || !current()) return; if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) clearAuthority(failure.message); else setError(failure instanceof Error ? failure.message : "原运行暂不可读"); });
    return () => { active = false; };
  }, [base, initialRunId, capability, line, captureAccess, clearAuthority]);
  function fail(failure: unknown, fallback: string) {
    if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) clearAuthority(failure.message);
    else setError(failure instanceof Error ? failure.message : fallback);
  }
  const needsLine = ["opportunity_mapping", "experiment_design", "product_strategy", "product_definition"].includes(capability);
  const currentCatalog = recheckedCatalog?.parent === catalog ? recheckedCatalog.value : catalog;
  async function readSources(offset = 0) {
    if (!live.current || reading.current) return;
    reading.current = true; setBusy(true); setError(""); setPrepared(null); const current = captureAccess();
    try {
      const [result, products] = await Promise.all([
        request<Options>(`${base}/product-ai-options`, "POST", { kind, product_line_id: line || null, query, offset }),
        denied ? request<ProductCatalog>(`${base}/products`) : Promise.resolve(null),
      ]);
      if (!current()) return;
      setOptions(previous => offset && previous ? { ...result, items: [...previous.items, ...result.items] } : result);
      if (products) setRecheckedCatalog({ value: products, parent: catalog });
      setDenied(false);
    } catch (failure) { if (current()) fail(failure, "来源暂不可读，已保留上次输入。"); }
    finally { if (current()) { reading.current = false; setBusy(false); } }
  }
  async function prepare() {
    if (!live.current || reading.current || denied) return;
    reading.current = true; setBusy(true); setError(""); setPrepared(null); const current = captureAccess();
    try {
      const result = await request<Preparation>(`${base}/product-ai-context`, "POST", { capability, product_line_id: line || null, question: question.trim(), sources: selected.map(({ kind, id }) => ({ kind, id })) });
      if (current()) setPrepared(result);
    } catch (failure) { if (current()) fail(failure, "当前资料无法核对，请刷新来源。"); }
    finally { if (current()) { reading.current = false; setBusy(false); } }
  }
  return <details open={linkedRun?.id === initialRunId && linkedRun?.matched ? true : undefined} className="rounded-lg border p-4">
    <summary className="cursor-pointer font-medium">小Pai · 核对本次产品工作资料</summary>
    <p className="mt-2 text-sm text-muted-foreground">选择本次问题与依据，核对原始内容和缺项。核对后可在下方查询分析记录，能力开放后再发起分析。</p>
    {error && <p role="alert" className="mt-2 text-sm text-destructive">{error}</p>}
    <fieldset disabled={busy || disabled} className="mt-3 space-y-3">
      <label className="block text-sm">本次产品线<select disabled={denied} className={field} value={line} onChange={event => {
        revision.current += 1; onLineChange?.(event.target.value); setLine(event.target.value); setQuestion(""); setQuery(""); setSelected([]); setOptions(null); setPrepared(null); setError("");
      }}><option value="">市场空间共同研究</option>{!denied && currentCatalog.nodes.filter(node => node.level === "line").map(node => <option key={node.id} value={node.id}>{node.name}</option>)}</select></label>
      {needsLine && !line && <p className="text-sm text-muted-foreground">机会、实验、策略及产品定义需要明确产品线；先在矩阵 / 路线图区登记产品线。</p>}
      <label className="block text-sm">本次需要解决的问题<textarea disabled={denied} className={field} maxLength={5000} value={question} onChange={event => { setQuestion(event.target.value); setPrepared(null); }}/></label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">资料类型<select disabled={denied} className={field} value={kind} onChange={event => { setKind(event.target.value); setOptions(null); setPrepared(null); }}>{kinds.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className="text-sm">查找资料<input disabled={denied} className={field} value={query} maxLength={200} onChange={event => { setQuery(event.target.value); setOptions(null); setPrepared(null); }}/></label>
      </div>
      <Button variant="outline" size="sm" onClick={() => void readSources()}>读取可用来源</Button>
      {options?.items.length === 0 && <p className="text-sm text-muted-foreground">此范围没有匹配资料，可调整查询或先登记来源。</p>}
      {options && <div className="max-h-64 space-y-2 overflow-auto">{options.items.map(source => {
        const checked = selected.some(item => item.kind === source.kind && item.id === source.id);
        return <label key={`${source.kind}:${source.id}`} className="flex min-h-11 items-center gap-2 rounded-md border p-2 text-sm">
          <input type="checkbox" checked={checked} disabled={!checked && selected.length >= 20} onChange={event => {
            setSelected(previous => event.target.checked ? [...previous, source] : previous.filter(item => item.id !== source.id || item.kind !== source.kind)); setPrepared(null);
          }}/><span>{source.label} · {new Date(source.as_of).toLocaleString()}</span>
        </label>;
      })}</div>}
      {options?.next_offset != null && <Button variant="outline" size="sm" onClick={() => void readSources(options.next_offset!)}>更多来源</Button>}
      {selected.length > 0 && <div className="space-y-1 text-sm"><p>已选 {selected.length} / 20 项</p>{selected.map(source => <div key={`${source.kind}:${source.id}`} className="flex items-center justify-between gap-2"><span>{source.label}</span><Button variant="ghost" size="sm" aria-label={`移除${source.label}`} onClick={() => { setSelected(previous => previous.filter(item => item.id !== source.id || item.kind !== source.kind)); setPrepared(null); }}>移除</Button></div>)}</div>}
      <Button size="sm" disabled={denied || !question.trim() || (needsLine && !line)} onClick={() => void prepare()}>核对资料与缺项</Button>
    </fieldset>
    {busy && <p role="status" className="mt-2 text-sm">正在核对当前权限和来源…</p>}
    {prepared && <div className="mt-3 space-y-2 text-sm">
      <p>已核对 {prepared.references.length} 组资料。后续生成与办理需再次验证来源版本。</p>
      {prepared.warnings.map(note => <p className="text-primary" key={note}>{note}</p>)}
      {prepared.coverage_limits.map(note => <p className="text-muted-foreground" key={note}>{note}</p>)}
      {prepared.references.map(source => <details key={source.reference_id} className="rounded-md border p-3"><summary className="cursor-pointer">{source.label}</summary>
        <a className="my-2 inline-flex min-h-11 items-center text-primary underline" href={source.href}>打开所属业务工作区</a>
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(source.fields, null, 2)}</pre>
      </details>)}
    </div>}
    <ProductAiRuns initialRunId={linkedRun?.id === initialRunId && linkedRun?.matched ? initialRunId : undefined} key={`${base}:${capability}:${line}:${authority}`} base={base} capability={capability} line={line} disabled={disabled} onAuthorityDenied={clearAuthority} captureAccess={captureAccess} prepared={prepared ? { digest: prepared.digest, selection: { capability, product_line_id: line || null, question: question.trim(), sources: selected.map(({ kind, id }) => ({ kind, id })) } } : null}/>
  </details>;
}
