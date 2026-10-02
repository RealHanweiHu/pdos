"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowClockwiseIcon, ChartBarIcon } from "@phosphor-icons/react";

type Observation = {
  draft_kind: string; policy_revision: number; provider: string; model: string;
  model_version: string | null; prompt_version: string; context_version: string;
  generated: number; confirmed: number; edited: number; withdrawn: number;
  handled: number; pending: number; retained_original: number;
  withdrawn_after_confirmation: number; published: number;
};
type Result = {
  as_of: string; window_start: string; items: Observation[];
  next_offset: number | null; scope_notice: string;
};
const labels: Record<string, string> = { minutes: "会议纪要", actions: "会议行动项", decisions: "会议决策" };
const buttonClass = "inline-flex min-h-8 items-center justify-center gap-1.5 rounded-md border bg-background px-2.5 text-xs outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";
function ratio(numerator: number, denominator: number) {
  return denominator ? `${(numerator / denominator * 100).toFixed(1)}%` : "暂无样本";
}

export function AiWriteObservations() {
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retryAppend, setRetryAppend] = useState(false);
  const generation = useRef(0);

  async function load(append = false) {
    const current = ++generation.current;
    setBusy(true); setError(null); setRetryAppend(append);
    const query = append && result?.next_offset !== null && result
      ? `?as_of=${encodeURIComponent(result.as_of)}&offset=${result.next_offset}` : "";
    try {
      const response = await fetch(`/api/ai/governance/write-policy/observations${query}`, { credentials: "same-origin", cache: "no-store" });
      if (current !== generation.current) return;
      if (!response.ok) {
        if ([401, 403].includes(response.status)) setResult(null);
        throw new Error([401, 403].includes(response.status) ? "当前账号无法读取试运行观察，请核对登录与权限。" : "暂时无法读取试运行记录，请重试。");
      }
      const next = await response.json() as Result;
      if (current !== generation.current) return;
      setResult(previous => ({ ...next, items: append && previous ? [...previous.items, ...next.items] : next.items }));
    } catch (failure) {
      if (current === generation.current) setError(failure instanceof Error ? failure.message : "读取失败，请重试。");
    } finally { if (current === generation.current) setBusy(false); }
  }
  useEffect(() => {
    const current = ++generation.current;
    const controller = new AbortController();
    void fetch("/api/ai/governance/write-policy/observations", { credentials: "same-origin", cache: "no-store", signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error([401, 403].includes(response.status) ? "当前账号无法读取试运行观察，请核对登录与权限。" : "暂时无法读取试运行记录，请重试。");
        const next = await response.json() as Result;
        if (current === generation.current) setResult(next);
      }).catch((failure: unknown) => {
        if (current === generation.current) setError(failure instanceof Error ? failure.message : "读取失败，请重试。");
      }).finally(() => { if (current === generation.current) setBusy(false); });
    return () => { generation.current += 1; controller.abort(); };
  }, []);

  return <section aria-label="AI 草稿试运行观察" aria-busy={busy} className="mt-3 rounded-lg border bg-muted/15 p-3">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h3 className="flex items-center gap-1.5 text-xs font-semibold"><ChartBarIcon size={16} className="text-primary" aria-hidden="true" />近 30 天 · 草稿试运行</h3>
        <p className="mt-1 text-[11px] leading-5 text-muted-foreground">只读统计，不产生待办，不自动授予写入资格。</p></div>
      <button type="button" className={buttonClass} disabled={busy} onClick={() => void load()}><ArrowClockwiseIcon size={14} aria-hidden="true" />刷新统计</button>
    </div>
    {result && <>
      <p className="mt-2 text-[11px] leading-5 text-muted-foreground">{new Date(result.window_start).toLocaleString("zh-CN")} — {new Date(result.as_of).toLocaleString("zh-CN")}</p>
      <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{result.scope_notice}</p>
      <div className="mt-3 space-y-2">{result.items.map(item => <article key={JSON.stringify([item.draft_kind, item.policy_revision, item.provider, item.model, item.model_version, item.prompt_version, item.context_version])} className="min-w-0 rounded-md border bg-card px-3 py-3">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs"><h4 className="font-semibold">{labels[item.draft_kind] ?? item.draft_kind}</h4><span className="text-muted-foreground">政策第 {item.policy_revision} 版 · {item.provider} / {item.model}</span></div>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
          {[["生成草稿", item.generated], ["已办理", item.handled], ["仍待确认", item.pending], ["已正式发布", item.published]].map(([label, value]) => <div key={label}><dt className="text-[11px] text-muted-foreground">{label}</dt><dd className="mt-0.5 font-mono text-base tabular-nums">{value}</dd></div>)}
        </dl>
        <dl className="mt-3 grid gap-2 border-t pt-3 text-xs sm:grid-cols-2">
          <div><dt className="text-muted-foreground">办理后确认率</dt><dd className="mt-1">{ratio(item.confirmed, item.handled)} <span className="text-[11px] text-muted-foreground">（确认 {item.confirmed} / 已办理 {item.handled}）</span></dd></div>
          <div><dt className="text-muted-foreground">确认后修改率</dt><dd className="mt-1">{ratio(item.edited, item.confirmed)} <span className="text-[11px] text-muted-foreground">（修改 {item.edited} / 已确认 {item.confirmed}）</span></dd></div>
          <div><dt className="text-muted-foreground">确认后撤回率</dt><dd className="mt-1">{ratio(item.withdrawn_after_confirmation, item.confirmed)} <span className="text-[11px] text-muted-foreground">（撤回 {item.withdrawn_after_confirmation} / 已确认 {item.confirmed}）</span></dd></div>
          <div><dt className="text-muted-foreground">原稿仍保留</dt><dd className="mt-1">{item.retained_original} 份 <span className="text-[11px] text-muted-foreground">· 所有撤回 {item.withdrawn} 份</span></dd></div>
        </dl>
        <details className="mt-3 text-[11px] text-muted-foreground"><summary className="cursor-pointer rounded outline-none focus-visible:ring-2 focus-visible:ring-ring">版本与统计口径</summary><p className="mt-2 break-words leading-5">模型版本：{item.model_version ?? "未登记，不能视为已固定模型版本"}；提示词：{item.prompt_version}；上下文：{item.context_version}。</p><p className="mt-1 leading-5">每份草稿仅计一次，重复修订不增加份数。已办理包括确认或撤回；修改、撤回与发布可能属于同一份草稿，不相加。原稿仍保留指已确认且未修改、未撤回；未独立核对其当前来源有效性。</p></details>
      </article>)}</div>
      {result.items.length === 0 && <p className="py-4 text-center text-xs text-muted-foreground">此窗口暂无会议草稿试运行记录，尚不能计算确认或撤回比例。</p>}
    </>}
    {error && <p role="alert" className="mt-3 text-xs text-destructive">{error}</p>}
    {busy && <p role="status" className="mt-3 text-xs text-muted-foreground">正在读取原始办理回执…</p>}
    {!busy && (error || result?.next_offset !== null && result) && <button type="button" className={`${buttonClass} mt-3`} onClick={() => void load(error ? retryAppend : true)}>{error ? "重新读取" : "更多版本分组"}</button>}
  </section>;
}
