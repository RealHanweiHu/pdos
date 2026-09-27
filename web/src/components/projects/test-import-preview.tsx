"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import { SampleConfigurationSnapshot } from "./sample-configuration-snapshot";
import { TestExecutionTimeInput } from "./test-execution-time-input";
import { TestImportSampleResolver } from "./test-import-sample-resolver";
import { TestImportMappingEditor, TestImportComparison } from "./test-import-mapping-editor";

const mappingLabels: Record<string, string> = { case_title_column: "用例名称列", sample_serial_column: "样机编号列", result_column: "结果列", notes_column: "备注列", pcb_version_column: "PCB版本列", structure_version_column: "结构版本列", fw_version_column: "固件版本列", build_date_column: "装机日期列", pass_values: "通过原值", fail_values: "失败原值", unmapped_headers: "未映射列" };
const skipLabels: Record<string, string> = { unsupported_sheet_layout: "工作表格式尚不支持", different_flat_headers: "列名与当前表格不同", missing_case_title: "缺少用例名称", non_decisive_result: "没有可判定测试结果", ambiguous_result_mapping: "通过与失败映射有冲突", missing_test_date: "缺少实际测试日期", missing_observations: "缺少实测记录", unknown_result_value: "测试结果值尚未映射", template_not_applicable: "模板已标不适用", unknown_test_case: "未找到计划内用例", test_case_waived: "用例已豁免" };
const statuses: Record<string, string> = { parsed: "待确认", confirmed: "已确认", failed: "失败", passed: "通过", draft: "草稿", waived: "已豁免" };
function row(v: unknown) { if (!isRecord(v)) throw new Error("报告预览不完整"); return v; }
function rows(v: unknown) { if (!Array.isArray(v)) throw new Error("报告明细不完整"); return v.map(row); }
function text(v: unknown): string { return v === null || v === undefined || v === "" ? "未记录" : typeof v === "object" ? JSON.stringify(v) : String(v); }
export async function importRequest(path: string, body?: object): Promise<unknown> {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "报告办理未完成，请刷新原回执");
  return value;
}
const reviewLabels: Record<string, string> = { ready: "确认条件已具备", needs_attention: "待补充", confirmed: "已整批确认", superseded: "原版留存", unavailable: "暂不可确认", unknown: "请刷新核对状态" };
type ReviewFilter = "all" | "needs_attention" | "ready";
function parse(v: unknown) {
  const value = row(v);
  return {
    batch: row(value.batch), plan: row(value.plan), document: row(value.document),
    mapping: isRecord(value.mapping) ? value.mapping : null,
    mappingReview: isRecord(value.mapping_review) ? value.mapping_review : null,
    items: rows(value.items).map(item => ({
      reviewState: typeof item.review_state === "string" ? item.review_state : "unknown",
      reviewReasons: Array.isArray(item.review_reasons) ? item.review_reasons.map(String) : [],
      href: text(item.href), execution_time_precision: text(item.execution_time_precision),
      configuration_from_this_report: item.configuration_from_this_report === true,
      revision: item.configuration_revision,
      reportedSerial: typeof item.report_sample_serial === "string" ? item.report_sample_serial : "",
      buildHints: Array.isArray(item.report_build_hints) ? item.report_build_hints.filter(isRecord) : [],
      build: isRecord(item.build) ? item.build : null,
      sampleResolution: isRecord(item.sample_resolution) ? item.sample_resolution : null,
      timeRecorder: typeof item.execution_time_recorded_by_name === "string" ? item.execution_time_recorded_by_name : null,
      run: row(item.run), case: isRecord(item.case) ? item.case : null,
      sample: isRecord(item.sample) ? item.sample : null, source: row(item.source),
      config: isRecord(item.current_sample_configuration) ? item.current_sample_configuration : null,
    })),
    skipped: rows(value.skipped_rows),
    blockers: Array.isArray(value.blockers) ? value.blockers.map(String) : [],
    batchBlockers: Array.isArray(value.batch_blockers) ? value.batch_blockers.map(String) : null,
    canResolveSamples: value.can_resolve_samples === true, canReparse: value.can_reparse === true,
    canAmendTimes: value.can_amend_execution_times === true, canConfirm: value.can_confirm === true,
    digest: String(value.digest),
    reviser: typeof value.mapping_revised_by_name === "string" ? value.mapping_revised_by_name : null,
    confirmer: typeof value.confirmed_by_name === "string" ? value.confirmed_by_name : null,
  };
}
type Preview = ReturnType<typeof parse>;
function MappingProvenance({ preview }: { preview: Preview }) {
  const review = preview.mappingReview;
  const confidence = review?.model_mapping_confidence;
  const source = review?.source ?? preview.batch.mapping_source;
  const label = source === "human" ? "人工修订列映射"
    : source === "model" ? "AI 建议列映射"
    : preview.batch.workbook_layout === "test_form_v1" ? "固定报告表单"
    : preview.batch.mapping_version_id ? "已确认映射模板" : "历史映射来源";
  return <div className="space-y-1 text-xs">
    <p className="font-medium">{label}{typeof review?.version === "number" ? ` · 模板 v${review.version}` : ""}</p>
    <p className="text-muted-foreground">{source === "model" && typeof confidence === "number" && Number.isFinite(confidence) && confidence >= 0 && confidence <= 1
      ? `模型对整表列映射的自评分：${Math.round(confidence * 100)}%。该评分不代表逐行结果准确率。`
      : source === "human" ? "本版映射由人工修订，没有模型置信评分。"
      : source === "mapping" ? "按固定表单或已确认模板提取，本次没有模型置信评分。"
      : "未保存可核对的模型列映射评分。"}
      逐行置信度尚未评估；确认条件按真实日期、样机及原记录状态核对，测试结果仍需对照原值。</p>
    <details><summary className="cursor-pointer text-muted-foreground">查看原文件与解析版本</summary><dl className="mt-2 space-y-1 break-all text-muted-foreground"><div><dt className="inline">原文件校验值：</dt><dd className="inline font-mono">{text(preview.document.sha256)}</dd></div><div><dt className="inline">解析版本：</dt><dd className="inline">{text(preview.batch.parser_version)}</dd></div><div><dt className="inline">映射版本编号：</dt><dd className="inline font-mono">{preview.batch.mapping_version_id ? text(preview.batch.mapping_version_id) : "本批原始映射快照"}</dd></div></dl></details>
  </div>;
}
function ReportBuildHints({ hints, build }: { hints: Record<string, unknown>[]; build: Record<string, unknown> | null }) {
  const codes = [...new Set(hints.map(h => text(h.code)).filter(c => c !== "未记录"))];
  return <div className="space-y-1 text-xs">
    {hints.length === 0 && <p className="text-muted-foreground">报告批次：未提供明确栏位或旧版未提取。</p>}
    {hints.map((hint, i) => { const matches = Array.isArray(hint.matches) ? hint.matches.filter(isRecord) : []; return <p key={i}>报告批次原值：{text(hint.raw_value)}（{text(hint.label)} · {text(hint.cell)}） · {matches.length === 0 ? "未匹配当前项目批次" : matches.length > 1 ? "同编号对应多个阶段，请核对真实批次" : `项目批次 ${text(matches[0].code)} · ${text(matches[0].phase).toUpperCase()}`}</p>; })}
    {codes.length > 1 && <p className="text-destructive">原文有多个不同批次编号，请核对各栏位含义及样机归属。</p>}
    {build && codes.some(code => code !== build.code) && <p className="text-destructive">报告批次原值与已绑定样机所属批次不一致，请核对来源及实际样机。</p>}
  </div>;
}
function commonBuildCode(items: Preview["items"], selected: string[]): string {
  const selectedItems = items.filter(item => selected.includes(String(item.run.id)));
  const codes = selectedItems.map(item => [...new Set(item.buildHints.map(h => typeof h.code === "string" ? h.code : "").filter(Boolean))]);
  return codes.length > 0 && codes.every(values => values.length === 1 && values[0] === codes[0][0]) ? codes[0][0] : "";
}
function SourceValues({ source }: { source: Record<string, unknown> }) {
  const cells = isRecord(source.cells) ? Object.entries(source.cells) : [];
  const records = Array.isArray(source.records) ? source.records.filter(isRecord) : [];
  return <div className="space-y-2 text-xs"><p>{text(source.sheet)} · 第{text(source.row)}行{source.result_cell ? ` · 结果 ${text(source.result_cell)}` : ""}</p>
    {source.reported_result !== undefined && <p>报告结论：{text(source.reported_result)} · 报告日期：{text(source.reported_date)}</p>}
    {Boolean(source.standard) && <p>原判定标准：{text(source.standard)}</p>}{Boolean(source.method) && <p>原方法：{text(source.method)}</p>}{Boolean(source.equipment) && <p>原设备：{text(source.equipment)}</p>}
    {cells.length > 0 && <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr><th>原单元格</th><th>原值</th></tr></thead><tbody>{cells.map(([key, value]) => <tr key={key} className="border-t"><td className="p-1 font-mono">{key}</td><td className="whitespace-pre-wrap p-1">{text(value)}</td></tr>)}</tbody></table></div>}
    {records.length > 0 && <details><summary className="cursor-pointer">展开原实测记录</summary>{records.map((record, i) => <div key={i} className="mt-2 border-t pt-2">第{text(record.row)}行：{isRecord(record.cells) && Object.entries(record.cells).map(([cell, value]) => <p key={cell}>{cell}：{text(value)}</p>)}</div>)}</details>}
    {!cells.length && !records.length && <p className="text-muted-foreground">此记录只保留了原行位置；请结合原报告核对，未补造历史单元格内容。</p>}
  </div>;
}
export function TestImportPreview({ projectId, batchId, onConfirmed }: { projectId: string; batchId: string; onConfirmed?: () => Promise<void> }) {
  const [activeBatchId, setActiveBatchId] = useState(batchId);
  const [preview, setPreview] = useState<Preview | null>(null), [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null), [acknowledged, setAcknowledged] = useState(false);
  const [page, setPage] = useState(0);
  const [filter, setFilter] = useState<ReviewFilter>("all");
  const [selectedSamples, setSelectedSamples] = useState<string[]>([]);
  const [selectedTimes, setSelectedTimes] = useState<string[]>([]);
  const base = `/api/projects/${projectId}/npi/test-imports/${activeBatchId}`;
  function display(next: Preview) {
    setPreview(next); setAcknowledged(false); setPage(0); setSelectedTimes([]); setSelectedSamples([]);
    setFilter(next.items.some(item => item.reviewState === "needs_attention") ? "needs_attention" : "all");
  }
  async function load() { display(parse(await importRequest(`${base}/preview`))); }
  async function openBatch(id: string) {
    const next = parse(await importRequest(`/api/projects/${projectId}/npi/test-imports/${id}/preview`));
    setActiveBatchId(id); display(next);
  }
  const attentionCount = preview?.items.filter(item => item.reviewState === "needs_attention").length ?? 0;
  const readyCount = preview?.items.filter(item => item.reviewState === "ready").length ?? 0;
  const filteredItems = preview?.items.filter(item => filter === "all" || item.reviewState === filter) ?? [];
  const batchBlockers = preview?.batchBlockers ?? preview?.blockers ?? [];
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "报告核对未完成"); setAcknowledged(false); } finally { setBusy(false); } }
  return <details className="rounded-lg border bg-card p-3" onToggle={e => { if (e.currentTarget.open && !preview && !busy) void act(load); }}>
    <summary className="cursor-pointer text-sm font-semibold">核对报告原值、目标记录与确认回执</summary>
    <div className="mt-3 space-y-4"><Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>刷新完整预览</Button>
      {preview && <>
        {Boolean(preview.batch.superseded_by_batch_id) && <Button type="button" size="sm" disabled={busy} onClick={() => void act(() => openBatch(String(preview.batch.superseded_by_batch_id)))}>打开后续重解析版本</Button>}
        {Boolean(preview.batch.parent_batch_id) && <><p className="text-xs">当前为映射修订版本。修订人：{preview.reviser ?? "姓名不可用"} · 修订依据：{text(preview.batch.remap_reason)}</p><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => openBatch(String(preview.batch.parent_batch_id)))}>回查修订前原批次</Button><TestImportComparison key={`${activeBatchId}:${preview.digest}`} load={() => importRequest(`${base}/comparison`)} /></>}
        <p className="text-sm">{text(preview.document.filename)} → {text(preview.plan.title)} · {statuses[text(preview.batch.status)] ?? text(preview.batch.status)}</p>
        <a className="text-xs text-primary underline" href={`/projects?project=${projectId}&tab=documents&entity_id=${String(preview.document.id)}`}>查看项目中的报告证据</a>
        <p className="text-xs text-muted-foreground">共{preview.items.length}条测试记录、{preview.skipped.length}处跳过说明。确认只采用本批次已生成的记录；跳过项不会被当作完成。报告日期缺失及历史样机配置未绑定处单独显示。</p>
        <MappingProvenance preview={preview} />
        {preview.mapping ? <details><summary className="cursor-pointer text-xs">核对字段映射及原值判定</summary><dl className="mt-2 grid gap-1 text-xs">{Object.entries(mappingLabels).filter(([key]) => preview.mapping?.[key] !== null && preview.mapping?.[key] !== undefined).map(([key, label]) => <div key={key}><dt className="inline font-medium">{label}：</dt><dd className="inline">{text(preview.mapping?.[key])}</dd></div>)}</dl>{Array.isArray(preview.mapping.metric_columns) && preview.mapping.metric_columns.filter(isRecord).map((metric, i) => <p key={i} className="text-xs">{text(metric.column)} → {text(metric.name)}（{text(metric.unit)}）</p>)}</details> : <p className="text-xs">此批次沿固定表单适配器或历史映射解析，请逐项核对原文与目标值。</p>}
        {preview.canResolveSamples && selectedSamples.length > 0 && <TestImportSampleResolver projectId={projectId} suggestedBuildCode={commonBuildCode(preview.items, selectedSamples)} onBuildCreated={async () => { setPreview(parse(await importRequest(`${base}/preview`))); setAcknowledged(false); await onConfirmed?.(); }} key={selectedSamples.join(",")} runIds={selectedSamples} digest={preview.digest} suggestedSerial={preview.items.find(i => selectedSamples.includes(String(i.run.id)))?.reportedSerial ?? ""} busy={busy} loadOptions={search => importRequest(`${base}/sample-options?search=${encodeURIComponent(search)}`)} onResolve={async body => {
          setBusy(true); setError(null);
          try { const next = parse(await importRequest(`${base}/resolve-samples`, body)); display(next); }
          finally { setBusy(false); }
        }} />}
        {preview.canReparse && <TestImportMappingEditor key={activeBatchId} busy={busy} loadOptions={() => importRequest(`${base}/mapping-options`)} onReparse={async body => {
          setBusy(true); setError(null);
          try { const next = parse(await importRequest(`${base}/reparse`, body)); setActiveBatchId(String(next.batch.id)); display(next); await onConfirmed?.(); }
          finally { setBusy(false); }
        }} />}
        {preview.canAmendTimes && <div className="space-y-3"><Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setSelectedTimes(preview.items.filter(item => item.execution_time_precision === "unknown").slice(0, 100).map(item => String(item.run.id)))}>选中缺实际日期的记录（最多100条）</Button>
          {selectedTimes.length > 0 && <TestExecutionTimeInput runIds={selectedTimes} busy={busy} onSave={async items => {
            setBusy(true); setError(null);
            try { const next = parse(await importRequest(`${base}/execution-times`, { expected_digest: preview.digest, items })); display(next); }
            finally { setBusy(false); }
          }} />}</div>}
        <div className="space-y-3 border-y py-3">
          <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-medium">本批记录 · {preview.items.length} 条</p><span className="text-xs text-muted-foreground">跳过 {preview.skipped.length} 处 · 保留原说明</span></div>
          {preview.batch.status === "parsed" && !preview.batch.superseded_by_batch_id && preview.items.length > 0 && <>
            <p className="text-xs text-muted-foreground">{attentionCount > 0 ? `先处理 ${attentionCount} 条待补充记录；全部具备确认条件后，一次确认本批 ${preview.items.length} 条结果。` : readyCount > 0 ? `${readyCount} 条具备确认条件；可核对原值后整批确认。` : "确认条件尚未核对，请刷新完整预览。"} 通过和失败结果均保留，不因筛选遗漏任何记录。</p>
            <div aria-label="报告记录筛选" className="flex flex-wrap gap-2">{([{ value: "needs_attention", label: `待补充 ${attentionCount}` }, { value: "ready", label: `条件已具备 ${readyCount}` }, { value: "all", label: `全部 ${preview.items.length}` }] as const).map(option => <Button key={option.value} type="button" size="sm" variant={filter === option.value ? "default" : "outline"} aria-pressed={filter === option.value} disabled={busy} onClick={() => { setFilter(option.value); setPage(0); }}>{option.label}</Button>)}</div>
          </>}
          {preview.items.length === 0 && <p className="text-xs text-muted-foreground">本批没有可确认的测试记录，请展开跳过说明核对来源。</p>}
          {preview.items.length > 0 && filteredItems.length === 0 && <p role="status" className="text-xs text-muted-foreground">该分类暂无记录，可切换至“全部”查看原值。</p>}
        </div>
        {filteredItems.slice(page * 20, page * 20 + 20).map(item => <article key={String(item.run.id)} className="space-y-3 rounded-lg border p-3 text-sm">
          <p className={`text-xs font-medium ${item.reviewState === "needs_attention" ? "text-destructive" : "text-muted-foreground"}`}>{reviewLabels[item.reviewState] ?? reviewLabels.unknown}</p>
          {item.reviewReasons.length > 0 && <ul className="list-inside list-disc space-y-1 text-xs text-destructive">{item.reviewReasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul>}
          <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium">{text(item.case?.title)} · 第{text(item.run.run_number)}次 · {statuses[text(item.run.status)] ?? text(item.run.status)}</p><a className="text-xs text-primary underline" href={String(item.href)}>打开实际测试记录</a></div>
          {preview.canResolveSamples && !item.run.sample_id && <div className="flex flex-wrap items-center gap-3"><label className="flex gap-2 text-xs"><input type="checkbox" disabled={busy || (!selectedSamples.includes(String(item.run.id)) && selectedSamples.length >= 100)} checked={selectedSamples.includes(String(item.run.id))} onChange={e => setSelectedSamples(ids => e.target.checked ? [...ids, String(item.run.id)] : ids.filter(id => id !== String(item.run.id)))} />选中本条补齐样机</label>{item.reportedSerial && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setSelectedSamples(preview.items.filter(i => !i.run.sample_id && i.reportedSerial === item.reportedSerial).slice(0, 100).map(i => String(i.run.id)))}>选中同原编号未绑定记录</Button>}</div>}
          {preview.canAmendTimes && <label className="flex items-center gap-2 text-xs"><input type="checkbox" disabled={busy || (!selectedTimes.includes(String(item.run.id)) && selectedTimes.length >= 100)} checked={selectedTimes.includes(String(item.run.id))} onChange={e => setSelectedTimes(ids => e.target.checked ? [...ids, String(item.run.id)] : ids.filter(id => id !== String(item.run.id)))} />选中本条补录或修正实际测试时间</label>}
          <p className="text-xs">报告原样机编号：{item.reportedSerial || "未保留或未提供"} · 所属批次：{text(item.build?.code)}{item.build?.phase ? ` · ${text(item.build.phase).toUpperCase()}` : ""}</p>
          <ReportBuildHints hints={item.buildHints} build={item.build} />
          {item.sampleResolution && <p className="text-xs text-muted-foreground">样机{item.sampleResolution.created_sample ? "新建并绑定" : "复用绑定"}人：{text(item.sampleResolution.resolved_by_name)} · 依据：{text(item.sampleResolution.reason)}</p>}
          <p className="text-xs">样机：{text(item.sample?.serial_number)} · 状态：{statuses[text(item.run.draft_state)] ?? text(item.run.draft_state)}</p>
          <p className="text-xs">{item.execution_time_precision === "day" ? `实际测试日期：${text(item.run.executed_at).slice(0, 10)}（日期精度）` : item.execution_time_precision === "instant" && typeof item.run.executed_at === "string" ? `实际测试时间：${new Date(item.run.executed_at).toLocaleString()}` : "实际测试时间未明确；系统登记时间不代表真实执行时间。"}</p>
          {isRecord(item.run.conditions) && isRecord(item.run.conditions.execution_time_input) && <p className="text-xs text-muted-foreground">补录人：{item.timeRecorder ?? "姓名不可用"} · {text(item.run.conditions.execution_time_input.recorded_at)} · 依据：{text(item.run.conditions.execution_time_input.reason)}</p>}
          {Array.isArray(item.run.metrics) && item.run.metrics.filter(isRecord).map((metric, i) => <p key={i} className="text-xs">{text(metric.name)}：{text(metric.value)} {metric.unit ? text(metric.unit) : ""}</p>)}
          {Boolean(item.run.result_notes) && <p className="whitespace-pre-wrap text-xs">备注：{text(item.run.result_notes)}</p>}
          <div className="grid gap-3 md:grid-cols-2"><div><p className="mb-2 text-xs font-medium">原报告依据</p><SourceValues source={item.source} /></div><div className="space-y-3 text-xs"><SampleConfigurationSnapshot revision={item.revision} /><details><summary className="cursor-pointer">当前样机配置（仅供对比）</summary>{item.config ? <><p>PCB：{text(item.config.pcb_version)}</p><p>结构：{text(item.config.structure_version)}</p><p>装机日期：{text(item.config.build_date)}</p><p>配置状态：{statuses[text(item.config.draft_state)] ?? text(item.config.draft_state)}</p></> : <p>未登记当前配置。</p>}</details></div></div>
          {Boolean(item.case?.related_issue_id) && <a className="text-xs text-primary underline" href={`/projects?project=${projectId}&tab=issues&entity_id=${String(item.case?.related_issue_id)}`}>查看实际关联问题</a>}
        </article>)}
        {filteredItems.length > 20 && <div className="flex items-center gap-3 text-xs"><Button size="sm" variant="outline" disabled={busy || page === 0} onClick={() => setPage(p => p - 1)}>上一页</Button><span>第{page + 1}/{Math.ceil(filteredItems.length / 20)}页</span><Button size="sm" variant="outline" disabled={busy || (page + 1) * 20 >= filteredItems.length} onClick={() => setPage(p => p + 1)}>下一页</Button></div>}
        {preview.skipped.length > 0 && <details><summary className="cursor-pointer text-xs">核对全部跳过说明（{preview.skipped.length}）</summary><ul className="mt-2 space-y-2 text-xs">{preview.skipped.map((skip, i) => <li key={i} className="rounded-md border p-2">{text(skip.sheet)} · 第{text(skip.row)}行：{skipLabels[text(skip.reason)] ?? text(skip.reason)}{skip.value !== undefined && <p>原值：{text(skip.value)}</p>}{isRecord(skip.source) && <SourceValues source={skip.source} />}</li>)}</ul></details>}
        {batchBlockers.length > 0 && <ul className="space-y-1 text-xs text-destructive">{batchBlockers.map((b, i) => <li key={i}>{b}</li>)}</ul>}
        {preview.canConfirm && preview.items.length > 0 && <div className="space-y-3 border-t pt-3"><label className="flex gap-2 text-xs"><input type="checkbox" checked={acknowledged} disabled={busy} onChange={e => setAcknowledged(e.target.checked)} />已核对本批全部原值、映射、目标和跳过项；整批确认共{preview.items.length}条记录进入正式测试结果（包含筛选未展示的记录）。失败项会沿原流程建立或关联问题。</label><Button size="sm" disabled={busy || !acknowledged} onClick={() => void act(async () => { await importRequest(`${base}/confirm`, { expected_digest: preview.digest }); await load(); await onConfirmed?.(); })}>整批确认 {preview.items.length} 条结果</Button></div>}
        {preview.batch.status === "confirmed" && <p role="status" className="text-xs">正式结果已确认。确认人：{preview.confirmer ?? "历史记录未保存姓名"} · 确认时间：{text(preview.batch.confirmed_at)}。重复请求沿用原回执。</p>}
      </>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </div>
  </details>;
}
