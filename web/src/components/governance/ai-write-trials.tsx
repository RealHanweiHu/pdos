"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowClockwiseIcon, ClipboardTextIcon } from "@phosphor-icons/react";
import { isRecord } from "@/components/workspace-api";
import { AiWriteTrialRegistration } from "./ai-write-trial-registration";
import { AiWriteTrialCurrent } from "./ai-write-trial-current";

const base = "/api/ai/governance/write-policy/trials";
const button = "inline-flex min-h-9 items-center justify-center gap-1.5 rounded-md border bg-background px-3 text-xs outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";
const operations: Record<string, string> = { "meeting.minutes.draft": "会议纪要", "meeting.actions.draft": "会议行动项", "meeting.decisions.draft": "会议决策" };
const kinds: Record<string, string> = { real_business: "真实业务", controlled_replay: "受控重放", synthetic: "模拟场景" };
const reasons: Record<string, string> = {
  evaluation_missing: "尚未接入独立真实模型评测", configuration_missing: "试运行配置缺失",
  model_version_unknown: "模型版本尚未核实", cohort_missing: "尚无固定窗口的采集记录",
  cohort_selection_incomplete: "部分原稿来源未能完整核实", followup_window_incomplete: "后续观察时间尚未满足",
  minimum_handled_drafts_not_met: "已办理原稿数量不足", handled_denominator_empty: "尚无已办理原稿",
  trial_not_real_evidence: "当前记录不能作为真实业务资格证据", evaluation_not_real_evidence: "评测来源尚未满足真实调用要求",
  confirmation_below_threshold: "确认比例低于本次门槛", retraction_above_threshold: "撤回比例高于本次门槛",
  trial_binding_mismatch: "原稿与登记版本不一致", evaluation_binding_mismatch: "评测与登记版本不一致",
  evaluation_incomplete: "独立评测尚未完成", evaluation_failed: "独立评测未通过",
  configuration_not_fixed_before_cohort: "配置未在观察窗口前固定", cohort_window_mismatch: "采集窗口与登记时长不一致",
  provider_call_unverified: "模型调用来源尚未核实", context_chain_mismatch: "原始依据链尚未核实",
  original_policy_unverified: "原始写入政策尚未核实", original_result_unverified: "原始运行结果尚未核实",
};
type Protocol = { id: string; project_ids: string[]; evidence_kind: string; binding: { operation_key: string }; window_start: string; window_end: string; created_at: string; reason: string; configuration: { minimum_handled_drafts: number; minimum_followup_seconds: number; minimum_confirmation_basis_points: number; maximum_retraction_basis_points: number; confirmation_basis: string } };
type Receipt = { evaluation?: { outcome: string; completed_at: string }; evaluationPublicationStatus: string; id: string; as_of: string; current_policy_matches: boolean; collection: { raw_total: number; verified_total: number; unverified_total: number; raw_counts: { confirmed: number; edited: number; withdrawn: number; pending: number }; blockers: { reasons: string[] }[] }; qualification: { reasons: string[]; qualification_granted: false } };
type Page<T> = { items: T[]; next_before_id: string | null };
function text(value: unknown): string { if (typeof value !== "string") throw new Error("试运行记录不完整，请重新读取。"); return value; }
function count(value: unknown): number { if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw new Error("试运行统计不完整，请重新读取。"); return value; }
function record(value: unknown): Record<string, unknown> { if (!isRecord(value)) throw new Error("试运行记录不完整，请重新读取。"); return value; }
function strings(value: unknown): string[] { if (!Array.isArray(value)) throw new Error("试运行清单不完整，请重新读取。"); return value.map(text); }
function stamp(value: unknown): string { const result = text(value); if (!Number.isFinite(Date.parse(result))) throw new Error("试运行时间不完整，请重新读取。"); return result; }
function parseProtocol(value: unknown): Protocol {
  const item = record(value), binding = record(item.binding), configuration = record(item.configuration);
  return { id: text(item.id), project_ids: strings(item.project_ids), evidence_kind: text(item.evidence_kind), binding: { operation_key: text(binding.operation_key) }, window_start: stamp(item.window_start), window_end: stamp(item.window_end), created_at: stamp(item.created_at), reason: text(item.reason), configuration: { minimum_handled_drafts: count(configuration.minimum_handled_drafts), minimum_followup_seconds: count(configuration.minimum_followup_seconds), minimum_confirmation_basis_points: count(configuration.minimum_confirmation_basis_points), maximum_retraction_basis_points: count(configuration.maximum_retraction_basis_points), confirmation_basis: text(configuration.confirmation_basis) } };
}
function parseReceipt(value: unknown): Receipt {
  const item = record(value), collection = record(item.collection), counts = record(collection.raw_counts), qualification = record(item.qualification);
  if (typeof item.current_policy_matches !== "boolean" || qualification.qualification_granted !== false || !Array.isArray(collection.blockers)) throw new Error("采集回执不完整，请重新读取。");
  const evaluation = isRecord(item.evaluation) ? { outcome: text(item.evaluation.outcome), completed_at: stamp(item.evaluation.completed_at) } : undefined;
  const evaluationPublicationStatus = isRecord(item.evaluation_publication) ? text(item.evaluation_publication.status) : "not_configured";
  return { evaluation, evaluationPublicationStatus, id: text(item.id), as_of: stamp(item.as_of), current_policy_matches: item.current_policy_matches, collection: { raw_total: count(collection.raw_total), verified_total: count(collection.verified_total), unverified_total: count(collection.unverified_total), raw_counts: { confirmed: count(counts.confirmed), edited: count(counts.edited), withdrawn: count(counts.withdrawn), pending: count(counts.pending) }, blockers: collection.blockers.map(value => ({ reasons: strings(record(value).reasons) })) }, qualification: { reasons: strings(qualification.reasons), qualification_granted: false } };
}
function page<T>(value: unknown, parse: (item: unknown) => T): Page<T> { const result = record(value); if (!Array.isArray(result.items)) throw new Error("历史清单不完整，请重新读取。"); return { items: result.items.map(parse), next_before_id: result.next_before_id === null ? null : text(result.next_before_id) }; }
function merge<T extends { id: string }>(old: T[], incoming: T[]): T[] { return [...old, ...incoming.filter(item => !old.some(prior => prior.id === item.id))]; }
function time(value: string) { return new Date(value).toLocaleString("zh-CN"); }
function percent(value: number) { return `${value / 100}%`; }
class TrialRequestError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}
function accessLost(error: unknown) { return error instanceof TrialRequestError && [401, 403].includes(error.status); }
async function request(path: string, body?: object): Promise<unknown> {
  const response = await fetch(base + path, { method: body ? "POST" : "GET", cache: "no-store", credentials: "same-origin", ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });
  if (!response.ok) {
    const message = response.status === 401 ? "登录已失效，请重新登录。" : response.status === 403 ? "当前账号无权读取或采集此试运行范围。" : response.status === 404 ? "原试运行记录已不可读取。" : response.status === 409 ? "当前范围或观察窗口尚不满足采集条件，请刷新核对。" : "试运行记录暂不可用，请重试。";
    throw new TrialRequestError(message, response.status);
  }
  return response.json();
}
function failureMessage(error: unknown) { return error instanceof TypeError ? "网络连接中断，请重试。" : error instanceof Error ? error.message : "读取未完成，请重试。"; }

