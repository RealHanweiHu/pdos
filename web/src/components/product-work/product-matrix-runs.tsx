"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { AgentRunProgressPanel } from "@/components/ai/agent-run-progress";
import type { AgentRunProgress } from "@/components/ai/ai-types";
import { obj, rows, text, field, type Row } from "@/components/quality/fmea-sources";
import { request, ProductRequestError } from "./product-work-api";

type Props = { base: string; recordId: string; initialRunId?: string; prepared: { digest: string; selection: { record_id: string; roadmap_ids: string[] } } | null; onAuthorityDenied?: (message: string) => void };
type PendingRequest = { body: Row; requestId: string };
const authorityDenied = (failure: unknown) => failure instanceof ProductRequestError && [401, 403].includes(failure.status);

const states: Record<string, string> = { running: "分析中", succeeded: "已保存分析", degraded: "未完成", failed: "已停止" };
function Statement({ value, sources }: { value: Row; sources: Row[] }) {
  return <div className="space-y-1"><p className="whitespace-pre-wrap">{text(value.text)} <span className="text-muted-foreground">（{value.nature === "observed" ? "原资料观察" : value.nature === "derived" ? "基于资料的解释" : "待验证假设"}）</span></p>{rows(value.citations).map((citation, index) => {
    const source = sources.find(ref => ref.reference_id === citation.reference_id);
    return <details key={index}><summary className="cursor-pointer text-muted-foreground">核对原字段 · {text(source?.label ?? citation.reference_id)}</summary><p className="whitespace-pre-wrap break-words">{text(citation.quoted_value)}</p><p className="break-words text-muted-foreground">{Array.isArray(citation.field_path) ? citation.field_path.join(" → ") : ""}</p>{source?.href != null && <a className="inline-flex min-h-11 items-center text-primary underline" href={text(source.href)}>打开原业务记录</a>}</details>;
  })}</div>;
}
function Missing({ value }: { value: unknown }) { return Array.isArray(value) && value.length > 0 ? <p className="text-primary">待补：{value.join("；")}</p> : null; }

export function ProductMatrixRuns(props: Props) {
  return <MatrixRunsPanel key={JSON.stringify([props.base, props.recordId])} {...props}/>;
}

