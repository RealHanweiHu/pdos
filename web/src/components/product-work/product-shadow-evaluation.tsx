"use client";

import { useEffect, useRef, useState } from "react";
import { requestModelGovernanceBootstrap } from "@/components/governance/model-governance-api";
import type { EligibleModel } from "@/components/governance/model-governance-types";
import { Button } from "@/components/ui/button";
import { ProductRequestError, request } from "./product-work-api";

const capabilities: Record<string, string> = {
  research_planning: "研究规划", competitor_analysis: "竞品分析", market_analysis: "市场分析",
  opportunity_mapping: "机会映射", experiment_design: "实验设计", product_strategy: "产品策略",
  product_definition: "产品定义", product_matrix: "产品矩阵", rfq_requirements: "RFQ需求抽取",
};
const sha = /^[a-f0-9]{64}$/;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
type Case = { case_id: string; source_sha256: string; source: { market_space_id: string; selection: Record<string, unknown> } };
type Suite = { capability: string; suite_version: string; prompt_version: string; runtime_sha256: string; cases: Case[] };
type Original = { name: string; document: string; sha256: string; suite: Suite };
type Submission = { evaluation_id: string; suite_document: string; suite_sha256: string; binding: EligibleModel & { configuration_sha256: string } };
type Report = { evaluation_id: string; status: string; report_sha256: string; cases: { case_id: string; passed: boolean; attempts: { status: string; error_code: string | null; response?: { original_receipt_ref: string | null } | null }[] }[] };
type Receipt = { run_id: string; status: string; error_code: string | null; invocation_id: string | null; assessment: { summary: { nature: string; text: string }[]; missing: string[]; coverage_limits: string } | null };

function download(value: unknown, name: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = name; anchor.click();
  URL.revokeObjectURL(url);
}

async function readOriginal(file: File, space: string): Promise<Original> {
  if (file.size < 1 || file.size > 4 * 1024 * 1024) throw new Error("参考文件须为非空UTF-8 JSON，且不超过4 MiB。");
  const bytes = await file.arrayBuffer();
  const document = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
  let suite;
  try { suite = JSON.parse(document); } catch { throw new Error("无法读取参考文件，请使用原始UTF-8 JSON文件。"); }
  if (suite?.version !== "product-capability-evaluation.v1" || suite.review_status !== "candidate" ||
    !Object.hasOwn(capabilities, suite.capability) || typeof suite.suite_version !== "string" ||
    typeof suite.prompt_version !== "string" || !sha.test(suite.runtime_sha256 ?? "") ||
    !Array.isArray(suite.cases) || !suite.cases.length || suite.cases.length > 100 ||
    suite.cases.some((item: Case) => !item || typeof item.case_id !== "string" || !sha.test(item.source_sha256 ?? "") || item.source?.market_space_id !== space || !item.source.selection) ||
    new Set(suite.cases.map((item: Case) => item.case_id)).size !== suite.cases.length) {
    throw new Error("参考文件格式或市场空间不符。每份文件须包含同一能力的1～100个不同样例，并属于当前市场空间。");
  }
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return { name: file.name, document, suite, sha256: Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("") };
}

