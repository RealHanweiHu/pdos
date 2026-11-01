"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowClockwise, ClipboardText, WarningCircle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { CandidateWorkflow } from "./candidate-workflow";
import { candidateErrorStatus, candidateReceipt, restoreCandidateLocal,
  type CandidateHost } from "./candidate-workflow-state";
import { candidateBusinessReview, candidatePanelScopeValid, candidateReadCancelled, candidateReadError,
  CandidatePanelScopeError, normalizeCandidatePanel, type CandidatePanelContext,
  type CandidatePanelData, type CandidateBusinessReview } from "./candidate-panel-contract";
import { record, type Read } from "./ui-contract";

export type CandidatePanelProps = {
  product: { id: string; revision: number }; principalId: string; issueId: string | null;
  api: <T>(path: string, body?: unknown) => Promise<T>;
  onSaved: () => Promise<void>;
  onPendingChange?: (locked: boolean) => void;
  onAccessRejected?: (saved: boolean, late?: boolean) => void;
  /** Parent busy/read failure gate, independent of server qualification. */
  blocked?: boolean;
};
const wrap = "min-w-0 [overflow-wrap:anywhere]";
const empty = "尚未提供，保持未知";
const roles: Record<string, string> = { quality: "品质", engineering: "工程", manufacturing: "制造" };
const risks: Record<string, string> = { low: "低", medium: "中", high: "高", critical: "关键" };
const meanings: Record<string, string> = { draft: "草稿", planned: "固定计划", observed: "已发生观察", performed: "实际执行" };

/** Clear only this exact actor/product/Issue's stored candidate requests on access rejection. */
function clearScopedStorage(context: CandidatePanelContext): boolean {
  let saved = false;
  try {
    const prefix = "pdos-next:capa-candidate:";
    const matched: string[] = [];
    for (let index = 0; index < localStorage.length; index++) {
      const key = localStorage.key(index);
      if (!key?.startsWith(prefix)) continue;
      try {
        const identity = key.slice(prefix.length), scope: unknown = JSON.parse(identity);
        if (!Array.isArray(scope) || scope.length !== 6 || scope[1] !== context.product.id ||
            scope[3] !== context.principalId || scope[4] !== context.issueId) continue;
        matched.push(key);
        try { const stored = restoreCandidateLocal(JSON.parse(localStorage.getItem(key) ?? "null"), identity);
          saved ||= stored?.outcome === "saved";
        } catch { /* A malformed payload is still removed after its scope matches. */ }
      } catch { /* Malformed unrelated keys do not authorize broad removal. */ }
    }
    for (const key of matched) localStorage.removeItem(key);
  } catch { /* No fallback private cache is created. */ }
  return saved;
}

export function CandidatePanel(props: CandidatePanelProps) {
  const context = { product: props.product, principalId: props.principalId, issueId: props.issueId ?? "" };
  if (!candidatePanelScopeValid(context)) return <section className="panel space-y-3" aria-label="复验候选">
    <h3 className="font-semibold">复验候选</h3><p className="text-sm">请先选择当前固定问题；尚未读取复验候选。</p>
  </section>;
  return <ScopedCandidatePanel key={JSON.stringify([props.product.id, props.principalId, props.issueId])}
    {...props} context={context}/>;
}