function MatrixRunsPanel({ base, recordId, initialRunId, prepared, onAuthorityDenied }: Props) {
  const [data, setData] = useState<Row | null>(null), [selected, setSelected] = useState<Row | null>(null);
  const [instruction, setInstruction] = useState(""), [busy, setBusy] = useState(false), [generating, setGenerating] = useState(false), [error, setError] = useState("");
  const [pending, setPending] = useState<PendingRequest | null>(null), [notice, setNotice] = useState("");
  const attempt = useRef<PendingRequest | null>(null), live = useRef(true), reading = useRef(false), sending = useRef(false), revision = useRef(0);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  const clearAuthority = useCallback((message: string) => {
    if (!live.current) return;
    revision.current += 1;
    attempt.current = null; setPending(null); setData(null); setSelected(null); setInstruction(""); setNotice(""); setError(message);
    onAuthorityDenied?.(message);
  }, [onAuthorityDenied]);
  useEffect(() => {
    if (!initialRunId || attempt.current) return;
    let active = true;
    const current = revision.current;
    void request<Row>(`${base}/matrix-ai-history`, "POST", { record_id: recordId, run_id: initialRunId }).then(value => { if (!active || !live.current || current !== revision.current || attempt.current) return; const item = rows(value.items).find(item => item.run_id === initialRunId); if (!item || obj(item.selection).record_id !== recordId) throw new Error("原矩阵运行与当前保存对照不匹配。"); setData(value); setSelected(item); }).catch(failure => { if (!active || !live.current || current !== revision.current) return; if (authorityDenied(failure)) clearAuthority((failure as Error).message); else setError(failure instanceof Error ? failure.message : "原矩阵运行暂不可读"); });
    return () => { active = false; };
  }, [base, recordId, initialRunId, clearAuthority]);
  const progress = useCallback(async (id: string) => {
    const current = revision.current;
    try { return await request<AgentRunProgress>(`${base}/matrix-ai-progress`, "POST", { run_id: id }); }
    catch (failure) { if (revision.current === current && authorityDenied(failure)) clearAuthority((failure as Error).message); throw failure; }
  }, [base, clearAuthority]);
  function clearPending() { attempt.current = null; setPending(null); }
  async function read(before?: string) {
    const current = revision.current;
    const value = await request<Row>(`${base}/matrix-ai-history`, "POST", { record_id: recordId, before_id: before ?? null });
    if (!live.current || revision.current !== current) return;
    setData(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value);
    const recovered = rows(value.items).find(item => item.request_id === attempt.current?.requestId);
    if (recovered) {
      setSelected(recovered); setNotice(`已核对原运行，回执：${text(recovered.run_id)} · ${states[text(recovered.status)] ?? text(recovered.status)}`);
      if (recovered.status !== "running") clearPending();
    }
    return value;
  }
  async function open(id: string) {
    const current = revision.current;
    setSelected(null);
    const value = await request<Row>(`${base}/matrix-ai-history`, "POST", { record_id: recordId, run_id: id });
    if (!live.current || revision.current !== current) return;
    setSelected(rows(value.items)[0] ?? null);
  }
  async function act(work: () => Promise<unknown>) {
    if (reading.current) return;
    reading.current = true; setBusy(true); setError("");
    const current = revision.current;
    try { await work(); } catch (failure) {
      if (!live.current || revision.current !== current) return;
      if (authorityDenied(failure)) clearAuthority((failure as Error).message);
      else setError(failure instanceof Error ? failure.message : "矩阵运行暂不可读");
    } finally { reading.current = false; if (live.current) setBusy(false); }
  }
  async function refresh() {
    const current = revision.current, original = attempt.current?.requestId;
    const value = await read();
    if (!live.current || revision.current !== current || !value) return;
    const recovered = rows(value.items).find(item => item.request_id === original);
    const id = text(recovered?.run_id ?? selected?.run_id);
    if (id) await open(id);
  }
  async function stop(value: Row) {
    const current = revision.current;
    await request(`${base}/matrix-ai-cancel`, "POST", { run_id: value.run_id });
    if (!live.current || revision.current !== current) return;
    await read();
    if (live.current && revision.current === current && selected?.run_id === value.run_id) await open(text(value.run_id));
  }
  async function generate(body?: Row, requestId?: string) {
    if (sending.current || reading.current) return;
    if (body) {
      if (attempt.current) return;
      // Keep the full original input while a response or terminal receipt is unconfirmed.
      attempt.current = { body: JSON.parse(JSON.stringify(body)) as Row, requestId: requestId ?? crypto.randomUUID() };
      setPending(attempt.current);
    }
    const original = attempt.current;
    if (!original) return;
    sending.current = true;
    const current = revision.current;
    setGenerating(true); setError(""); setNotice("");
    try {
      let value: Row;
      try { value = await request<Row>(`${base}/matrix-ai-runs`, "POST", { ...original.body, request_id: original.requestId }); }
      catch (failure) {
        if (!live.current || revision.current !== current) return;
        if (authorityDenied(failure)) throw failure;
        if (failure instanceof ProductRequestError && failure.status < 500 && ![408, 429].includes(failure.status)) { clearPending(); throw failure; }
        setError("矩阵请求结果尚未确认。请刷新本人原运行，或重试原矩阵请求核对回执；原资料、要求与编号保持。");
        return;
      }
      if (!live.current || revision.current !== current) return;
      setSelected(value);
      setNotice(`已收到原运行回执：${text(value.run_id)} · ${states[text(value.status)] ?? text(value.status)}`);
      if (value.status !== "running") clearPending();
      try {
        await read();
        if (live.current && revision.current === current) await open(text(value.run_id));
      } catch (failure) {
        if (!live.current || revision.current !== current) return;
        if (authorityDenied(failure)) throw failure;
        setSelected(value);
        setError(value.status === "succeeded" ? "矩阵分析已保存，历史暂未刷新。请刷新本人原运行与回执，无需再次生成。" : "已收到原运行回执，历史暂未刷新。请刷新核对本次状态，接续仍使用原请求。");
      }
    } catch (failure) {
      if (!live.current || revision.current !== current) return;
      if (authorityDenied(failure)) clearAuthority((failure as Error).message);
      else setError(failure instanceof Error ? failure.message : "矩阵请求暂不可用");
    } finally { sending.current = false; if (live.current) setGenerating(false); }
  }
  const assessment = obj(selected?.assessment), sources = rows(selected?.frozen_sources);
  const productName = (id: unknown) => {
    const source = sources.find(ref => text(ref.reference_id).endsWith(`:product:${text(id)}`));
    return text(source?.label) || text(id);
  };
  const criterionName = (key: unknown) => {
    const source = sources.find(ref => obj(obj(ref.fields).criterion).key === key);
    return text(obj(obj(source?.fields).criterion).interpretation) || text(key);
  };
  return <details open={!!initialRunId || undefined} className="space-y-3 rounded-md border p-3" onToggle={event => { if (event.currentTarget.open && !initialRunId && !data && !busy) void act(() => read()); }}>
    <summary className="cursor-pointer text-sm font-medium">矩阵分析与本人运行历史</summary>
    <div className="space-y-3 text-sm"><p>依据原对照和明确选入的路线图解释产品定位、声明缺口与重叠。复用方向保留为待验证假设，产品定义、路线图和立项仍由人工办理。</p>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {notice && <p role="status" className="break-words">{notice}</p>}
      {pending && <div className="space-y-2 rounded-md border p-3"><p>原请求尚待核对；先读取本人原运行或按同一编号重试，再开始新的分析。</p><p className="break-all text-xs text-muted-foreground">原请求编号：{pending.requestId}</p><Button size="sm" variant="outline" disabled={busy || generating || data?.can_request !== true || data.rollout !== "live"} onClick={() => void generate()}>重试原矩阵请求</Button></div>}
      {data && data.rollout !== "live" && <p className="text-primary">此能力待阶段评测，当前可核对资料和读取原运行，尚未开放生成。</p>}
      <Button variant="outline" size="sm" disabled={busy} onClick={() => void act(refresh)}>刷新本人原运行与回执</Button>
      {data?.can_request === true && <div className="space-y-2 rounded-md bg-muted/30 p-3"><label className="block">本次重点要求<textarea className={field} maxLength={10000} disabled={generating || !!pending} value={instruction} onChange={event => setInstruction(event.target.value)}/></label>{!prepared && <p className="text-muted-foreground">先在上方核对本次分析资料。</p>}<Button size="sm" disabled={busy || generating || !!pending || !prepared || data.rollout !== "live"} onClick={() => prepared && void generate({ selection: prepared.selection, expected_digest: prepared.digest, user_instruction: instruction })}>生成矩阵分析</Button></div>}
      {generating && <p role="status">正在分析，可刷新原运行、查看预算和进度或停止。</p>}
      {data && rows(data.items).length === 0 && <p className="text-muted-foreground">这份对照尚无本人运行记录。</p>}
      {rows(data?.items).map(value => <div className="flex flex-wrap items-center gap-2 rounded-md border p-2" key={text(value.run_id)}><span>{new Date(text(value.created_at)).toLocaleString()} · {states[text(value.status)] ?? text(value.status)}</span><Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => open(text(value.run_id)))}>查看分析与原请求</Button>{value.status === "running" && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => stop(value))}>停止原运行</Button>}</div>)}
      {data?.next_before_id != null && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => read(text(data.next_before_id)))}>更早记录</Button>}
      {selected && <div className="space-y-3 rounded-md border p-3"><AgentRunProgressPanel runId={text(selected.run_id)} requestProgress={progress}/><p>{selected.sources_current === true ? "当前读取资料与本次固定依据一致" : "当前资料或读取范围已有变化，以下保留原分析；新办理须重新核对"}</p>{text(selected.user_instruction) && <p className="whitespace-pre-wrap">原重点要求：{text(selected.user_instruction)}</p>}{selected.error_code != null && <p>本次未完成：{text(selected.error_code)}</p>}
        {selected.assessment != null && <><p className="whitespace-pre-wrap">{text(assessment.coverage_limits)}</p>{assessment.disposition === "insufficient_evidence" && <p className="text-primary">本次资料不足，以下为有限观察与待补项。</p>}{rows(assessment.summary).map((value, index) => <Statement key={index} value={value} sources={sources}/>)}
          {rows(assessment.products).map(product => <article className="space-y-2 border-l pl-3" key={text(product.product_id)}><h6 className="font-medium">{productName(product.product_id)}</h6><p className="text-xs text-muted-foreground">定位说明</p><Statement value={obj(product.positioning)} sources={sources}/><p className="text-xs text-muted-foreground">声明覆盖与缺口</p><Statement value={obj(product.coverage)} sources={sources}/><Missing value={product.missing}/></article>)}
          {rows(assessment.criteria).map(criterion => <article className="space-y-2 border-l pl-3" key={text(criterion.criterion_key)}><h6 className="font-medium">{criterionName(criterion.criterion_key)}</h6><Statement value={obj(criterion.explanation)} sources={sources}/>{rows(criterion.human_next_steps).length > 0 && <p className="font-medium">建议人工下一步</p>}{rows(criterion.human_next_steps).map((value, index) => <Statement key={index} value={value} sources={sources}/>)}</article>)}
          {([['positioning_hypotheses', '定位重叠假设'], ['platform_reuse_hypotheses', '平台复用假设']] as const).map(([key, label]) => rows(assessment[key]).length > 0 && <section key={key} className="space-y-2"><h6 className="font-medium">{label}</h6>{rows(assessment[key]).map((value, index) => <article key={index} className="space-y-2 rounded-md bg-muted/30 p-3"><p>{Array.isArray(value.product_ids) ? value.product_ids.map(productName).join("；") : ""}</p><Statement value={obj(value.hypothesis)} sources={sources}/><Missing value={value.verification_needed}/></article>)}</section>)}<Missing value={assessment.missing}/></>}
        <details><summary className="cursor-pointer">本次固定资料与原字段</summary>{sources.map(source => <details className="mt-2" key={text(source.reference_id)}><summary className="cursor-pointer">{text(source.label)}</summary>{source.href != null && <a className="inline-flex min-h-11 items-center text-primary underline" href={text(source.href)}>打开当前原资料</a>}<pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-2 text-xs">{JSON.stringify(source.fields, null, 2)}</pre></details>)}</details>
        {selected.sources_current === true && data?.can_request === true && (selected.status === "running" || (selected.status === "degraded" && selected.error_code === "APPLICATION_RUN_LEASE_EXPIRED")) && <Button size="sm" variant="outline" disabled={busy || generating || !!pending || data.rollout !== "live"} onClick={() => void generate({ selection: selected.selection, expected_digest: selected.source_digest, user_instruction: selected.user_instruction }, text(selected.request_id))}>沿原请求接续（共享累计预算）</Button>}
      </div>}
    </div>
  </details>;
}
