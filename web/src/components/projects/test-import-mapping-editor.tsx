"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";

const fields = { case_title_column: "用例名称", result_column: "测试结果", sample_serial_column: "样机编号", notes_column: "备注", pcb_version_column: "PCB版本", structure_version_column: "结构版本", fw_version_column: "固件版本", build_date_column: "装机日期" };
type Metric = { column: string; name: string; unit: string };
const input = "mt-1 w-full rounded-md border bg-background p-2 text-xs";
export function TestImportMappingEditor({ loadOptions, onReparse, busy }: { loadOptions: () => Promise<unknown>; onReparse: (body: object) => Promise<void>; busy: boolean }) {
  const [headers, setHeaders] = useState<string[] | null>(null), [mapping, setMapping] = useState<Record<string, string>>({});
  const [metrics, setMetrics] = useState<Metric[]>([]), [passed, setPassed] = useState(""), [failed, setFailed] = useState("");
  const [digest, setDigest] = useState(""), [reason, setReason] = useState(""), [allowed, setAllowed] = useState(false);
  const [loading, setLoading] = useState(false), [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null);
  const request = useRef<{ signature: string; id: string } | null>(null);
  async function load() {
    setLoading(true); setError(null);
    try {
      const options = await loadOptions();
      if (!isRecord(options) || !Array.isArray(options.headers) || typeof options.digest !== "string") throw new Error("原文件映射资料不完整");
      const source = isRecord(options.mapping) ? options.mapping : {};
      setHeaders(options.headers.map(String)); setAllowed(options.can_reparse === true); setDigest(options.digest);
      setNotice(typeof options.notice === "string" ? options.notice : null);
      setMapping(Object.fromEntries(Object.keys(fields).map(key => [key, typeof source[key] === "string" ? source[key] : ""])));
      setMetrics(Array.isArray(source.metric_columns) ? source.metric_columns.filter(isRecord).map(m => ({ column: String(m.column ?? ""), name: String(m.name ?? ""), unit: String(m.unit ?? "") })) : []);
      setPassed(Array.isArray(source.pass_values) ? source.pass_values.join("\n") : ""); setFailed(Array.isArray(source.fail_values) ? source.fail_values.join("\n") : ""); request.current = null;
    } catch (e) { setError(e instanceof Error ? e.message : "原文件暂不可读"); } finally { setLoading(false); }
  }
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && headers === null && !loading) void load(); }}>
    <summary className="cursor-pointer text-sm font-medium">修正列映射并重新解析原报告</summary>
    <div className="mt-3 space-y-3 text-xs"><p>修正只生成新草稿，原批次保留供对照。旧版人工补录的时间不会自动复制到新结果；新版本仍需逐项核对并单独确认。</p>
      {notice && <p>{notice}</p>}{headers && allowed && <><div className="grid gap-3 sm:grid-cols-2">{Object.entries(fields).map(([key, label]) => <label key={key}>{label}对应列<select className={input} value={mapping[key] ?? ""} disabled={busy || loading} onChange={e => setMapping({ ...mapping, [key]: e.target.value })}><option value="">{["case_title_column", "result_column"].includes(key) ? "请选择（必填）" : "未映射"}</option>{headers.map(h => <option key={h} value={h}>{h}</option>)}</select></label>)}</div>
        <div className="grid gap-3 sm:grid-cols-2"><label>表示通过的原值（每行一个）<textarea className={input} value={passed} disabled={busy || loading} onChange={e => setPassed(e.target.value)} maxLength={2560} /></label><label>表示失败的原值（每行一个）<textarea className={input} value={failed} disabled={busy || loading} onChange={e => setFailed(e.target.value)} maxLength={2560} /></label></div>
        <div className="space-y-2"><p className="font-medium">实测指标</p>{metrics.map((metric, index) => <div key={index} className="grid gap-2 sm:grid-cols-4"><label>原列<select className={input} value={metric.column} disabled={busy || loading} onChange={e => setMetrics(metrics.map((m, i) => i === index ? { ...m, column: e.target.value } : m))}><option value="">请选择</option>{headers.map(h => <option key={h} value={h}>{h}</option>)}</select></label><label>指标名称<input className={input} value={metric.name} maxLength={128} disabled={busy || loading} onChange={e => setMetrics(metrics.map((m, i) => i === index ? { ...m, name: e.target.value } : m))} /></label><label>原单位<input className={input} value={metric.unit} maxLength={32} disabled={busy || loading} onChange={e => setMetrics(metrics.map((m, i) => i === index ? { ...m, unit: e.target.value } : m))} /></label><Button type="button" size="sm" variant="outline" disabled={busy || loading} onClick={() => setMetrics(metrics.filter((_, i) => i !== index))}>移除此映射</Button></div>)}<Button type="button" size="sm" variant="outline" disabled={busy || loading || metrics.length >= 50} onClick={() => setMetrics([...metrics, { column: "", name: "", unit: "" }])}>添加指标映射</Button></div>
        <label className="block">修正依据<textarea className={input} value={reason} maxLength={2000} disabled={busy || loading} onChange={e => setReason(e.target.value)} /></label>
        <Button type="button" size="sm" disabled={busy || loading || !reason.trim() || !mapping.case_title_column || !mapping.result_column || !passed.trim() || !failed.trim()} onClick={async () => {
          setLoading(true); setError(null);
          try {
            const value = { expected_digest: digest, reason: reason.trim(), mapping: { ...Object.fromEntries(Object.entries(mapping).map(([key, v]) => [key, v || null])), metric_columns: metrics.map(m => ({ ...m, name: m.name.trim(), unit: m.unit.trim() || null })), pass_values: passed.split("\n").map(s => s.trim()).filter(Boolean), fail_values: failed.split("\n").map(s => s.trim()).filter(Boolean), confidence: 1, unmapped_headers: [] } };
            const signature = JSON.stringify(value);
            if (request.current?.signature !== signature) request.current = { signature, id: crypto.randomUUID() };
            await onReparse({ ...value, request_id: request.current.id });
          } catch (e) { setError(e instanceof Error ? e.message : "重解析未完成，请重试原请求"); } finally { setLoading(false); }
        }}>生成修订草稿并查看差异</Button></>}
      <Button type="button" size="sm" variant="outline" disabled={busy || loading} onClick={() => void load()}>{headers ? "重新读取原映射（清除本地修改）" : "读取原文件映射"}</Button>
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}

