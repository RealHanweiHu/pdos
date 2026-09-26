import { isRecord } from "@/components/workspace-api";

type Value = Record<string, unknown>;
const words: Record<string, string> = {
  passed: "通过", failed: "失败", aborted: "中止", in_progress: "执行中", planned: "已计划",
  confirmed: "已确认", draft: "待确认草稿", pass: "通过", fail: "失败", info: "仅记录",
};
const display = (value: unknown): string => value == null || value === "" ? "未记录" : typeof value === "object" ? JSON.stringify(value) : String(value);

export function testEvidenceLabel(value: Value) {
  return `测试第${display(value.run_number)}次 · ${words[String(value.status)] ?? display(value.status)} · ${words[String(value.draft_state)] ?? display(value.draft_state)}`;
}

export function TestEvidenceValue({ value }: { value: Value }) {
  const metrics = Array.isArray(value.metrics) ? value.metrics.filter(isRecord) : [];
  const conditions = isRecord(value.conditions) ? value.conditions : {};
  const source = isRecord(conditions.report_source) ? conditions.report_source : {};
  const cells = isRecord(source.cells) ? Object.entries(source.cells) : [];
  const timeInput = isRecord(conditions.execution_time_input) ? conditions.execution_time_input : {};
  return <div className="space-y-2 rounded-md border p-3 text-xs">
    <p className="font-medium">{testEvidenceLabel(value)}</p>
    <p>实际测试时间：{display(value.executed_at)}{value.execution_time_precision === "day" ? "（日期精度）" : ""}</p>
    <p>设备：{display(value.equipment)} · 环境：{display(value.environment)}</p>
    {metrics.length ? <div className="overflow-x-auto"><table className="w-full text-left"><caption className="mb-1 text-left">原实测指标（保留原判定，不重新推断）</caption><thead><tr>{["指标", "实测值", "单位", "目标", "原判定"].map(title => <th className="p-1" key={title}>{title}</th>)}</tr></thead><tbody>{metrics.map((metric, index) => <tr className="border-t" key={index}><td className="p-1">{display(metric.name)}</td><td className="p-1">{display(metric.value)}</td><td className="p-1">{display(metric.unit)}</td><td className="p-1">{display(metric.target)}</td><td className="p-1">{words[String(metric.verdict)] ?? display(metric.verdict)}</td></tr>)}</tbody></table></div> : <p>未记录结构化实测指标，请核对原报告。</p>}
    {value.result_notes != null && <p className="whitespace-pre-wrap">原说明：{display(value.result_notes)}</p>}
    {conditions.report_sample_serial != null && <p>原报告样机编号：{display(conditions.report_sample_serial)}</p>}
    {source.sheet != null && <div className="space-y-2"><p>原报告位置：{display(source.sheet)} · 第{display(source.row)}行</p>
      {source.reported_result != null && <p>原结论：{display(source.reported_result)} · 原报告日期：{display(source.reported_date)}</p>}
      {source.standard != null && <p className="whitespace-pre-wrap">原判据：{display(source.standard)}</p>}
      {source.method != null && <p className="whitespace-pre-wrap">原方法：{display(source.method)}</p>}
      {cells.length > 0 && <div className="overflow-x-auto"><table className="w-full text-left"><caption className="text-left">报告原单元格</caption><thead><tr><th className="p-1">位置</th><th className="p-1">原值</th></tr></thead><tbody>{cells.map(([cell, original]) => <tr className="border-t" key={cell}><td className="p-1">{cell}</td><td className="whitespace-pre-wrap break-words p-1">{display(original)}</td></tr>)}</tbody></table></div>}
    </div>}
    {timeInput.reason != null && <p className="whitespace-pre-wrap">实际时间补录依据：{display(timeInput.reason)}</p>}
    <details><summary className="cursor-pointer">原测试条件与记录编号</summary><pre className="mt-2 whitespace-pre-wrap break-words">{JSON.stringify({ test_run_id: value.id, test_case_id: value.test_case_id, sample_id: value.sample_id, sample_configuration_revision_id: value.sample_configuration_revision_id, conditions: value.conditions }, null, 2)}</pre></details>
  </div>;
}