function TrialReceipts({ protocol, canManage, pendingId, remember }: { protocol: Protocol; canManage: boolean; pendingId?: string; remember: (requestId: string | null) => void }) {
  const [history, setHistory] = useState<Page<Receipt> | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const generation = useRef(0);
  const path = `/${encodeURIComponent(protocol.id)}/receipts`;
  const windowOpen = now < Date.parse(protocol.window_end);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 30_000); return () => window.clearInterval(timer); }, []);
  useEffect(() => {
    const current = ++generation.current;
    void request(path).then(value => { const parsed = page(value, parseReceipt); if (current === generation.current) { setHistory(parsed); setError(null); } }).catch((error: unknown) => { if (current === generation.current) setError(failureMessage(error)); }).finally(() => { if (current === generation.current) setLoading(false); });
    return () => { generation.current += 1; };
  }, [path]);
  async function load(append = false) {
    const current = ++generation.current;
    setLoading(true); setError(null);
    try { const next = page(await request(path + (append && history?.next_before_id ? `?before_id=${encodeURIComponent(history.next_before_id)}` : "")), parseReceipt); if (current === generation.current) setHistory(old => ({ ...next, items: append && old ? merge(old.items, next.items) : next.items })); }
    catch (error) { if (current === generation.current) { setError(failureMessage(error)); if (accessLost(error)) setHistory(null); } }
    finally { if (current === generation.current) setLoading(false); }
  }
  async function collect() {
    if (saving || !canManage || windowOpen) return;
    const current = ++generation.current;
    const requestId = pendingId ?? crypto.randomUUID();
    let acknowledged = false;
    remember(requestId); setSaving(true); setError(null); setNotice(null);
    try {
      const result = record(await request(path, { request_id: requestId }));
      parseReceipt(result.receipt);
      remember(null); acknowledged = true;
      if (current !== generation.current) return;
      setNotice("本次采集已保存，原回执保持不变。采集不授予自动写入资格。");
      const next = page(await request(path), parseReceipt);
      if (current === generation.current) setHistory(next);
    } catch (error) { if (current === generation.current) { if (accessLost(error)) setHistory(null); setError(`${failureMessage(error)}${!acknowledged ? " 重试采集将沿用原请求，不会重复记账。" : " 可重新读取原回执。"}`); } }
    finally { if (current === generation.current) setSaving(false); }
  }
  return <section aria-label="所选试运行采集回执" aria-busy={loading || saving} className="mt-3 space-y-3 border-t pt-3">
    <div className="flex flex-wrap gap-2"><button type="button" className={button} disabled={loading || saving} onClick={() => void load()}>刷新采集回执</button>{canManage && <button type="button" className={`${button} border-primary/30 text-primary`} disabled={windowOpen || loading || saving} onClick={() => void collect()}>{saving ? "正在采集…" : pendingId ? "重试采集当前记录" : "采集当前记录"}</button>}</div>
    {windowOpen && <p className="text-xs text-muted-foreground">观察窗口尚未结束，结束后可采集当前记录。</p>}
    {notice && <p role="status" className="text-xs text-muted-foreground">{notice}</p>}{error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    {loading && <p role="status" className="text-xs text-muted-foreground">正在读取原采集回执…</p>}
    <AiWriteTrialCurrent key={protocol.id} protocolId={protocol.id} />
    {history?.items.length === 0 && <p className="text-xs text-muted-foreground">尚无采集回执。窗口结束后可保存一次固定观察。</p>}
    {history?.items.map(receipt => {
      const collection = receipt.collection;
      const labels = [...new Set([...receipt.qualification.reasons, ...collection.blockers.flatMap(item => item.reasons)].map(reason => reasons[reason] ?? "部分来源或绑定资料仍待核实"))];
      return <article key={receipt.id} className="rounded-lg border bg-background p-3">
        <h5 className="text-xs font-medium">截至 {time(receipt.as_of)}</h5>
        <p className="mt-2 text-xs leading-5 text-muted-foreground">{receipt.evaluationPublicationStatus === "verified" && receipt.evaluation ? `已关联独立能力评测：${receipt.evaluation.outcome === "passed" ? "通过" : "未通过"}（${time(receipt.evaluation.completed_at)}）。试运行仍须单独达标。` : receipt.evaluationPublicationStatus === "unavailable" ? "该次采集未能核实独立评测原件；原试运行统计保留。" : "该次采集尚未关联独立能力评测原件。"}</p>
        <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">{[["范围内原稿", collection.raw_total], ["来源已核实", collection.verified_total], ["未核实", collection.unverified_total], ["已确认", collection.raw_counts.confirmed], ["人工改动", collection.raw_counts.edited], ["已撤回", collection.raw_counts.withdrawn], ["仍待办理", collection.raw_counts.pending]].map(([label, value]) => <div key={label}><dt className="text-[11px] text-muted-foreground">{label}</dt><dd className="mt-1 font-mono text-base tabular-nums">{value}</dd></div>)}</dl>
        <p className="mt-3 text-[11px] leading-5 text-muted-foreground">每份原稿只计一次；确认、改动和撤回可能属于同一份原稿，不相加。来源核实不等于获得写入资格。</p>
        {!receipt.current_policy_matches && <p className="mt-2 text-xs text-primary">当前政策已与登记版本不同；本回执保留原观察口径。</p>}
        {labels.length > 0 && <ul aria-label="尚待满足的条件" className="mt-2 space-y-1 text-xs text-muted-foreground">{labels.map(label => <li key={label}>· {label}</li>)}</ul>}
      </article>;
    })}
    {history?.next_before_id && <button type="button" className={button} disabled={loading || saving} onClick={() => void load(true)}>更多采集回执</button>}
  </section>;
}

