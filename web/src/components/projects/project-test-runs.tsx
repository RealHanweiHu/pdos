"use client";

import { useEffect, useRef, useState } from "react";
import { isRecord } from "@/components/workspace-api";
import { TestPreparationSummary } from "./test-execution-preparation";
import { TestRunConfigurationPicker } from "./test-run-configuration-picker";
import { Button } from "@/components/ui/button";
import type { NpiSample } from "./project-npi-types";
import { SampleConfigurationSnapshot } from "./sample-configuration-snapshot";
import { TestRunConfigurationComparison } from "./project-configuration-comparison";
import { TestImportPreview } from "./test-import-preview";

type Metric = { name: string; value: string; unit: string; target: string; verdict: string };
type Run = {
  import_batch_id?: string | null;
  source_field_capture_id?: string | null;
  id: string; run_number: number; status: string; draft_state: string;
  sample_id: string | null; operator_user_id: string | null; operator_name: string | null; related_issue_id: string | null; created_at: string;
  equipment: string | null; environment: string | null;
  conditions: Record<string, unknown>; metrics: Record<string, unknown>[];
  result_notes: string | null; evidence_document_id: string | null;
  expected_completion_at: string | null; executed_at: string | null;
  test_preparation?: unknown;
  execution_time_precision: string; execution_time_source: string; configuration_revision: unknown; import_successor_batch_id: string | null;
};
const labels: Record<string, string> = { in_progress: "进行中", passed: "通过", failed: "失败", aborted: "终止" };
const inputClass = "w-full rounded-md border bg-background p-2 text-sm";

async function json(response: Response) {
  const body = await response.json();
  if (!response.ok) throw new Error(body?.detail?.message ?? "测试记录暂不可用");
  return body;
}

