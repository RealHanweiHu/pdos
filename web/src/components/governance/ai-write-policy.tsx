"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowClockwiseIcon, CaretDownIcon, ClockCounterClockwiseIcon, RobotIcon } from "@phosphor-icons/react";

import { cn } from "@/lib/utils";
import { AiWriteObservations } from "./ai-write-observations";
import { AiWriteTrials } from "./ai-write-trials";

type Mode = "disabled" | "confirm" | "automatic";
type Setting = {
  mode: Mode;
  minimum_confirmation_basis_points: number;
  maximum_retraction_basis_points: number;
};
type Operation = {
  key: string; label: string; write_tier: "t0" | "t1" | "t2";
  effect: string; blockers: string[];
};
type Policy = {
  revision: number; mode: "legacy" | "tiered"; principal_id: string | null;
  principal_name: string; operation_settings: Record<string, Setting>;
  operations: Operation[]; notice: string;
};
type HistoryItem = {
  revision: number; mode: Policy["mode"]; actor_name: string; actor_user_id: string;
  reason: string; created_at: string; operation_settings: Record<string, Setting>;
};
type History = { items: HistoryItem[]; next_before_revision: number | null };
type SaveResult = { policy: Policy; receipt: { revision: number; replayed: boolean } };
const modeLabels: Record<Mode, string> = {
  disabled: "关闭", confirm: "逐次确认", automatic: "资格通过后自动",
};
const tierLabels = { t0: "可撤回写入", t1: "整批确认", t2: "人工裁决" };
const fieldClass = "h-8 rounded-md border bg-background px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";

class PolicyError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}
async function request<T>(path = "", body?: string): Promise<T> {
  const response = await fetch(`/api/ai/governance/write-policy${path}`, {
    method: body ? "POST" : "GET", credentials: "same-origin", cache: "no-store",
    ...(body ? { headers: { "Content-Type": "application/json" }, body } : {}),
  });
  if (!response.ok) {
    // Keep infrastructure messages out of the workspace, but preserve actionable conflicts.
    const payload = await response.json().catch(() => null);
    const fallback = response.status === 401 ? "登录已失效，请重新登录。"
      : response.status === 403 ? "当前账号无权查看或修改写入政策。"
      : response.status === 409 ? "设置已更新，请重新加载后核对。" : "写入政策暂不可用，请稍后重试。";
    throw new PolicyError(response.status === 409 ? payload?.detail?.message ?? fallback : fallback, response.status);
  }
  return await response.json() as T;
}