const changes: Record<string, string> = { added: "新增", removed: "减少", changed: "改变", unchanged: "相同" };
const labels: Record<string, string> = { case_title: "用例", status: "结果", sample_serial: "样机", metrics: "指标", result_notes: "备注", executed_at: "测试时间", execution_time_precision: "时间精度", execution_time_source: "时间来源", configuration: "当次配置", reason: "跳过原因", value: "原值" };
const valueLabels: Record<string, string> = { passed: "通过", failed: "失败", aborted: "终止", day: "日期", instant: "精确时刻", unknown: "未知", legacy_unknown: "历史来源未知", report: "原报告", human: "人工补录", name: "指标", value: "值", unit: "单位", target: "目标", verdict: "判定", pass: "通过", fail: "失败", info: "仅记录", pcb_version: "PCB", structure_version: "结构", fw_version: "固件", build_date: "装机日期", key_component_suppliers: "关键件供应商", bom_code: "BOM", bom_version: "BOM版本" };
function display(value: unknown, field?: string): string { if (value === null || value === undefined) return "未知"; if (Array.isArray(value)) return value.map(v => display(v)).join("；"); if (isRecord(value)) return Object.entries(value).filter(([key]) => !key.endsWith("_id")).map(([key, v]) => `${valueLabels[key] ?? key}：${display(v, key)}`).join(" · "); return field && ["status", "verdict", "execution_time_precision", "execution_time_source"].includes(field) ? valueLabels[String(value)] ?? String(value) : String(value); }
function Entry({ value }: { value: unknown }) {
  if (!Array.isArray(value) || !value.length) return <p>无对应记录</p>;
  return <div className="space-y-2">{value.filter(isRecord).map((item, i) => <dl key={i} className="space-y-1"><dt className="font-medium">{item.kind === "skipped" ? "跳过" : "测试草稿"}</dt>{Object.entries(labels).filter(([key]) => item[key] !== undefined).map(([key, label]) => <div key={key}><dt className="inline">{label}：</dt><dd className="inline whitespace-pre-wrap break-words">{display(item[key], key)}</dd></div>)}</dl>)}</div>;
}
export function TestImportComparison({ load }: { load: () => Promise<unknown> }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [page, setPage] = useState(0);
  async function refresh() { setBusy(true); setError(null); try { const v = await load(); if (!isRecord(v)) throw new Error("版本对照不完整"); setData(v); setPage(0); } catch (e) { setError(e instanceof Error ? e.message : "版本对照暂不可用"); } finally { setBusy(false); } }
  const items = data && Array.isArray(data.items) ? data.items.filter(isRecord) : [];
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void refresh(); }}><summary className="cursor-pointer text-sm font-medium">逐行对照原批次与本次修订</summary><div className="mt-3 space-y-3 text-xs"><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void refresh()}>刷新差异</Button>{data && <><p>{String(data.notice ?? "")}</p>{isRecord(data.counts) && <p>{Object.entries(data.counts).map(([key, n]) => `${changes[key] ?? key} ${String(n)}`).join(" · ")}</p>}{items.slice(page * 20, (page + 1) * 20).map((item, i) => <article key={i} className="rounded-md border p-2"><p className="mb-2 font-medium">{String(item.source)} · {changes[String(item.change)] ?? String(item.change)}</p><div className="grid gap-3 md:grid-cols-2"><section><p className="mb-1 font-medium">原批次</p><Entry value={item.before} /></section><section><p className="mb-1 font-medium">本次修订</p><Entry value={item.after} /></section></div></article>)}{items.length > 20 && <div className="flex gap-3"><Button size="sm" variant="outline" disabled={busy || page === 0} onClick={() => setPage(p => p - 1)}>上一页</Button><span>{page + 1}/{Math.ceil(items.length / 20)}</span><Button size="sm" variant="outline" disabled={busy || (page + 1) * 20 >= items.length} onClick={() => setPage(p => p + 1)}>下一页</Button></div>}</>}{error && <p role="alert" className="text-destructive">{error}</p>}</div></details>;
}
