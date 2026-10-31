"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Paperclip, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { inputSourceReference, readInputSources, readRunSourceBindings } from "@/lib/pai-sources";
import type { PaiInputSource, PaiInputSources, PaiRunSourceBindings, PaiSourcesApi, PaiSourcesScope } from "@/lib/pai-sources";
import styles from "./source-picker.module.css";

export type SelectedSource = { artifact_id: string; expected_revision: number; title: string };
export type SourceSelection = { scope: string; items: SelectedSource[] };
export const sourcePickerScope = (scope: PaiSourcesScope) => JSON.stringify([scope.principalId, scope.categoryId, scope.productId, scope.proposalId]);
const failureMessage = (failure: unknown) => failure instanceof Error ? failure.message : "来源读取暂不可用。";
const unavailableReason = (code: string | null) => ({
  SOURCE_STALE: "固定版本已变化，请刷新后重新选择。", SOURCE_UNAVAILABLE: "来源已撤回或不可继续使用。", FORBIDDEN_SCOPE: "当前范围不可使用该来源。",
  ORIGINAL_SECURITY_BLOCKED: "当前安全扫描或来源状态尚未满足使用要求。", ORIGINAL_SECURITY_UNAVAILABLE: "来源安全记录待核对。",
} as Record<string, string>)[code ?? ""] ?? "当前可用性尚待核对。";
const parseLabel = (status: string) => ({ uploaded: "已上传，尚未解析", parsed: "已登记解析结果", needs_ocr: "需要文字识别", failed: "解析未完成" } as Record<string, string>)[status] ?? "解析状态待核对";
const scanLabel = (status: string) => ({ not_scanned: "尚未扫描", clean: "已记录扫描通过", infected: "检出安全风险", failed: "扫描未完成", scan_failed: "扫描未完成", stale: "扫描依据已变化", unavailable: "扫描记录待核对", blocked: "已阻止使用", quarantined: "已隔离", unknown: "扫描结果待核对", timeout: "扫描超时", rejected: "扫描请求未受理" } as Record<string, string>)[status] ?? "扫描状态待核对";
const statusLabel = (status: string) => ({ active: "有效", withdrawn: "已撤回", archived: "已归档", draft: "草稿" } as Record<string, string>)[status] ?? status;

type PickerProps = { api: PaiSourcesApi; scope: PaiSourcesScope; value: SourceSelection | null; onChange: (value: SourceSelection) => void; disabled?: boolean };
/** Registered sources only. Choosing a source never uploads a file or changes an existing Run. */
export function SourcePicker(props: PickerProps) {
  const [binding, setBinding] = useState({ api: props.api, revision: 0 });
  if (binding.api !== props.api) { setBinding({ api: props.api, revision: binding.revision + 1 }); return null; }
  return <ScopedSourcePicker key={`${binding.revision}:${sourcePickerScope(props.scope)}`} {...props} />;
}

function SourceDetails({ value }: { value: PaiInputSource }) {
  return <details className={styles.details}><summary>登记详情</summary>
    <p>资料状态：{statusLabel(value.status)}</p><p className={styles.identity}>登记来源 {value.artifact_id} · 版本 {value.artifact_revision}</p>
    {value.original ? <><p>原件：{value.original.filename} · 版本 {value.original.revision}</p><p>解析状态：{parseLabel(value.original.parse_status)} · 扫描状态：{scanLabel(value.original.scan_status)}</p><details><summary>原始状态记录</summary><p>解析：{value.original.parse_status} · 扫描：{value.original.scan_status}</p>{value.original.parse_code && <p>解析记录：{value.original.parse_code}</p>}</details><p className={styles.identity}>原件 {value.original.id}</p></> : <p>未提供可读原件信息。</p>}
    {value.availability.code && <p>当前可用性记录：{value.availability.code}</p>}
  </details>;
}

