"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AgentRunProgressPanel } from "@/components/ai/agent-run-progress";
import type { AgentRunProgress } from "@/components/ai/ai-types";
import { Button } from "@/components/ui/button";
import { ProductEvidenceProposal } from "./product-evidence-proposal";
import { ProductRfqProposal } from "./product-rfq-proposal";
import { ProductResearchProposal } from "./product-research-proposal";
import { ProductRequestError, request } from "./product-work-api";

export type ProductSelection = { capability: string; product_line_id: string | null; question: string; sources: { kind: string; id: string; ordinals?: number[] }[] };
type Citation = { reference_id: string; digest: string; field_path: string[]; quoted_value: string };
type Statement = { nature: string; text: string; citations: Citation[] };
type Assessment = { disposition: string; summary: Statement[]; sections: { key: string; statements: Statement[]; missing: string[] }[]; next_steps: Statement[]; missing: string[]; coverage_limits: string };
type Source = { reference_id: string; label: string; href: string; fields: Record<string, unknown> };
type Run = { run_id: string; request_id: string; status: string; created_at: string; error_code: string | null; invocation_id: string | null; assessment: Assessment | null; source_digest: string; sources_current?: boolean; selection: ProductSelection; user_instruction: string; reference_labels: Record<string, string>; frozen_sources?: Source[] };
type History = { can_request: boolean; rollout: string; items: Run[]; next_before_id: string | null };
type RunRequest = { request_id: string; selection: ProductSelection; expected_digest: string; user_instruction?: string };
const sectionNames: Record<string, string> = {
  requirements: "客户需求", acceptance_criteria: "验收条件", uncertainties: "待澄清",
  questions: "研究问题", scope_and_sources: "范围与来源", method: "方法", stop_conditions: "停止条件",
  comparison_scope: "比较范围", conditions_and_units: "条件与单位", differences: "差异", conflicts: "冲突",
  users_and_jtbd: "用户与任务", market_size: "市场规模", assumptions: "假设", evidence_gaps: "证据缺口",
  desired_outcomes: "期望结果", opportunities: "机会", alternatives: "备选方案", tradeoffs: "取舍",
  hypotheses: "待验证假设", vuvf_coverage: "四类实验覆盖", falsification: "证伪条件",
  canvas: "策略画布", routes: "方案路线", cost_and_timing: "成本与时机", professional_constraints: "专业约束",
  strategy_basis: "策略依据", scope: "产品范围", specifications: "规格", verification: "验证判据",
};
const statuses: Record<string, string> = { running: "分析中", succeeded: "分析已保存", degraded: "未完成", failed: "失败" };

function Statements({ statements, run }: { statements: Statement[]; run: Run }) {
  return <ul className="space-y-2">{statements.map((statement, index) => <li key={index} className="rounded-md border p-3">
    <p><span className="text-muted-foreground">{({ observed: "观察", derived: "推断", hypothesis: "待验证" } as Record<string, string>)[statement.nature]} · </span>{statement.text}</p>
    {statement.citations.map((citation, i) => <details className="mt-2 text-xs" key={i}><summary className="cursor-pointer text-primary">依据：{run.reference_labels[citation.reference_id] ?? "原始资料"} · {citation.field_path.join(" / ")}</summary>
      <blockquote className="mt-2 whitespace-pre-wrap break-words border-l-2 pl-3">{citation.quoted_value}</blockquote>
    </details>)}
  </li>)}</ul>;
}