export function ProjectTestRuns({ projectId, testCaseId, canRecord, samples, onChanged }: {
  projectId: string; testCaseId: string; canRecord: boolean; samples: NpiSample[]; onChanged?: () => Promise<void>;
}) {
  const details = useRef<HTMLDetailsElement | null>(null);
  useEffect(() => { const query = new URLSearchParams(window.location.search); if (query.get("test_case_id") === testCaseId && details.current) details.current.open = true; }, [testCaseId]);
  const base = `/api/projects/${projectId}/npi/test-cases/${testCaseId}/runs`;
  const [runs, setRuns] = useState<Run[] | null>(null);
  useEffect(() => { if (!runs) return; const id = new URLSearchParams(window.location.search).get("test_run_id"); if (id && runs.some(run => run.id === id)) document.getElementById(`test-run-${id}`)?.scrollIntoView({ block: "center" }); }, [runs]);
  const [documents, setDocuments] = useState<{ id: string; filename: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [status, setStatus] = useState("in_progress");
  const [sample, setSample] = useState("");
  const [equipment, setEquipment] = useState("");
  const [environment, setEnvironment] = useState("");
  const [conditions, setConditions] = useState("");
  const [notes, setNotes] = useState("");
  const [evidence, setEvidence] = useState("");
  const [due, setDue] = useState("");
  const [executed, setExecuted] = useState(""), [precision, setPrecision] = useState("day"), [factReason, setFactReason] = useState("");
  const [configMode, setConfigMode] = useState("current"), [revisionId, setRevisionId] = useState("");
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const refresh = async () => {
    const [runData, docData] = await Promise.all([
      fetch(base, { cache: "no-store" }).then(json),
      fetch(`/api/projects/${projectId}/documents`, { cache: "no-store" }).then(json),
    ]);
    setRuns(runData.items); setDocuments(docData.items);
  };
  const act = async (work: () => Promise<void>) => {
    setBusy(true); setError(null);
    try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "操作失败"); }
    finally { setBusy(false); }
  };
  const edit = (run: Run | null) => {
    setExecuted(""); setPrecision("day"); setFactReason(""); setConfigMode("current"); setRevisionId("");
    setEditing(run?.id ?? "new"); setStatus(run ? "passed" : "in_progress");
    setSample(run?.sample_id ?? ""); setEquipment(run?.equipment ?? "");
    setEnvironment(run?.environment ?? ""); setConditions(String(run?.conditions.description ?? ""));
    setNotes(run?.result_notes ?? ""); setEvidence(run?.evidence_document_id ?? ""); setDue("");
    setMetrics((run?.metrics ?? []).map((m) => ({ name: String(m.name ?? ""), value: String(m.value ?? ""), unit: String(m.unit ?? ""), target: String(m.target ?? ""), verdict: String(m.verdict ?? "info") })));
  };
  return <details ref={details} className="basis-full rounded-md border p-2" onToggle={(event) => {
    if (event.currentTarget.open && runs === null && !busy) void act(refresh);
  }}>
    <summary className="cursor-pointer text-sm font-medium">逐次测试与证据</summary>
    <div className="mt-3 space-y-3">
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={busy || !!editing} onClick={() => void act(refresh)}>刷新记录</Button>
        {canRecord && <Button size="sm" disabled={busy || !!editing} onClick={() => edit(null)}>新增一次测试</Button>}
      </div>
      {runs?.length === 0 && <p className="text-sm text-muted-foreground">尚无逐次测试记录。</p>}
      {runs?.map((run) => <article id={`test-run-${run.id}`} key={run.id} className="space-y-1 border-t pt-2 text-sm">
        <p className="font-medium">第 {run.run_number} 次 · {labels[run.status] ?? run.status}{run.import_successor_batch_id ? " · 旧导入草稿，已由后续版本替代" : run.draft_state === "draft" ? " · 待确认草稿" : ""}</p>
        <p>样机：{samples.find((s) => s.id === run.sample_id)?.serial_number ?? run.sample_id ?? "未关联"} · 设备：{run.equipment ?? "未记录"} · 环境：{run.environment ?? "未记录"}</p>
        <TestPreparationSummary preparation={run.test_preparation} />
        <SampleConfigurationSnapshot revision={run.configuration_revision} />
        {run.sample_id && <TestRunConfigurationComparison projectId={projectId} runId={run.id} sampleId={run.sample_id} />}
        <p className="text-xs">{run.execution_time_source === "system_completion" && run.executed_at ? `完成登记时间：${new Date(run.executed_at).toLocaleString()}` : run.execution_time_precision === "day" && run.executed_at ? `实际测试日期：${run.executed_at.slice(0, 10)}（日期精度）` : run.execution_time_precision === "instant" && run.executed_at ? `实际测试时间：${new Date(run.executed_at).toLocaleString()}` : "实际测试时间未明确记录"}</p>
        <p className="text-xs">登记人：{run.operator_name ?? run.operator_user_id ?? "历史未保存"} · 登记时间：{new Date(run.created_at).toLocaleString()}</p>
        {isRecord(run.conditions.execution_time_input) && <p className="text-xs">测试时间登记依据：{String(run.conditions.execution_time_input.reason ?? "未记录")}</p>}
        {isRecord(run.conditions.manual_configuration_selection) && <p className="text-xs">当次配置：{{ current: "开始登记时固定当前版本", revision: "人工核对所选历史版本", unknown: "明确未知" }[String(run.conditions.manual_configuration_selection.mode)] ?? "历史选择"} · {String(run.conditions.manual_configuration_selection.reason ?? "沿开始登记时配置")}</p>}
        {run.result_notes && <p>{run.result_notes}</p>}
        {run.expected_completion_at && <p>预计完成：{new Date(run.expected_completion_at).toLocaleString()}</p>}
        {run.metrics.length > 0 && <ul>{run.metrics.map((m, index) => <li key={index}>{String(m.name)}：{String(m.value)} {String(m.unit ?? "")} · 目标 {String(m.target ?? "—")} · {String(m.verdict ?? "info")}</li>)}</ul>}
        {run.evidence_document_id && <a className="block text-xs text-primary underline" href={`/projects?project=${projectId}&tab=documents&entity_id=${run.evidence_document_id}`}>查看证据：{documents.find((doc) => doc.id === run.evidence_document_id)?.filename ?? "历史文档"}</a>}
        {run.source_field_capture_id && <a className="block text-xs text-primary underline" href={`/capture?project=${projectId}&capture=${run.source_field_capture_id}`}>查看现场原件与人工核对记录</a>}
        {run.related_issue_id && <a className="block text-xs text-primary underline" href={`/projects?project=${projectId}&tab=issues&entity_id=${run.related_issue_id}`}>查看用例当前关联问题</a>}
        {run.import_batch_id && <TestImportPreview projectId={projectId} batchId={run.import_batch_id} onConfirmed={async () => { await refresh(); await onChanged?.(); }} />}
        {canRecord && run.status === "in_progress" && run.draft_state !== "draft" && <Button size="sm" variant="outline" disabled={busy || !!editing} onClick={() => edit(run)}>完成本次测试</Button>}
      </article>)}
      {canRecord && editing && <form className="space-y-3 border-t pt-3" onSubmit={(event) => {
        event.preventDefault();
        void act(async () => {
          const executionFact = status === "in_progress" ? {} : {
            executed_at: precision === "day" ? `${executed}T00:00:00Z` : new Date(executed).toISOString(),
            execution_time_precision: precision, execution_time_reason: factReason.trim(),
          };
          const terminal = { status, ...executionFact, result_notes: notes.trim() || null, evidence_document_id: evidence.trim() || null,
            metrics: metrics.map((m) => ({ name: m.name.trim(), value: m.value.trim(), unit: m.unit.trim() || null, target: m.target.trim() || null, verdict: m.verdict })) };
          await json(await fetch(editing === "new" ? base : `${base}/${editing}/complete`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(editing === "new" ? { ...terminal, configuration_mode: configMode,
              configuration_revision_id: configMode === "revision" ? revisionId : null,
              configuration_reason: configMode === "current" ? null : factReason.trim(), sample_id: sample || null, equipment: equipment.trim() || null, environment: environment.trim() || null,
              conditions: conditions.trim() ? { description: conditions.trim() } : {}, expected_completion_at: due ? new Date(due).toISOString() : null } : terminal),
          }));
          setEditing(null); await refresh();
        });
      }}>
        <fieldset disabled={busy} className="space-y-3">
        <p className="text-sm font-medium">{editing === "new" ? "新增一次测试" : "完成本次测试"}</p>
        <label className="block text-sm">结果<select className={inputClass} value={status} onChange={(e) => { setStatus(e.target.value); if (e.target.value !== "in_progress" && configMode === "current") setConfigMode("unknown"); }}>{Object.entries(labels).filter(([key]) => editing === "new" || key !== "in_progress").map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        {editing === "new" && <>
          <label className="block text-sm">样机<select className={inputClass} value={sample} onChange={(e) => { setSample(e.target.value); setRevisionId(""); if (configMode === "revision") setConfigMode("unknown"); }}><option value="">未关联</option>{samples.map((s) => <option key={s.id} value={s.id}>{s.serial_number}</option>)}</select></label>
          <label className="block text-sm">当次样机配置<select className={inputClass} value={configMode} onChange={e => { setConfigMode(e.target.value); setRevisionId(""); }}>
            {status === "in_progress" && <option value="current">开始登记时固定当前已确认配置</option>}<option value="revision" disabled={!sample}>核对并选择已保存版本</option><option value="unknown">配置未知，保留原因</option>
          </select></label>
          {configMode === "revision" && sample && <TestRunConfigurationPicker key={sample} projectId={projectId} sampleId={sample} value={revisionId} busy={busy} onSelect={revision => { setRevisionId(revision?.id ?? ""); if (revision?.source_document_id) setEvidence(revision.source_document_id); }} />}
          <div className="grid gap-2 sm:grid-cols-2"><label className="text-sm">设备<input className={inputClass} value={equipment} onChange={(e) => setEquipment(e.target.value)} /></label><label className="text-sm">环境<input className={inputClass} value={environment} onChange={(e) => setEnvironment(e.target.value)} /></label></div>
          <label className="block text-sm">测试条件<textarea className={inputClass} value={conditions} onChange={(e) => setConditions(e.target.value)} /></label>
          {status === "in_progress" && <label className="block text-sm">预计完成时间<input type="datetime-local" className={inputClass} value={due} onChange={(e) => setDue(e.target.value)} /></label>}
        </>}
        {status !== "in_progress" && <div className="grid gap-2 sm:grid-cols-2">
          <label className="text-sm">测试时间精度<select className={inputClass} value={precision} onChange={e => { setPrecision(e.target.value); setExecuted(""); }}><option value="day">只知道日期</option><option value="instant">准确时间（当前设备时区）</option></select></label>
          <label className="text-sm">实际测试完成{precision === "day" ? "日期" : "时间"}<input required className={inputClass} type={precision === "day" ? "date" : "datetime-local"} value={executed} onChange={e => setExecuted(e.target.value)} /></label>
        </div>}
        {(status !== "in_progress" || (editing === "new" && configMode !== "current")) && <label className="block text-sm">测试时间及配置选择依据<textarea required maxLength={2000} className={inputClass} value={factReason} onChange={e => setFactReason(e.target.value)} placeholder="说明实际测试日期的依据、当时使用的配置版本，或无法还原配置的原因" /></label>}
        {editing !== "new" && <p className="text-xs text-muted-foreground">沿用本次开始登记时已固定的配置；完成结果保存后进入原测试及问题处理流程。</p>}
        <div className="space-y-2"><p className="text-sm">指标</p>{metrics.map((metric, index) => <div key={index} className="grid gap-2 sm:grid-cols-3">{(["name", "value", "unit", "target"] as const).map((key) => <input key={key} aria-label={`${index + 1} ${key}`} placeholder={{ name: "指标名称", value: "实测值", unit: "单位", target: "目标值" }[key]} required={key === "name" || key === "value"} className={inputClass} value={metric[key]} onChange={(e) => setMetrics(metrics.map((m, i) => i === index ? { ...m, [key]: e.target.value } : m))} />)}<select aria-label={`指标 ${index + 1} 判定`} className={inputClass} value={metric.verdict} onChange={(e) => setMetrics(metrics.map((m, i) => i === index ? { ...m, verdict: e.target.value } : m))}><option value="info">仅记录</option><option value="pass">通过</option><option value="fail">失败</option></select><Button type="button" variant="outline" onClick={() => setMetrics(metrics.filter((_, i) => i !== index))}>移除指标</Button></div>)}<Button type="button" size="sm" variant="outline" disabled={metrics.length >= 100} onClick={() => setMetrics([...metrics, { name: "", value: "", unit: "", target: "", verdict: "info" }])}>添加指标</Button></div>
        <label className="block text-sm">结果说明<textarea className={inputClass} value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
        <label className="block text-sm">证据文档<select className={inputClass} value={evidence} onChange={(e) => setEvidence(e.target.value)}><option value="">选择已上传的项目文档</option>{documents.map((doc) => <option key={doc.id} value={doc.id}>{doc.filename}</option>)}</select></label>
        <div className="flex gap-2"><Button size="sm" disabled={busy || (status !== "in_progress" && (!executed || !factReason.trim())) || (editing === "new" && configMode !== "current" && !factReason.trim()) || (editing === "new" && configMode === "revision" && !revisionId)}>保存测试记录</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setEditing(null)}>取消</Button></div>
        </fieldset>
      </form>}
    </div>
  </details>;
}