function ScopedSourcePicker({ api, scope, value, onChange, disabled }: PickerProps) {
  const [open, setOpen] = useState(false);
  const [reading, setReading] = useState<PaiInputSources | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0), lock = useRef(false);
  const key = sourcePickerScope(scope);
  const selected = reading && value?.scope === key ? value.items : [];
  useEffect(() => { const counter = generation; return () => { counter.current++; }; }, []);
  async function load(cursor?: string) {
    if (lock.current) return;
    lock.current = true; const own = ++generation.current;
    setLoading(true); setError("");
    if (!cursor) { setReading(null); onChange({ scope: key, items: [] }); }
    try {
      const page = await readInputSources(api, scope, { cursor });
      if (generation.current !== own) return;
      if (cursor && (!reading || reading.next_cursor !== cursor || page.next_cursor === cursor)) throw new Error("来源分页位置已变化，请重新读取。 ");
      setReading(previous => cursor && previous ? { ...page, items: [...previous.items, ...page.items.filter(item => !previous.items.some(prior => prior.artifact_id === item.artifact_id))] } : page);
    } catch (failure) {
      if (generation.current === own) { setReading(null); onChange({ scope: key, items: [] }); setError(failureMessage(failure)); }
    } finally { if (generation.current === own) { lock.current = false; setLoading(false); } }
  }
  function choose(source: PaiInputSource, checked: boolean) {
    if (disabled || loading) return;
    if (!source.availability.available) return;
    const reference = inputSourceReference(source);
    onChange({ scope: key, items: checked ? [...selected.filter(item => item.artifact_id !== source.artifact_id), { ...reference, title: source.title }] : selected.filter(item => item.artifact_id !== source.artifact_id) });
  }
  return <div className={styles.picker}>
    <Button type="button" variant="ghost" size="sm" className={styles.trigger} disabled={disabled} aria-expanded={open} onClick={() => { setOpen(current => !current); if (!open && !reading && !lock.current) void load(); }}><Paperclip size={13} aria-hidden="true" />已登记来源{selected.length > 0 && <span>{selected.length}</span>}</Button>
    {selected.length > 0 && <div className={styles.selected} aria-label="下次新工作固定来源">{selected.map(source => <span className={styles.chip} key={source.artifact_id}>{source.title} · v{source.expected_revision}<button type="button" disabled={disabled} aria-label={`移除来源 ${source.title}`} onClick={() => onChange({ scope: key, items: selected.filter(item => item.artifact_id !== source.artifact_id) })}><X size={11} aria-hidden="true" /></button></span>)}</div>}
    {open && <section className={styles.panel} aria-label="选择已登记来源">
      <div className={styles.heading}><strong>选择已登记来源</strong><Button type="button" variant="ghost" size="sm" disabled={disabled || loading} onClick={() => void load()}>刷新来源</Button></div>
      <p className={styles.hint}>所选资料会限定下次回答的检索范围；可在回答下解除资料条件。</p>
      <p className={styles.hint}>{scope.proposalId ? "为本提案选择当前品类的可读资料；提案自动携带的资料以运行绑定记录为准。" : scope.productId ? "当前品类及关联型号的可读登记资料。" : "当前品类的可读登记资料；关联型号后可选择该型号资料。"}此处不上传新文件。</p>
      {loading && <p role="status">正在读取登记来源…</p>}{error && <p role="alert">{error}</p>}
      <div className={styles.list}>{reading?.items.map(source => <div className={styles.option} key={source.artifact_id}>
        <label className={styles.choice}><input type="checkbox" disabled={disabled || loading || !source.availability.available} checked={selected.some(item => item.artifact_id === source.artifact_id && item.expected_revision === source.artifact_revision)} onChange={event => choose(source, event.target.checked)} /><span><strong>{source.title}</strong><span className={styles.meta}>固定版本 v{source.artifact_revision} · {source.original ? "已登记附件" : "登记资料"} · {source.availability.available ? "可选择" : "当前不可选择"}</span></span></label>
        {!source.availability.available && <p className={styles.hint}>{unavailableReason(source.availability.code)}</p>}
        <SourceDetails value={source} />
      </div>)}</div>
      {reading && !reading.items.length && <p className={styles.hint}>当前范围暂无可读的已登记来源；未生成登记资料的上传不会列在这里。</p>}
      {reading?.next_cursor && <Button type="button" size="sm" variant="outline" disabled={disabled || loading} onClick={() => void load(reading.next_cursor!)}>加载更多来源</Button>}
      {reading && <p className={styles.hint}>已加载 {reading.items.length} 项登记来源</p>}
    </section>}
  </div>;
}

type BindingsProps = { api: PaiSourcesApi; scope: PaiSourcesScope; runId: string; sessionId: string; onUnavailable?: () => void };
export function RunSourceBindings(props: BindingsProps) {
  const [binding, setBinding] = useState({ api: props.api, revision: 0 });
  if (binding.api !== props.api) { setBinding({ api: props.api, revision: binding.revision + 1 }); return null; }
  return <ScopedRunBindings key={`${binding.revision}:${sourcePickerScope(props.scope)}:${props.runId}:${props.sessionId}`} {...props} />;
}
function ScopedRunBindings({ api, scope, runId, sessionId, onUnavailable }: BindingsProps) {
  const [value, setValue] = useState<PaiRunSourceBindings | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const generation = useRef(0);
  const { principalId, categoryId, productId, proposalId } = scope;
  const load = useCallback(async () => {
    const own = ++generation.current;
    setValue(null); setError(""); setLoading(true);
    try {
      const reading = await readRunSourceBindings(api, { principalId, categoryId, productId, proposalId }, runId, sessionId);
      if (generation.current === own) setValue(reading);
    } catch (failure) {
      if (generation.current === own) { setValue(null); setError(failureMessage(failure)); if ((failure as { status?: number }).status !== 503) onUnavailable?.(); }
    } finally { if (generation.current === own) setLoading(false); }
  }, [api, principalId, categoryId, productId, proposalId, runId, sessionId, onUnavailable]);
  useEffect(() => {
    let active = true; const counter = generation;
    void Promise.resolve().then(() => { if (active) return load(); });
    return () => { active = false; counter.current++; };
  }, [load, attempt]);
  return <section className={styles.bindings} aria-label="本次运行绑定来源"><div className={styles.heading}><strong>本次绑定来源{value ? ` · ${value.items.length}` : ""}</strong><Button type="button" size="sm" variant="ghost" disabled={loading} onClick={() => setAttempt(current => current + 1)}>重新核对来源</Button></div>
    {loading && <p role="status">正在核对实际来源绑定…</p>}{error && <p role="alert">{error}</p>}
    {value && <><p className={styles.hint}>以下是本次运行的固定绑定记录，不代表已完成解析或模型执行。</p>{!value.items.length && <p className={styles.hint}>本次运行未绑定登记来源。</p>}
      {value.items.map(source => <div className={styles.bound} key={source.artifact_id}>{source.current ? <><p><strong>{source.current.title}</strong> · 绑定 v{source.expected_revision}{source.current.artifact_revision !== source.expected_revision && <span className={styles.changed}> · 当前 v{source.current.artifact_revision}（名称为当前登记名）</span>}</p><p className={styles.hint}>{source.current.availability.available ? "当前来源可读。" : unavailableReason(source.current.availability.code)}</p><SourceDetails value={source.current} /></> : <><p>固定来源引用 · 绑定 v{source.expected_revision}</p><p className={styles.hint}>当前来源不可读，名称与正文未展示。</p><details className={styles.details}><summary>引用标识</summary><p className={styles.identity}>{source.artifact_id}</p></details></>}</div>)}
    </>}
  </section>;
}