type Props = { base: string; disabled?: boolean; onPendingChange?: (pending: boolean) => void; onAuthorityLost?: (message: string) => void };
export function ProductShadowEvaluation(props: Props) {
  return <ProductShadowEvaluationPanel key={props.base} {...props}/>;
}
function ProductShadowEvaluationPanel({ base, disabled = false, onPendingChange, onAuthorityLost }: Props) {
  const [model, setModel] = useState<EligibleModel | null>(null);
  const [modelMessage, setModelMessage] = useState("请读取当前租户模型。");
  const [configuration, setConfiguration] = useState("");
  const [original, setOriginal] = useState<Original | null>(null);
  const [checked, setChecked] = useState(false);
  const [evaluationId, setEvaluationId] = useState("");
  const [pending, setPending] = useState<Submission | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [runId, setRunId] = useState("");
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [locked, setLocked] = useState(false);
  const lock = useRef(false);
  const callbacks = useRef({ onPendingChange, onAuthorityLost });
  useEffect(() => { callbacks.current = { onPendingChange, onAuthorityLost }; }, [onPendingChange, onAuthorityLost]);
  function changeLock(value: boolean) {
    if (!live.current || lock.current === value) return;
    lock.current = value; setLocked(value); callbacks.current.onPendingChange?.(value);
  }
  const live = useRef(true);
  const inFlight = useRef(false);
  useEffect(() => { live.current = true; return () => { live.current = false; if (lock.current) { lock.current = false; callbacks.current.onPendingChange?.(false); } }; }, []);

  async function act(work: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError("");
    try { await work(); } catch (failure) {
      if (live.current) {
        if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) {
          setOriginal(null); setPending(null); setChecked(false); setReport(null); setReceipt(null); setModel(null);
          setConfiguration(""); setEvaluationId(""); setRunId(""); changeLock(false);
          setModelMessage("当前权限或登录状态已失效，请重新核对。");
          callbacks.current.onAuthorityLost?.(failure.message);
        }
        setError(failure instanceof Error ? failure.message : "本次操作未确认，请重试原请求。");
      }
    } finally { inFlight.current = false; if (live.current) setBusy(false); }
  }

  async function readModel() {
    setModel(null); setModelMessage("正在读取当前租户模型…");
    const result = await requestModelGovernanceBootstrap();
    if (!live.current) return;
    if (result?.kind !== "ready") throw new ProductRequestError("当前身份不能读取模型配置，请确认管理员权限与登录状态。", 403);
    const selection = result.snapshot.selection;
    const selected = selection?.available && result.snapshot.eligible_models.find(item => item.provider === selection.provider && item.model === selection.model);
    if (selected && !result.snapshot.budget.exhausted) { setModel(selected); setModelMessage(`${selected.provider} · ${selected.model}`); }
    else setModelMessage(result.snapshot.budget.exhausted ? "当前模型预算已用完。" : "当前租户尚无可用的已选模型，请在模型管理中核对。");
    setChecked(false);
  }

  async function checkSources() {
    if (!original) return;
    setChecked(false);
    for (const item of original.suite.cases) {
      if (!live.current) return;
      const result = await request<{ source_sha256: string; runtime_sha256: string; prompt_version: string }>(`${base}/evaluation/prepare`, "POST", {
        capability: original.suite.capability,
        [original.suite.capability === "product_matrix" ? "matrix" : "work"]: item.source.selection,
      });
      if (result.source_sha256 !== item.source_sha256 || result.runtime_sha256 !== original.suite.runtime_sha256 || result.prompt_version !== original.suite.prompt_version) {
        throw new Error(`样例 ${item.case_id} 的来源或执行版本已变化，请由参考资料负责人重新核对原件。`);
      }
    }
    if (live.current) setChecked(true);
  }

  async function submit(body: Submission) {
    setPending(body); setEvaluationId(body.evaluation_id); setReport(null); setReceipt(null);
    changeLock(true);
    try {
      const result = await request<Report>(`${base}/evaluation/suite`, "POST", body);
      if (!result || result.evaluation_id !== body.evaluation_id || !Array.isArray(result.cases) || typeof result.status !== "string" || !sha.test(result.report_sha256 ?? "")) throw new Error("评测回执未确认，请重试原评测请求。");
      if (live.current) { setReport(result); changeLock(false); }
    } catch (failure) {
      if (live.current && failure instanceof ProductRequestError && failure.status >= 400 && failure.status < 500 && ![408, 429].includes(failure.status)) changeLock(false);
      throw failure;
    }
  }

  async function readRun(id: string) {
    setReceipt(null);
    const result = await request<Receipt>(`${base}/evaluation/runs/${id}`);
    if (live.current) setReceipt(result);
  }

  return <section className="space-y-4 rounded-lg border p-4" aria-label="产品能力影子评测">
    <div><h3 className="font-semibold">产品能力影子评测</h3><p className="mt-2 text-sm text-muted-foreground">管理员导入独立人员提供的参考文件，逐样例核对当前来源，再使用当前租户模型比对。结果只供发起人复核；比对通过后仍须独立核验调用证明、参考答案与人工出口。</p></div>
    <p className="text-sm text-muted-foreground">本入口不会授予能力资格或生成业务动作。提交会实际调用模型并消耗预算，服务器仍检查计量、授权及来源版本。</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {busy && <p role="status" className="text-sm">正在核对或取回结果，请稍候…</p>}
    <fieldset disabled={busy || disabled || !!pending} className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-center gap-3"><Button variant="outline" onClick={() => void act(readModel)}>读取当前租户模型</Button><a className="text-sm text-primary underline" href="/governance/models">模型管理</a></div>
      <p className="break-words text-sm">{modelMessage}</p>
      <label className="block text-sm">人工参考文件<input className={field} type="file" accept=".json,application/json" onChange={event => {
        const file = event.target.files?.[0]; event.currentTarget.value = "";
        setOriginal(null); setChecked(false); setReport(null); setReceipt(null);
        if (file) void act(async () => { const result = await readOriginal(file, base.split("/")[1]); if (live.current) setOriginal(result); });
      }}/></label>
      <label className="block text-sm">已核对的模型配置摘要<input className={field} maxLength={64} value={configuration} placeholder="由配置负责人提供的64位SHA-256" onChange={event => setConfiguration(event.target.value)}/></label>
      <label className="block text-sm">评测编号（继续已有评测时填写）<input className={field} value={evaluationId} maxLength={36} onChange={event => setEvaluationId(event.target.value.trim())}/></label>
      {original && <div className="space-y-2 text-sm"><p className="break-all">{original.name} · {capabilities[original.suite.capability]} · {original.suite.suite_version} · {original.suite.cases.length}个样例</p><details><summary className="cursor-pointer">查看原件摘要与样例编号</summary><p className="mt-2 break-all">{original.sha256}</p><ul>{original.suite.cases.map(item => <li className="break-all" key={item.case_id}>{item.case_id}</li>)}</ul></details>
        <Button variant="outline" onClick={() => void act(checkSources)}>核对全部样例来源</Button>
        {checked && <p>当前来源与执行版本相符；提交时还会再次核对。参考答案的正确性与独立性仍需人工确认。</p>}
      </div>}
      <Button disabled={!model || !original || !checked || !sha.test(configuration) || (!!evaluationId && !uuid.test(evaluationId))} onClick={() => {
        if (model && original) void act(() => submit({ evaluation_id: evaluationId || crypto.randomUUID(), suite_document: original.document, suite_sha256: original.sha256, binding: { ...model, configuration_sha256: configuration } }));
      }}>提交影子评测</Button>
    </fieldset>
    {pending && <div className="space-y-2 rounded-md bg-muted p-3 text-sm"><p className="break-all">本次评测编号：{pending.evaluation_id}</p><p>重试会保留原参考文件、模型和评测编号。结果未确认时请先取回本次回执，再准备另一轮。明确拒绝也可能已有部分样例执行，请保留编号回查。</p><Button variant="outline" disabled={busy || disabled} onClick={() => void act(() => submit(pending))}>{report ? "重新取回本次评测" : "重试原评测请求"}</Button>
      <Button variant="ghost" disabled={busy || disabled || locked} onClick={() => { if (lock.current) return; setPending(null); setOriginal(null); setChecked(false); setReport(null); setReceipt(null); setEvaluationId(""); setError(""); }}>准备另一轮评测</Button></div>}
    {report && <div className="space-y-3 text-sm"><p className="font-medium">{report.status === "passed" ? "样例比对通过，仍待人工复核与独立证明。" : "本轮存在不匹配或未完成样例，请逐项复核。"}</p>
      <p>尚未授予能力资格。</p><Button variant="outline" disabled={busy} onClick={() => void act(async () => {
        await checkSources();
        if (live.current) download(report, `product-evaluation-${report.evaluation_id}.json`);
      })}>下载评测报告</Button>
      <ul className="space-y-2">{report.cases.map(item => <li key={item.case_id} className="rounded-md border p-3"><p className="break-all">{item.case_id} · {item.passed ? "参考比对相符" : "待复核"}</p>{item.attempts.map((attempt, index) => {
        const prefix = `/api/product-work/${base}/evaluation/runs/`;
        const ref = attempt.response?.original_receipt_ref;
        const id = ref?.startsWith(prefix) ? ref.slice(prefix.length) : "";
        return <div className="mt-2" key={index}>{attempt.error_code && <p className="break-words text-destructive">未完成原因：{attempt.error_code}</p>}{uuid.test(id) && <Button aria-label={`查看${item.case_id}原回执`} size="sm" variant="outline" disabled={busy} onClick={() => { setRunId(id); void act(() => readRun(id)); }}>查看原回执</Button>}</div>;
      })}</li>)}</ul>
    </div>}
    <form className="space-y-2 border-t pt-4" onSubmit={event => { event.preventDefault(); void act(() => readRun(runId)); }}>
      <label className="block text-sm">原运行编号<input className={field} value={runId} maxLength={36} onChange={event => { setRunId(event.target.value.trim()); setReceipt(null); }}/></label>
      <Button variant="outline" disabled={busy || !uuid.test(runId)}>查询我的原回执</Button>
    </form>
    {receipt && <div className="space-y-2 rounded-md border p-3 text-sm"><p>{({ succeeded: "结果已保存", running: "尚在运行", failed: "执行失败", degraded: "未完成" } as Record<string, string>)[receipt.status] ?? "尚未完成"} · 影子评测</p>
      {receipt.error_code && <p className="break-words text-destructive">未完成原因：{receipt.error_code}</p>}
      {receipt.assessment?.summary.map((item, index) => <p key={index}>{({ observed: "观察", derived: "推断", hypothesis: "待验证" } as Record<string, string>)[item.nature] ?? "建议"}：{item.text}</p>)}
      {receipt.assessment?.missing.map((item, index) => <p key={index}>待补：{item}</p>)}
      {receipt.assessment && <p className="text-muted-foreground">{receipt.assessment.coverage_limits}</p>}
      <p className="break-all text-xs text-muted-foreground">运行：{receipt.run_id} · 调用：{receipt.invocation_id ?? "暂无有效回执"}</p>
      <Button variant="outline" disabled={busy} onClick={() => void act(async () => {
        const current = await request<Receipt>(`${base}/evaluation/runs/${receipt.run_id}`);
        if (live.current) { setReceipt(current); download(current, `product-evaluation-run-${current.run_id}.json`); }
      })}>下载原回执与冻结来源</Button>
    </div>}
  </section>;
}