function ScopedCandidatePanel({ api, onSaved, onPendingChange, onAccessRejected, blocked = false,
  context }: CandidatePanelProps & { context: CandidatePanelContext }) {
  const [data, setData] = useState<CandidatePanelData | null>(null);
  const [loading, setLoading] = useState(false), [readFailed, setReadFailed] = useState(true);
  const [error, setError] = useState(""), [accessRejected, setAccessRejected] = useState(false);
  const [readEpoch, setReadEpoch] = useState(0), [savedHint, setSavedHint] = useState(false);
  const alive = useRef(false), sequence = useRef(0), current = useRef(context);
  const known = useRef<CandidatePanelData | null>(null), denied = useRef(false);
  const invalidateReads = useCallback(() => { sequence.current++; }, []);
  useLayoutEffect(() => { current.current = context; known.current = data; }, [context, data]);
  const clearPrivate = useCallback((savedKnown = false) => {
    denied.current = true;
    const saved = clearScopedStorage(current.current);
    if (alive.current) { setData(null); setReadFailed(true); setAccessRejected(true); setSavedHint(old => old || saved || savedKnown); }
    onAccessRejected?.(saved || savedKnown);
  }, [onAccessRejected]);
  const read = useCallback(async () => {
    const ticket = ++sequence.current, selected = current.current;
    if (alive.current) { setLoading(true); setReadFailed(true); setError(""); }
    try {
      const value = await api<unknown>(`v1/products/${selected.product.id}/capa-candidates?issue_id=${encodeURIComponent(selected.issueId)}`);
      if (!alive.current || ticket !== sequence.current) throw Object.assign(new Error("旧读取已由当前读取接管"), { code: "READ_SUPERSEDED" });
      const parsed = normalizeCandidatePanel(value, current.current);
      denied.current = false; setAccessRejected(false); setData(parsed); setReadFailed(false); setError("");
      setReadEpoch(epoch => epoch + 1);
    } catch (failure) {
      if (alive.current && ticket === sequence.current) {
        setReadFailed(true);
        const rejected = candidateErrorStatus(failure) === 401 || candidateErrorStatus(failure) === 403 || failure instanceof CandidatePanelScopeError;
        if (rejected) {
          denied.current = true; setAccessRejected(true);
          // A mounted workflow first clears its own exact in-flight state. It
          // calls clearPrivate afterwards; otherwise clear this scope directly.
          if (!known.current) clearPrivate();
        }
        setError(rejected ? "当前访问或返回范围不可核对，私有资料已停止展示与办理。" :
          candidateReadCancelled(failure) ? "本次读取已取消，请重试读取当前事实；原提交恢复不受此读取影响。" : candidateReadError(failure));
      }
      throw failure;
    } finally { if (alive.current && ticket === sequence.current) setLoading(false); }
  }, [api, clearPrivate]);
  useEffect(() => {
    alive.current = true;
    void Promise.resolve().then(() => { if (alive.current) return read(); }).catch(() => { /* read presents only the current failure. */ });
    return () => { alive.current = false; invalidateReads(); };
  }, [read, context.product.revision, invalidateReads]);
  const operationApi = useCallback(async <T,>(path: string, body?: unknown): Promise<T> => {
    if (body !== undefined) {
      sequence.current++; if (alive.current) setLoading(false);
    }
    const result = await api<T>(path, body);
    // If access was revoked while the write was in flight, disclose only that
    // the original request now has a saved result. No private receipt body.
    if (denied.current && candidateReceipt(result)) {
      if (alive.current) setSavedHint(true);
      else onAccessRejected?.(true, true);
    }
    return result;
  }, [api, onAccessRejected]);
  const afterSaved = useCallback(async () => {
    if (alive.current) setSavedHint(true);
    await onSaved();
    await read();
  }, [onSaved, read]);
  const loadHistory = async () => {
    if (!data?.history_page?.next_cursor || loading) return;
    const ticket = sequence.current;
    setLoading(true); setError("");
    try {
      const value = await api<unknown>(`v1/products/${current.current.product.id}/capa-candidates?issue_id=${encodeURIComponent(current.current.issueId)}&history_cursor=${encodeURIComponent(data.history_page.next_cursor)}`);
      if (!alive.current || ticket !== sequence.current) return;
      const page = normalizeCandidatePanel(value, current.current);
      setData(old => old ? { ...old, candidates: [...old.candidates, ...page.candidates.filter(row => !old.candidates.some(saved => saved.id === row.id))], history_page: page.history_page } : old);
    } catch (failure) {
      if (!alive.current || ticket !== sequence.current) return;
      if ([401, 403].includes(candidateErrorStatus(failure) ?? 0) || failure instanceof CandidatePanelScopeError) clearPrivate();
      setError("历史读取失败，请重试；已有填写与原请求保留。");
    } finally { if (alive.current && ticket === sequence.current) setLoading(false); }
  };
  const refresh = () => { if (!loading) void read().catch(() => { /* Current read error is already shown. */ }); };
  return <section className={`space-y-4 ${wrap}`} aria-label="复验候选" aria-busy={loading}>
    <div className="panel space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="flex items-center gap-2 font-semibold"><ClipboardText/>复验候选与固定历史</h3>
        <Button variant="outline" disabled={loading} onClick={refresh}><ArrowClockwise/>读取当前候选事实</Button></div>
      <p className="text-sm">选择已保存的整改回链与实际复验对应，形成一次固定候选。保存候选不证明措施有效，不关闭问题。</p>
      {loading && <p className="subtle">正在读取当前固定问题与候选；本次读取不发起操作。</p>}
      {error && <p role="alert" className="flex items-start gap-2 text-sm"><WarningCircle className="mt-0.5 size-4 shrink-0"/>{error}</p>}
      {savedHint && (readFailed || accessRejected) && <p role="status" className="text-sm">原操作已取得保存结果，当前读取尚未完成。不能重发已保存操作。</p>}
      {!data && !loading && !error && <p className="subtle">暂未取得当前候选事实，请读取后核对。</p>}
    </div>
    {data && !accessRejected && <>
      <p className="rounded-lg border p-3 text-sm">{data.missing_pair_options || "当前实际复验配对尚未接通，空选保持待核对。"}</p>
      <section className="panel space-y-3" aria-label="已保存候选历史"><h4 className="font-medium">已保存的固定候选</h4>
        {!data.candidates.length && <p className="subtle">尚无已保存候选。本页面不补造复验或观察记录。</p>}
        {data.candidates.map((candidate, index) => <article className={`space-y-2 rounded-lg border p-3 text-sm ${wrap}`} key={candidate.id}>
          <p className="font-medium">候选 {index + 1} · 第 {candidate.revision} 版 · 待核对</p><p>{candidate.reason}</p>
          <p>服务器接收记录：<span className="font-mono">{candidate.received_at}</span></p>
          <p>适用性未知 · 独立核验未知 · 观察完整性未知</p>
          <details className="text-xs text-muted-foreground"><summary className="cursor-pointer py-2">固定记录对账</summary>
            <p>候选：{candidate.id}</p><p>保存回执：{candidate.receipt_id}</p></details>
        </article>)}
        {data.history_page?.next_cursor && <Button variant="outline" disabled={loading} onClick={() => void loadHistory()}>读取更多候选历史</Button>}
        <p className="subtle">有效性决定与单独关闭尚未接通。未知不等于无效；候选不会推进问题状态。</p>
      </section>
    </>}
    {data && <CandidateWorkflow host={data.host} api={operationApi}
      inputs={command => operationApi(`v1/products/${current.current.product.id}/quality-followup/inputs`, command)}
      renderReview={(review, command) => {
        const reading = candidateBusinessReview(review, command, data.host);
        return reading ? { content: <BusinessReview reading={reading} host={data.host} reads={review.required_source_read_set}/>, complete: true } :
          { content: <p role="alert">固定原失败、整改完成记录或专业政策尚不能完整阅读，本次不能确认。</p>, complete: false };
      }} onSaved={afterSaved} onRefresh={read} onPendingChange={onPendingChange} onAccessRejected={clearPrivate}
      hostAccessRejected={accessRejected} hostAccessEpoch={readEpoch} blocked={blocked || loading || readFailed}/>} 
  </section>;
}