type Props = {
  base: string; capability: string; line: string; initialRunId?: string;
  prepared: { digest: string; selection: ProductSelection } | null; disabled?: boolean;
  onAuthorityDenied?: (message: string) => void; captureAccess?: () => () => boolean; onPendingChange?: (pending: boolean) => void;
};
const authorityDenied = (failure: unknown) => failure instanceof ProductRequestError && [401, 403].includes(failure.status);
export function ProductAiRuns(props: Props) {
  return <ProductAiRunsPanel key={JSON.stringify([props.base, props.capability, props.line])} {...props}/>;
}
function ProductAiRunsPanel({ base, capability, line, initialRunId, prepared, disabled = false, onAuthorityDenied, captureAccess, onPendingChange }: Props) {
  const [history, setHistory] = useState<History | null>(null);
  const [active, setActive] = useState<Run | null>(null);
  const [pending, setPending] = useState<RunRequest | null>(null);
  const [busy, setBusy] = useState(false), [sending, setSending] = useState(false), [error, setError] = useState("");
  const [confirmationPending, setConfirmationPending] = useState(false);
  const confirmationOwner = useRef<string | null>(null), pendingCallback = useRef(onPendingChange);
  useEffect(() => { pendingCallback.current = onPendingChange; }, [onPendingChange]);
  useEffect(() => { pendingCallback.current?.(!!pending || confirmationPending); }, [pending, confirmationPending]);
  const live = useRef(true), revision = useRef(0), runVersion = useRef(0), reading = useRef(false), submitting = useRef(false);
  const currentRequest = useRef<string | null>(null), original = useRef<RunRequest | null>(null), deniedCallback = useRef(onAuthorityDenied);
  useEffect(() => { deniedCallback.current = onAuthorityDenied; }, [onAuthorityDenied]);
  useEffect(() => { live.current = true; return () => { live.current = false; revision.current += 1; runVersion.current += 1; pendingCallback.current?.(false); }; }, []);
  const clearAuthority = useCallback((message: string) => {
    if (!live.current) return;
    revision.current += 1; runVersion.current += 1; reading.current = false; submitting.current = false;
    currentRequest.current = null; original.current = null; confirmationOwner.current = null; setConfirmationPending(false);
    setHistory(null); setActive(null); setPending(null); setBusy(false); setSending(false); setError(message);
    deniedCallback.current?.(message);
  }, []);
  const capture = useCallback(() => {
    const current = revision.current, parent = captureAccess?.() ?? (() => true);
    return () => live.current && revision.current === current && parent();
  }, [captureAccess]);
  useEffect(() => {
    if (!initialRunId || original.current || confirmationOwner.current) return;
    let active = true;
    const current = capture();
    void request<History>(`${base}/product-ai-history`, "POST", { capability, product_line_id: line || null, before_id: null, run_id: initialRunId }).then(value => { if (!active || !current() || original.current || confirmationOwner.current) return; const item = value.items.find(item => item.run_id === initialRunId); if (!item || item.selection.capability !== capability || (item.selection.product_line_id ?? "") !== line) throw new Error("原运行与当前能力或产品线不匹配，请返回原工作范围。"); setHistory(value); setActive(item); }).catch(failure => { if (!active || !current()) return; if (authorityDenied(failure)) clearAuthority((failure as Error).message); else setError(failure instanceof Error ? failure.message : "原运行暂不可读"); });
    return () => { active = false; };
  }, [base, capability, line, initialRunId, capture, clearAuthority]);
  const readProgress = useCallback(async (id: string) => {
    const current = capture();
    try {
      const value = await request<AgentRunProgress>(`${base}/product-ai-progress`, "POST", { run_id: id });
      if (!current()) throw new Error("当前读取范围已变化，请重新读取分析记录。");
      return value;
    } catch (failure) { if (current() && authorityDenied(failure)) clearAuthority((failure as Error).message); throw failure; }
  }, [base, capture, clearAuthority]);
  function proposalPending(runId: string, value: boolean) {
    if (!live.current) return;
    if (value) { confirmationOwner.current = runId; setConfirmationPending(true); }
    else if (confirmationOwner.current === runId) { confirmationOwner.current = null; setConfirmationPending(false); }
  }
  const proposalFailure = (message: string) => { if (live.current) setError(message); };
  function clearPending() { original.current = null; setPending(null); }
  function recover(items: Run[]) {
    const found = items.find(item => item.request_id === currentRequest.current);
    if (!found) return null;
    clearPending();
    if (found.status !== "running") {
      currentRequest.current = null; runVersion.current += 1; submitting.current = false; setSending(false);
    }
    return found;
  }
  async function read(before?: string, runId?: string) {
    if (!live.current || reading.current || (runId && confirmationOwner.current)) return;
    reading.current = true; setBusy(true); setError(""); const current = capture();
    try {
      const result = await request<History>(`${base}/product-ai-history`, "POST", { capability, product_line_id: line || null, before_id: before ?? null, run_id: runId ?? null });
      if (!current()) return;
      const recovered = recover(result.items);
      if (runId && !confirmationOwner.current) setActive(result.items.find(item => item.run_id === runId) ?? null);
      else if (recovered) setActive(recovered);
      if (!runId) setHistory(previous => before && previous ? { ...result, items: [...previous.items, ...result.items] } : result);
    } catch (failure) {
      if (!current()) return;
      if (authorityDenied(failure)) clearAuthority((failure as Error).message);
      else setError(failure instanceof Error ? failure.message : "历史暂不可读，已保留上次读取记录。");
    } finally { if (current()) { reading.current = false; setBusy(false); } }
  }
  async function run(body: RunRequest) {
    if (!live.current || submitting.current || reading.current || disabled || confirmationOwner.current || !history?.can_request || history.rollout !== "live") return;
    if (original.current && original.current.request_id !== body.request_id) return;
    const requestBody = original.current ?? JSON.parse(JSON.stringify(body)) as RunRequest;
    original.current = requestBody; const version = ++runVersion.current; currentRequest.current = requestBody.request_id;
    submitting.current = true; setSending(true); setError(""); setActive(null); setPending(requestBody);
    const current = capture();
    try {
      const result = await request<Run>(`${base}/product-ai-runs`, "POST", requestBody);
      if (!current() || version !== runVersion.current) return;
      setActive(result); clearPending(); currentRequest.current = result.status === "running" ? requestBody.request_id : null;
      setHistory(previous => previous ? { ...previous, items: [result, ...previous.items.filter(item => item.run_id !== result.run_id)] } : previous);
    } catch (failure) {
      if (!current() || version !== runVersion.current) return;
      if (authorityDenied(failure)) clearAuthority((failure as Error).message);
      else {
        if (failure instanceof ProductRequestError && failure.status < 500 && ![408, 429].includes(failure.status)) { clearPending(); currentRequest.current = null; }
        setError(failure instanceof Error ? failure.message : "运行回执暂未返回，请查询历史或用原请求重试");
      }
    } finally { if (current() && version === runVersion.current) { submitting.current = false; setSending(false); } }
  }
  async function cancel(runId: string) {
    if (!live.current || reading.current) return;
    reading.current = true; setBusy(true); setError(""); const current = capture();
    try {
      const result = await request<{ run: Run }>(`${base}/product-ai-cancel`, "POST", { run_id: runId });
      if (!current()) return;
      recover([result.run]); setActive(result.run); setHistory(previous => previous ? { ...previous, items: previous.items.map(item => item.run_id === runId ? result.run : item) } : previous);
    } catch (failure) {
      if (!current()) return;
      if (authorityDenied(failure)) clearAuthority((failure as Error).message);
      else setError(failure instanceof Error ? failure.message : "停止请求未确认，已保留原记录，请刷新历史核对。");
    } finally { if (current()) { reading.current = false; setBusy(false); } }
  }
  return <section className="mt-4 space-y-3 border-t pt-4" aria-label="产品分析运行">
    <p className="text-sm text-muted-foreground">分析建议保留原始依据与运行回执。登记任务、实验结论和正式发布需在对应业务区办理。</p>
    <Button variant="outline" size="sm" disabled={busy} onClick={() => void read()}>读取 / 刷新我的分析</Button>
    {history && history.rollout !== "live" && <p className="text-sm text-muted-foreground">此项分析尚未开放。可以核对资料和查看已有记录；真实模型资格与启用待完成。</p>}
    {history?.rollout === "live" && !history.can_request && <p className="text-sm text-muted-foreground">当前范围只读，不能发起分析。</p>}
    <Button className="ml-2" size="sm" disabled={busy || sending || disabled || !prepared || !history?.can_request || history.rollout !== "live" || !!pending || confirmationPending} onClick={() => prepared && void run({ request_id: crypto.randomUUID(), selection: prepared.selection, expected_digest: prepared.digest })}>基于已核对资料分析</Button>
    {pending && <div className="space-y-2 text-sm"><p>原请求尚未确认。可刷新我的分析；重试保持原输入和请求编号。</p><Button variant="outline" size="sm" disabled={busy || sending || disabled || !history?.can_request || history.rollout !== "live"} onClick={() => void run(pending)}>重试原请求</Button></div>}
    {(busy || sending) && <p role="status" className="text-sm">正在读取或执行，请稍候…</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {history?.items.length === 0 && <p className="text-sm text-muted-foreground">此能力与产品线尚无你的分析记录。</p>}
    <ul className="space-y-2">{history?.items.map(item => <li key={item.run_id} className="rounded-md border p-3 text-sm">
      <p>{item.selection.question} · {statuses[item.status] ?? item.status} · {new Date(item.created_at).toLocaleString()}</p>
      {item.sources_current === false && <p className="text-primary">原资料已变化，结论仅供历史追溯。</p>}
      <AgentRunProgressPanel runId={item.run_id} requestProgress={readProgress}/>
      <Button variant="ghost" size="sm" disabled={busy || confirmationPending} onClick={() => void read(undefined, item.run_id)}>查看分析与原依据</Button>
      {item.status === "running" && <Button variant="outline" size="sm" disabled={busy} onClick={() => void cancel(item.run_id)}>停止此次分析</Button>}
      {(item.status === "running" || item.error_code === "APPLICATION_RUN_LEASE_EXPIRED") && <Button variant="ghost" size="sm" disabled={busy || sending || disabled || !!pending || confirmationPending || !history.can_request || history.rollout !== "live" || item.sources_current === false} onClick={() => void run({ request_id: item.request_id, selection: item.selection, expected_digest: item.source_digest, user_instruction: item.user_instruction })}>取回原运行结果</Button>}
    </li>)}</ul>
    {history?.next_before_id && <Button variant="outline" size="sm" disabled={busy} onClick={() => void read(history.next_before_id!)}>更早的分析</Button>}
    {active && <div className="space-y-3 rounded-lg border p-4 text-sm">
      <p className="font-medium">{statuses[active.status] ?? active.status} · {active.selection.question}</p>
      {active.sources_current === false && <p className="text-primary">资料已变化；请重新核对后另发分析。</p>}
      {active.error_code && <p className="text-destructive">本次未形成可用分析：{active.error_code}</p>}
      {active.assessment && <><p>{active.assessment.disposition === "insufficient_evidence" ? "资料不足，以下为缺项与建议。" : "以下为分析建议，尚未登记为业务结果。"}</p>
        <Statements statements={active.assessment.summary} run={active}/>
        {active.assessment.sections.map(section => <section key={section.key} className="space-y-2"><h4 className="font-medium">{sectionNames[section.key] ?? section.key}</h4><Statements statements={section.statements} run={active}/>{section.missing.map((gap, i) => <p key={i} className="text-muted-foreground">待补：{gap}</p>)}</section>)}
        <h4 className="font-medium">建议下一步</h4><Statements statements={active.assessment.next_steps} run={active}/>
        {active.assessment.missing.map((gap, i) => <p key={i}>待补：{gap}</p>)}<p className="text-muted-foreground">{active.assessment.coverage_limits}</p>
      </>}
      {capability === "rfq_requirements" && active.assessment && <ProductRfqProposal key={active.run_id} base={base} runId={active.run_id} onFailure={proposalFailure} onAccessDenied={clearAuthority} onPendingChange={value => proposalPending(active.run_id, value)} captureAccess={capture} disabled={disabled || history?.rollout !== "live" || !history?.can_request}/>}
      {capability === "research_planning" && active.assessment && <ProductResearchProposal key={active.run_id} base={base} runId={active.run_id} onFailure={proposalFailure} onAccessDenied={clearAuthority} disabled={disabled || history?.rollout !== "live" || !history?.can_request}/>}
      {["competitor_analysis", "market_analysis", "opportunity_mapping", "experiment_design", "product_strategy", "product_definition"].includes(capability) && active.assessment && <ProductEvidenceProposal key={active.run_id} base={base} runId={active.run_id} onFailure={proposalFailure} onAccessDenied={clearAuthority} disabled={disabled || history?.rollout !== "live" || !history?.can_request}/>}
      {active.frozen_sources?.map(source => <details key={source.reference_id}><summary className="cursor-pointer">原依据：{source.label}</summary><a className="my-2 inline-flex min-h-11 items-center text-primary underline" href={source.href}>打开所属业务区</a><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(source.fields, null, 2)}</pre></details>)}
      <p className="break-all text-xs text-muted-foreground">运行：{active.run_id}{active.invocation_id ? ` · 调用：${active.invocation_id}` : " · 尚无有效模型结果回执"}</p>
    </div>}
  </section>;
}
