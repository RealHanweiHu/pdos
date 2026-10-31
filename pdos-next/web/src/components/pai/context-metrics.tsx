import type { ReactNode } from "react";
import type { ProcessStep } from "@/lib/run-process";
import type { ContextMetrics } from "@/lib/run-context-metrics";
import { cleanupReason, contextCarrySummary, contextMetricSteps, metricCacheTokens, metricField, metricIsolation, metricNumber, metricPercent, metricSegments, metricWorkFields, reductionLabel, warningLabels } from "@/lib/run-context-metrics";

function Pair({ label, children }: { label: string; children: ReactNode }) {
  return <div className="min-w-0"><dt className="subtle">{label}</dt><dd className="break-words tabular-nums">{children}</dd></div>;
}
function MetricsRecord({ value }: { value: ContextMetrics }) {
  const warnings = [...new Set(value.warnings)].filter(key => warningLabels[key]);
  const run = value.run_budget;
  return <div className="space-y-3 text-sm">
    {warnings.length > 0 && <ul aria-label="已记录的上下文告警" className="space-y-1 rounded-lg border border-border bg-muted/40 p-3">{warnings.map(key => <li key={key}>{warningLabels[key]}</li>)}</ul>}
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <Pair label="模型窗口 W">{metricNumber(value.window)}</Pair>
      <Pair label="预留 R">{metricNumber(value.reserve)}</Pair>
      <Pair label="聚焦上限 F">{metricNumber(value.focus)}</Pair>
      <Pair label="输入估算">{metricNumber(value.estimated_input_tokens)}</Pair>
      <Pair label="含余量的入场计量">{metricNumber(value.admission_tokens)}</Pair>
      <Pair label="本次实际输入">{metricNumber(value.actual_input_tokens)}</Pair>
      <Pair label="本次实际输出">{metricNumber(value.actual_output_tokens)}</Pair>
      <Pair label="输入估算偏差">{metricPercent(value.estimation_error_ratio)}</Pair>
      <Pair label="校准系数">{metricNumber(value.calibration_factor)}</Pair>
    </dl>
    <p className="subtle">单位为 token。{value.window_configured === false ? "窗口未配置，采用服务器默认窗口。" : value.window_configured === null ? "窗口配置状态未知。" : ""}{value.usage_status === "unavailable" || value.call_state === "unknown" ? "调用实际用量尚未核实。" : ""}</p>
    <div className="overflow-x-auto"><table className="w-full text-left text-xs"><caption className="mb-2 text-left font-medium">各段计量</caption><thead><tr><th scope="col" className="py-1 pr-3">段</th><th scope="col" className="py-1 pr-3">估算</th><th scope="col" className="py-1">实际</th></tr></thead><tbody>{metricSegments.map(([key, label]) => <tr key={key}><th scope="row" className="py-1 pr-3 font-normal">{label}</th><td className="pr-3 tabular-nums">{metricNumber(value.segments?.[key]?.estimated_tokens)}</td><td className="tabular-nums">{metricNumber(value.segments?.[key]?.actual_tokens)}</td></tr>)}</tbody></table></div>
    <p className="subtle">服务商未报告的分段实际用量保持未知，不能从总量分摊。</p>
    <div><p className="mb-2 font-medium">缓存</p><dl className="grid grid-cols-2 gap-3 sm:grid-cols-3"><Pair label="读取缓存 token">{metricCacheTokens(value.cache?.read_tokens)}</Pair><Pair label="创建缓存 token">{metricCacheTokens(value.cache?.creation_tokens)}</Pair><Pair label="读取缓存占输入">{metricPercent(value.cache?.read_hit_ratio)}</Pair></dl><p className="subtle mt-1">缓存 token 已包含在输入总量中。未报告与归一化为 0 无法区分时，显示未知。</p></div>
    <div><p className="mb-2 font-medium">历史与工作状态</p><dl className="grid grid-cols-2 gap-3 sm:grid-cols-3"><Pair label="携带历史">{metricNumber(value.history?.carried)}</Pair><Pair label="保留历史">{metricNumber(value.history?.kept)}</Pair><Pair label="资料已更新标注">{metricNumber(value.history?.updated)}</Pair><Pair label="因权限隐藏">{metricNumber(value.history?.hidden)}</Pair><Pair label="历史预览或目录">{metricNumber(value.history?.truncated)}</Pair><Pair label="工作状态版本">{metricNumber(value.work_state?.revision)}</Pair>{metricWorkFields.map(([key, label]) => <Pair key={key} label={label}>{metricNumber(value.work_state?.item_counts?.[key])}</Pair>)}</dl></div>
    <div><p className="mb-1 font-medium">清理与省略</p><p>{cleanupReason(value.cleanup?.reason)}</p><dl className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-3"><Pair label="本次估算节省">{metricNumber(value.cleanup?.saved_tokens)}</Pair><Pair label="本次最小清理量">{metricNumber(value.cleanup?.minimum_tokens)}</Pair><Pair label="清理前入场计量">{metricNumber(value.cleanup?.before_tokens)}</Pair><Pair label="清理后入场计量">{metricNumber(value.cleanup?.after_tokens)}</Pair><Pair label="受保护结果">{metricNumber(value.cleanup?.protected_results)}</Pair><Pair label="保留最新结果">{metricNumber(value.cleanup?.retained_latest_results)}</Pair><Pair label="本运行已清理">{metricNumber(value.cleanup_count)} 次</Pair><Pair label="本次新增省略">{metricNumber(value.reductions_count)} 项</Pair></dl>
      {value.reductions.length > 0 && <ul className="mt-2 space-y-1">{value.reductions.map((row, index) => <li key={index}>{reductionLabel(row.kind)} · {metricField(row.field)}{row.recoverable ? " · 可按当前权限续读" : ""}</li>)}</ul>}
      {value.reductions_count !== null && value.reductions_count > value.reductions.length && <p className="subtle">另有 {metricNumber(value.reductions_count - value.reductions.length)} 项省略，仅展开前 {value.reductions.length} 项。</p>}
      <p className="subtle mt-1">此处省略的是模型消息视图，原始账本、回执、证据与错误记录保留。</p>
    </div>
    {(value.context_incomplete || value.missing.length > 0) && <div><p className="font-medium">本次未装入的必需内容</p>{value.missing.length ? <ul className="mt-1 space-y-1">{value.missing.map((row, index) => <li key={index}>{metricField(row.field)} · 估算 {metricNumber(row.estimated_tokens)} token</li>)}</ul> : <p className="subtle">具体缺项未记录。</p>}{value.missing_count !== null && value.missing_count > value.missing.length && <p className="subtle">另有 {metricNumber(value.missing_count - value.missing.length)} 项，请同时核对本轮结果的未完成项。</p>}</div>}
    <div><p className="mb-2 font-medium">运行预算快照</p><dl className="grid grid-cols-2 gap-3 sm:grid-cols-4"><Pair label="上限">{metricNumber(run?.limit)}</Pair><Pair label="已记账">{metricNumber(run?.used)}</Pair><Pair label="预占">{metricNumber(run?.held)}</Pair><Pair label="剩余">{metricNumber(run?.remaining)}</Pair></dl><p className="subtle mt-1">运行记账可包含待核实的预约量；本次实际输入与输出以已记录实测为准。</p></div>
  </div>;
}