export function AiWriteTrials({ canManage }: { canManage: boolean }) {
  const [registrationOpen, setRegistrationOpen] = useState(false);
  const [registrationPending, setRegistrationPending] = useState(false);
  const [history, setHistory] = useState<Page<Protocol> | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const [pending, setPending] = useState<Record<string, string>>({});
  useEffect(() => {
    const current = ++generation.current;
    void request("").then(value => { const next = page(value, parseProtocol); if (current === generation.current) setHistory(next); }).catch((error: unknown) => { if (current === generation.current) setError(failureMessage(error)); }).finally(() => { if (current === generation.current) setLoading(false); });
    return () => { generation.current += 1; };
  }, []);
  async function load(append = false) {
    const current = ++generation.current;
    setLoading(true); setError(null);
    try { const next = page(await request(append && history?.next_before_id ? `?before_id=${encodeURIComponent(history.next_before_id)}` : ""), parseProtocol); if (current === generation.current) { setHistory(old => ({ ...next, items: append && old ? merge(old.items, next.items) : next.items })); if (!append) setSelected(null); } }
    catch (error) { if (current === generation.current) { setError(failureMessage(error)); if (accessLost(error)) setHistory(null); } }
    finally { if (current === generation.current) setLoading(false); }
  }
  return <section aria-label="固定试运行登记与回执" className="mt-3 rounded-lg border bg-muted/15 p-3">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="flex items-center gap-2 text-sm font-semibold"><ClipboardTextIcon size={17} className="text-primary" aria-hidden="true" />固定试运行与采集回执</h3><p className="mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">按事先登记的项目、窗口和版本回查原稿。采集不授予自动写入资格，也不会自动切换写入方式。</p></div><button type="button" className={button} disabled={loading} onClick={() => void load()}><ArrowClockwiseIcon size={14} aria-hidden="true" />刷新试运行</button></div>
    {canManage && <div className="mt-3"><button type="button" aria-expanded={registrationOpen} disabled={registrationPending} className={button} onClick={() => setRegistrationOpen(!registrationOpen)}>{registrationOpen ? "收起登记表单" : "登记试运行"}</button>{registrationOpen && <AiWriteTrialRegistration onPendingChange={setRegistrationPending} onRegistered={() => { setRegistrationOpen(false); void load(); }} />}</div>}
    {error && <p role="alert" className="mt-3 text-xs text-destructive">{error}</p>}{loading && <p role="status" className="mt-3 text-xs text-muted-foreground">正在读取固定试运行…</p>}
    {history?.items.length === 0 && <p className="py-5 text-center text-xs text-muted-foreground">尚无已登记的固定试运行。管理员可选择已发布的评测版本进行登记。</p>}
    <div className="mt-3 space-y-3">{history?.items.map(protocol => <article key={protocol.id} className="min-w-0 rounded-lg border bg-card p-3">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h4 className="text-sm font-medium">{operations[protocol.binding.operation_key] ?? "会议草稿"} <span className="ml-1 text-xs font-normal text-muted-foreground">{kinds[protocol.evidence_kind] ?? "来源待核实"} · {protocol.project_ids.length} 个项目</span></h4><p className="mt-1 text-[11px] text-muted-foreground">登记于 {time(protocol.created_at)}</p></div><button type="button" aria-expanded={selected === protocol.id} className={button} onClick={() => setSelected(selected === protocol.id ? null : protocol.id)}>{selected === protocol.id ? "收起采集回执" : "查看采集回执"}</button></div>
      <p className="mt-3 break-words text-xs leading-5">{protocol.reason}</p><p className="mt-2 text-xs leading-5 text-muted-foreground">观察窗口：{time(protocol.window_start)} — {time(protocol.window_end)}</p>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">至少办理 {protocol.configuration.minimum_handled_drafts} 份；确认比例 ≥ {percent(protocol.configuration.minimum_confirmation_basis_points)}，撤回比例 ≤ {percent(protocol.configuration.maximum_retraction_basis_points)}。确认口径：{protocol.configuration.confirmation_basis === "retained_original" ? "确认后未修改、未撤回" : "曾确认采用"}；后续观察至少 {protocol.configuration.minimum_followup_seconds} 秒。</p>
      {selected === protocol.id && <TrialReceipts key={protocol.id} protocol={protocol} canManage={canManage} pendingId={pending[protocol.id]} remember={requestId => setPending(old => { const next = { ...old }; if (requestId) next[protocol.id] = requestId; else delete next[protocol.id]; return next; })} />}
    </article>)}</div>
    {history?.next_before_id && <button type="button" className={`${button} mt-3`} disabled={loading} onClick={() => void load(true)}>更多试运行登记</button>}
  </section>;
}