function BusinessReview({ reading: r, host, reads }: { reading: CandidateBusinessReview; host: CandidateHost; reads: Read[] }) {
  return <div className={`space-y-4 ${wrap}`}>
    {r.synthetic && <p className="rounded-lg border border-primary p-3 text-sm">本地合成演练：原失败、整改和当前专业政策用于核验流程，不代表真实生产资格。</p>}
    <section className="space-y-2"><h4 className="font-medium">本次范围与原失败依据</h4><p>{r.title}</p><p>用途：{r.purpose}</p>
      <p>原失败依据固定第 {r.origin_revision} 版；本次核对当前第 {r.current_revision} 版，历史不覆盖。</p>
      <p>可见范围：{r.visibility === "private" ? "原范围内仅本人可见" : "原型号范围内可见"} · 完整来源 {r.source_count} 份</p>
      <p>保存原因：{r.reason}</p></section>
    <section className="space-y-3"><h4 className="font-medium">原失败原值与工况（只读）</h4>
      {r.failures.map((f, index) => <article key={f.identity} className={`space-y-2 rounded-lg border p-3 text-sm ${wrap}`}>
        <p className="font-medium">{index + 1}. {f.feature} · 固定计算结果：失败</p>
        <dl className="grid min-w-0 gap-2 sm:grid-cols-2">
          <Fact label="原值" value={f.raw_value}/><Fact label="单位" value={f.unit}/><Fact label="工况" value={f.conditions}/>
          <Fact label="环境" value={f.environment}/><Fact label="原设备名称" value={f.equipment_label}/><Fact label="模穴" value={f.cavity}/><Fact label="实际观察时间" value={f.observed_at}/>
          <Fact label="原时区" value={f.observed_timezone}/><Fact label="判据下限" value={f.criterion?.lower}/><Fact label="判据上限" value={f.criterion?.upper}/>
        </dl><p>测试记录第 {f.run_revision} 版 · 样件第 {f.sample_revision} 版 · 实际配置第 {f.configuration_revision} 版</p>
        <SourceReading label="原值出处" source={f.source} host={host}/><SourceReading label="固定方法依据" source={f.method} host={host}/>
        {record(f.criterion?.source) && <SourceReading label="固定判据依据" source={f.criterion.source} host={host}/>}
        <details className="text-xs text-muted-foreground"><summary className="cursor-pointer py-2">查看固定失败对应</summary><p>失败：{f.identity}</p><p>样件：{f.sample_id} · 测试项：{f.item_id}</p></details>
      </article>)}</section>
    <section className="space-y-3"><h4 className="font-medium">已具名根因与实际完成的整改</h4><p>{r.root_cause}</p><p className="subtle">根因具名保存记录：{r.root_cause_at}</p>
      {r.actions.map((a, index) => <article key={a.id} className={`space-y-2 rounded-lg border p-3 text-sm ${wrap}`}><p className="font-medium">措施 {index + 1} · {a.kind === "corrective" ? "纠正" : "预防"}</p>
        <p>{a.text}</p><p>实际完成说明：{a.completed_text}</p><p>实际发生：<span className="font-mono">{a.occurred_at}</span> · 原时区 {a.original_timezone}</p>
        <details className="text-xs text-muted-foreground"><summary className="cursor-pointer py-2">完成记录对账</summary><p>措施：{a.id}</p><p>具名执行人标识：{a.executor_id}（姓名尚未提供）</p></details></article>)}</section>
    <section className="space-y-2"><h4 className="font-medium">本次固定整改回链</h4>{!r.links.length && <p>未选整改回链，保留该缺项，不推定整改已履行。</p>}
      {r.links.map(link => <article key={link.ref.id} className="space-y-1 rounded-lg border p-3 text-sm"><p>{link.label || "固定回链，名称未提供"} · 第 {link.ref.revision} 版</p><p>{link.detail || "具体说明未提供"}</p></article>)}</section>
    <section className="space-y-2"><h4 className="font-medium">本次原失败与新复验对应</h4>{!r.mappings.length && <p>未提供可完整核对的新测试配对；本候选不补测量值、工况、测试或通过结果。</p>}
      {r.mappings.map(choice => <article key={JSON.stringify([choice.mapping.failure_id, choice.mapping.run.id, choice.mapping.sample_id, choice.mapping.item_id])} className={`space-y-2 rounded-lg border p-3 text-sm ${wrap}`}>
        <p>{choice.label || "固定复验对应，名称未提供"}</p><p>{choice.detail}</p><p>原值：{choice.original_value ?? empty} · 工况：{choice.conditions ?? empty}</p>
        <p>原时钟：{choice.occurred_at ?? empty} · 原时区：{choice.original_timezone ?? empty}</p>
        <p>测试第 {choice.mapping.run.revision} 版 · 样件第 {choice.mapping.sample_revision} 版 · 实际配置第 {choice.mapping.actual_configuration_revision} 版</p>
      </article>)}
      {r.output_readings.map((output, index) => <p key={index} className="text-sm">固定复验读取：{typeof output.title === "string" ? output.title : "名称未提供"} · {typeof output.meaning === "string" ? meanings[output.meaning] ?? "含义待核对" : "含义待核对"}。当前配对读取不等于已具名有效。</p>)}
    </section>
    <section className="space-y-2"><h4 className="font-medium">独立验证要求与当前专业政策</h4><p>验证方法：{r.requirement.method}</p><p>验收要求：{r.requirement.acceptance}</p><p>要求观察至：{r.requirement.observation_until}</p>
      <p>政策第 {r.policy_revision} 版 · 风险 {risks[r.risk]} · {r.independent_verification ? "要求独立验证" : "政策未要求独立验证（候选自身仍未知）"}</p>
      <p>{r.policy_valid_until ? `政策有效至：${r.policy_valid_until}` : "当前政策及各项适用时间已核对"}</p><p>本操作专业准入：{r.roles.length ? r.roles.map(role => roles[role] ?? "职责名称未提供").join("、") : "职责名称未提供"}{r.authority_valid_until ? ` · 有效至 ${r.authority_valid_until}` : " · 当前职责与资格已核对"}</p>
      <p>本次保存不包含具名复核、有效性决定或问题关闭。</p></section>
    <section className="space-y-2"><h4 className="font-medium">本次精确原文出处</h4>{!r.sources.length && <p>未额外选择候选出处；原失败与整改的固定来源仍保留在完整读集中。</p>}
      {r.sources.map((source, index) => <blockquote key={index} className={`space-y-2 rounded-lg border p-3 text-sm ${wrap}`}><p>{source.title || "固定来源，标题未提供"} · 第 {source.reference.expected_revision} 版 · 第 {source.reference.line} 行</p><p className="whitespace-pre-wrap">{source.reference.quote}</p></blockquote>)}
      <details className="text-xs text-muted-foreground"><summary className="cursor-pointer py-2">完整固定来源对账（{reads.length} 份）</summary>
        {reads.map(ref => <p key={ref.artifact_id}>{host.materials.sources.find(source => source.reference.artifact_id === ref.artifact_id)?.title || "固定来源，标题未提供"} · 第 {ref.expected_revision} 版 · {ref.artifact_id}</p>)}</details></section>
    <section className="space-y-2 rounded-lg border border-primary p-3"><h4 className="font-medium">待独立核对的缺项与保存后果</h4>
      <p>适用性未知 · 独立核验未知 · 观察完整性未知 · 综合仍待核对</p>
      {r.missing.length ? <ul className="list-disc space-y-2 pl-5 text-sm">{r.missing.map((gap, index) => <li key={`${gap.code}:${index}`}>{gap.detail}</li>)}</ul> : <p>服务器未列额外缺项；三项专业判断仍保持未知。</p>}
      <p className="text-sm">只保存本次固定候选与原失败对应，不覆盖历史、原值或原时钟，不决定措施有效，不关闭问题，也不放行成品。</p></section>
  </div>;
}
function Fact({ label, value }: { label: string; value: unknown }) { return <div className={wrap}><dt className="text-muted-foreground">{label}</dt><dd>{typeof value === "string" || typeof value === "number" ? value : empty}</dd></div>; }
function SourceReading({ label, source, host }: { label: string; source: Record<string, unknown>; host: CandidateHost }) {
  const match = typeof source.position === "string" ? /^line:([1-9]\d*);quote_sha256:[0-9a-f]{64}$/.exec(source.position) : null;
  const choices = match && source.kind === "artifact" ? host.materials.sources.filter(choice => choice.reference.artifact_id === source.id &&
    choice.reference.expected_revision === source.revision && choice.reference.line === Number(match[1])) : [];
  return <div className="space-y-1 text-sm"><p>{label}：{source.kind === "command" ? "固定历史办理回执" : choices[0]?.title || "固定来源，标题未提供"} · 第 {typeof source.revision === "number" ? source.revision : "未知"} 版{match ? ` · 第 ${match[1]} 行` : ""}</p>
    {choices.length === 1 && source.kind === "artifact" ? <p className={`whitespace-pre-wrap text-muted-foreground ${wrap}`}>{choices[0].reference.quote}</p> :
      <p className="subtle">原文未在当前可选资料中单独提供，固定引用保留；不替换为新的出处。</p>}
    <details className="text-xs text-muted-foreground"><summary className="cursor-pointer py-2">出处对账</summary><p className={wrap}>{typeof source.id === "string" ? source.id : "标识未提供"}</p>
      {record(source) && typeof source.position === "string" && source.kind !== "artifact" && <p>固定回执定位已保留</p>}</details></div>;
}