export function ContextMetricsDetails({ steps }: { steps: ProcessStep[] }) {
  const records = contextMetricSteps(steps).sort((a, b) => b.sequence - a.sequence);
  const latest = records.find(step => step.context_metrics.isolation === "main") ?? records[0];
  if (!latest) return null;
  return <details aria-label="上下文携带与省略详情" className="rounded-lg border border-border p-3 text-sm">
    <summary className="cursor-pointer break-words">{contextCarrySummary(latest.context_metrics)}{latest.context_metrics.warnings.length > 0 ? ` · ${latest.context_metrics.warnings.filter(key => warningLabels[key]).length} 项告警` : ""}</summary>
    <div className="mt-3 space-y-4">
      <p className="subtle">以下按已载入的过程记录展示最近计量，不是新的模型调用。主调用优先显示；其他只读调用分别列出。更早调用可通过“读取更早步骤”查看。</p>
      <p className="font-medium">最近{metricIsolation(latest.context_metrics.isolation)}计量 · 步骤 {latest.sequence}{latest.context_metrics.context_incomplete ? " · 调用前已停止" : ""}</p>
      <MetricsRecord value={latest.context_metrics} />
      {records.filter(step => step.id !== latest.id).map(step => <details key={step.id} className="border-t border-border pt-3"><summary className="cursor-pointer">{step.sequence < latest.sequence ? "较早" : "其他"}计量 · 步骤 {step.sequence} · {metricIsolation(step.context_metrics.isolation)}</summary><div className="mt-3"><MetricsRecord value={step.context_metrics} /></div></details>)}
    </div>
  </details>;
}