export function AiWritePolicy() {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [mode, setMode] = useState<Policy["mode"]>("legacy");
  const [settings, setSettings] = useState<Record<string, Setting>>({});
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [observationsOpen, setObservationsOpen] = useState(false);
  const [trialsOpen, setTrialsOpen] = useState(false);
  const [history, setHistory] = useState<History | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const requestBody = useRef<string | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const generation = useRef(0);

  function adopt(next: Policy) {
    setPolicy(next); setMode(next.mode); setSettings(next.operation_settings);
    setReason(""); setConflict(false); setUncertain(false); requestBody.current = null;
  }
  async function reload() {
    const current = ++generation.current;
    setLoading(true); setError(null); setNotice(null);
    try {
      const next = await request<Policy>();
      if (current !== generation.current) return;
      adopt(next); setHistory(null); setHistoryOpen(false); setHistoryLoading(false); setHistoryError(null);
    } catch (failure) {
      if (current !== generation.current) return;
      setError(failure instanceof Error ? failure.message : "加载失败，请重试。");
      if (failure instanceof PolicyError && [401, 403].includes(failure.status)) {
        setPolicy(null); setHistory(null);
      }
    } finally { if (current === generation.current) setLoading(false); }
  }
  useEffect(() => {
    const current = ++generation.current;
    void request<Policy>().then((next) => {
      if (current !== generation.current) return;
      setPolicy(next); setMode(next.mode); setSettings(next.operation_settings); setLoading(false);
    }).catch((failure: unknown) => {
      if (current !== generation.current) return;
      setError(failure instanceof Error ? failure.message : "加载失败，请重试。"); setLoading(false);
    });
    return () => { generation.current += 1; };
  }, []);

  async function save() {
    if (!policy || saving) return;
    setSaving(true); setError(null); setNotice(null);
    const current = ++generation.current;
    setHistoryLoading(false);
    requestBody.current ??= JSON.stringify({
      request_id: crypto.randomUUID(), expected_revision: policy.revision,
      mode, operation_settings: settings, reason: reason.trim(),
    });
    try {
      const result = await request<SaveResult>("", requestBody.current);
      if (current !== generation.current) return;
      // Keep the same id until the entire response has been received.
      adopt(result.policy); setHistory(null); setHistoryOpen(false);
      setNotice(`${result.receipt.replayed ? "已找回" : "已保存"}第 ${result.receipt.revision} 版设置。当前使用第 ${result.policy.revision} 版；各操作的生效条件见下方。`);
    } catch (failure) {
      if (current !== generation.current) return;
      setError(failure instanceof Error ? failure.message : "保存结果未确认，请重试原请求。");
      if (failure instanceof PolicyError && failure.status < 500) {
        requestBody.current = null;
        setConflict(failure.status === 409); setUncertain(false);
        if ([401, 403].includes(failure.status)) { setPolicy(null); setHistory(null); }
      } else { setUncertain(true); }
    } finally { if (current === generation.current) setSaving(false); }
  }
  async function loadHistory(append = false) {
    if (historyLoading) return;
    const current = generation.current;
    setHistoryLoading(true); setHistoryError(null);
    try {
      const suffix = append && history?.next_before_revision ? `?before_revision=${history.next_before_revision}` : "";
      const next = await request<History>(`/history${suffix}`);
      if (current === generation.current) {
        setHistory((old) => ({ ...next, items: append && old ? [...old.items, ...next.items] : next.items }));
      }
    } catch (failure) {
      if (current === generation.current) {
        setHistoryError(failure instanceof Error ? failure.message : "历史暂不可用。");
        if (failure instanceof PolicyError && [401, 403].includes(failure.status)) { setPolicy(null); setHistory(null); }
      }
    } finally { if (current === generation.current) setHistoryLoading(false); }
  }
  const locked = loading || saving || uncertain || conflict;
  const dirty = policy !== null && (mode !== policy.mode || JSON.stringify(settings) !== JSON.stringify(policy.operation_settings));

  return (
    <section aria-label="AI 写入政策" aria-busy={loading || saving} className="mt-5 overflow-hidden rounded-lg border bg-card">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div className="flex items-start gap-2.5">
          <span className="mt-0.5 rounded-md bg-primary/10 p-1.5 text-primary"><RobotIcon size={18} aria-hidden="true" /></span>
          <div><h2 className="text-sm font-semibold">AI 写入政策</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">让 AI 完成可撤回的工作，让人处理例外与正式裁决。</p>
          </div>
        </div>
        <button type="button" onClick={() => void reload()} disabled={loading || saving || uncertain} className={cn(fieldClass, "flex items-center gap-1.5") }>
          <ArrowClockwiseIcon size={14} aria-hidden="true" />重新加载
        </button>
      </div>
      {error && <p role="alert" className="mx-4 mt-3 text-xs text-destructive">{error}</p>}
      {notice && <p role="status" className="mx-4 mt-3 text-xs text-success">{notice}</p>}
      {loading && !policy && <p className="p-4 text-xs text-muted-foreground">正在读取写入政策…</p>}
      {policy && <>
        <div className="flex flex-wrap items-start justify-between gap-4 px-4 py-4">
          <fieldset disabled={locked} className="min-w-0">
            <legend className="mb-2 text-xs font-medium">租户模式</legend>
            <div className="inline-flex rounded-lg border bg-muted/40 p-0.5">
              {([['legacy', '逐项审核'], ['tiered', '按操作分级']] as const).map(([value, label]) => (
                <label key={value} className={cn("cursor-pointer rounded-md px-3 py-1.5 text-xs transition-colors has-focus-visible:ring-2 has-focus-visible:ring-ring", mode === value ? "bg-background font-medium text-primary shadow-sm" : "text-muted-foreground", locked && "cursor-default opacity-60")}>
                  <input type="radio" name="ai-write-mode" value={value} checked={mode === value} onChange={() => setMode(value)} className="sr-only" />{label}
                </label>
              ))}
            </div>
            <p className="mt-2 max-w-xl text-xs leading-5 text-muted-foreground">{policy.notice}</p>
          </fieldset>
          <div className="text-xs leading-5 text-muted-foreground sm:text-right">
            <p className="font-medium text-foreground">{policy.principal_name} · 独立 AI 身份</p>
            <p>{policy.principal_id ? "已登记 · 不占用员工账号" : "首次保存时登记"}</p>
            <p className="font-mono text-[11px]">{policy.revision ? `当前版本 ${policy.revision}` : "默认设置 · 尚未调整"}</p>
          </div>
        </div>
        <div className="border-y">
          {policy.operations.map((operation) => {
            const setting = settings[operation.key];
            const formal = operation.write_tier === "t2";
            return <div key={operation.key} className="grid gap-3 border-b px-4 py-3 last:border-b-0 lg:grid-cols-[minmax(0,1fr)_13rem]">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-xs font-semibold">{operation.label}</h3>
                  <span className={cn("rounded border px-1.5 py-0.5 text-[10px]", formal ? "border-border text-muted-foreground" : "border-primary/20 bg-primary/5 text-primary")}>{tierLabels[operation.write_tier]}</span>
                </div>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">{operation.effect}</p>
                {!formal && operation.blockers.length > 0 && <p className="mt-1 text-[11px] leading-4 text-muted-foreground">待就绪：{operation.blockers.join("；")}。</p>}
              </div>
              <div className="flex flex-col justify-center gap-1.5">
                {formal ? <p className="text-xs text-muted-foreground">始终由具名人员办理</p> : <>
                  <select aria-label={`${operation.label}使用方式`} value={setting.mode} disabled={locked || mode === "legacy"} className={cn(fieldClass, "w-full")}
                    onChange={(event) => setSettings((previous) => ({ ...previous, [operation.key]: { ...previous[operation.key], mode: event.target.value as Mode } }))}>
                    <option value="disabled">关闭</option>
                    <option value="confirm">{operation.write_tier === "t1" ? "预填后整批确认" : "逐次确认"}</option>
                    {operation.write_tier === "t0" && <option value="automatic">资格通过后自动</option>}
                  </select>
                  {operation.write_tier === "t0" && <span className="text-[10px] text-muted-foreground">确认率 ≥ {setting.minimum_confirmation_basis_points / 100}% · 撤回率 ≤ {setting.maximum_retraction_basis_points / 100}%</span>}
                </>}
              </div>
            </div>;
          })}
        </div>
        <div className="flex flex-wrap items-end gap-3 px-4 py-3">
          <label className="min-w-0 flex-1 basis-64 text-xs font-medium">调整原因
            <input value={reason} onChange={(event) => setReason(event.target.value)} disabled={locked} maxLength={1000} placeholder="说明这次设置调整的原因" className={cn(fieldClass, "mt-1.5 w-full font-normal")} />
          </label>
          <button type="button" onClick={() => void save()} disabled={loading || saving || conflict || (!uncertain && (!dirty || !reason.trim()))}
            className="h-8 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50">
            {saving ? "正在保存…" : uncertain ? "重试原请求" : "保存设置"}
          </button>
          {uncertain && <p className="basis-full text-xs text-muted-foreground">尚未确认保存结果。请重试原请求，系统会找回回执，不会重复修改。</p>}
          {mode === "legacy" && <p className="basis-full text-[11px] text-muted-foreground">逐项审核模式沿用原办理流程；各操作偏好保留，分级写入暂停。</p>}
        </div>
        <div className="border-t px-4 py-3">
          <button type="button" aria-expanded={observationsOpen} onClick={() => setObservationsOpen(!observationsOpen)} className="mb-3 flex items-center gap-1.5 rounded text-xs text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">试运行观察<CaretDownIcon size={12} className={cn("transition-transform", observationsOpen && "rotate-180")} aria-hidden="true" /></button>
          {observationsOpen && <AiWriteObservations />}
          <button type="button" aria-expanded={trialsOpen} onClick={() => setTrialsOpen(!trialsOpen)} className="mb-3 flex items-center gap-1.5 rounded text-xs text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">固定试运行与采集回执<CaretDownIcon size={12} className={cn("transition-transform", trialsOpen && "rotate-180")} aria-hidden="true" /></button>
          {trialsOpen && <AiWriteTrials canManage />}
          <button type="button" aria-expanded={historyOpen} disabled={saving || loading} onClick={() => {
            setHistoryOpen(!historyOpen); if (!historyOpen && !history) void loadHistory();
          }} className="flex items-center gap-1.5 rounded text-xs text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
            <ClockCounterClockwiseIcon size={14} aria-hidden="true" />调整历史<CaretDownIcon size={12} className={cn("transition-transform", historyOpen && "rotate-180")} aria-hidden="true" />
          </button>
          {historyOpen && <div className="mt-3 space-y-2">
            {history?.items.map((item) => <details key={item.revision} className="rounded-md border px-3 py-2 text-xs">
              <summary className="cursor-pointer leading-5"><span className="font-medium">第 {item.revision} 版 · {item.mode === "tiered" ? "按操作分级" : "逐项审核"}</span><span className="ml-2 text-muted-foreground">{item.actor_name} · {new Date(item.created_at).toLocaleString("zh-CN")}</span></summary>
              <p className="mt-2 whitespace-pre-wrap break-words leading-5">{item.reason}</p>
              <dl className="mt-2 grid gap-1 border-t pt-2">
                {policy.operations.filter((operation) => operation.write_tier !== "t2").map((operation) => {
                  const saved = item.operation_settings[operation.key];
                  return <div key={operation.key} className="flex flex-wrap justify-between gap-2 text-muted-foreground"><dt>{operation.label}</dt><dd>{saved ? modeLabels[saved.mode] : "未登记"}</dd></div>;
                })}
              </dl>
            </details>)}
            {history?.items.length === 0 && <p className="text-xs text-muted-foreground">尚无调整记录，当前采用默认设置。</p>}
            {historyError && <p role="alert" className="text-xs text-destructive">{historyError}</p>}
            {(historyError || history?.next_before_revision) && <button type="button" disabled={historyLoading} onClick={() => void loadHistory(Boolean(history))} className={fieldClass}>{historyError ? "重新读取" : "更早记录"}</button>}
            {historyLoading && <p role="status" className="text-xs text-muted-foreground">正在读取历史…</p>}
          </div>}
        </div>
      </>}
    </section>
  );
}
