"use client";

import { isRecord } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const obj = (value: unknown): Row => isRecord(value) ? value : {};
const date = (value: unknown) => typeof value === "string" && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleString() : "未知 / 未记录";
const labels: Record<string, string> = {
  change_execution_links: "历次变更执行及补齐任务的明确绑定", scope_version_id: "范围版本引用", item_key: "范围条目引用", binding_id: "原执行绑定", source_result_id: "补齐依据结果", task_id: "原任务引用", kind: "依据类别", baseline_id: "基线引用", predecessor_node_id: "前置节点引用", successor_node_id: "后续节点引用",
  definition: "固定工作日历规则", definition_digest: "日历原版本摘要", timezone: "时区", working_week: "每周工作时段", exceptions: "例外工作日", holidays: "休息日",
  baseline_version: "当前基线版本", forecast_is_current: "保存的预测依据仍一致", related_node_count: "本次关联节点数", direct_node_count: "直接绑定节点数", dependency_depth: "正式依赖读取层数", unbound_execution_task_count: "尚未绑定的执行任务数", gaps: "缺失与待复核", interpretation: "使用说明",
  node_kind: "原业务类别", source_object: "原对象引用", relation_to_change: "与本变更的关系", in_current_baseline: "属于当前正式基线", effective_actual: "当前有效实绩及缺项", plan_definition: "原正式计划定义", saved_forecast: "原预测计算结果", allocation: "固定日历与投入", formal_resource_requirements: "原正式资源需求", formal_no_resource_reason: "原无需资源依据",
  relation: "依赖关系", lag: "等待偏移", lag_unit: "偏移单位", confirmation: "原具名确认", approval: "原批准依据", sources: "原来源", basis_is_latest_forecast: "承诺依据是最新预测版本", checked_profile: "原检查采用的容量", latest_profile: "最新容量版本", version_is_current: "容量版本仍一致", created_at: "记录时间", saved_status: "原容量检查结论", saved_conflict_count: "原检查冲突数", saved_unknown_count: "原检查缺项数", saved_conflicts: "原检查中相关资源冲突", saved_unknown: "原检查待补资料", current_occupancy: "当前共享预约汇总", occupancy_truncated: "当前预约汇总有省略", current_capacity_status: "当前可兑现性",
  title: "名称", status: "实际状态", node_key: "计划节点", node_id: "节点引用", id: "原记录引用", record_id: "时间记录引用", resource_id: "资源引用", resource_name: "资源名称", name: "名称", reason: "依据", version: "版本", discipline: "专业", expected_output: "交付要求", completion_criteria: "完成判据", effort_hours: "工作量（小时）", waiting_days: "等待天数", estimate_basis: "估算依据", parallel_units: "并行投入", allocation_basis: "投入依据", not_before: "最早开始限制", calendar_version_id: "日历版本引用",
  actual_start: "实际开始", actual_finish: "实际结束", actual_start_event: "开始事件依据", actual_finish_event: "结束事件依据", actual_observation: "业务实绩回执", actual_correction: "实际纠错依据", input_unknown: "无法确定的输入", input_warnings: "输入提示", source_status: "原业务状态", source_outcome: "原业务结论", completion_basis: "完成判据依据", id_handoff_conditions: "交接接收条件",
  start: "开始", end: "结束", finish: "完成", as_of: "计算基准时间", forecast_start: "预测开始", forecast_finish: "预测完成", remaining_work_start: "剩余工作开始", remaining_work_minutes: "剩余工作量（分钟）", window_start: "容量开始", window_end: "容量结束", basis: "声明依据", scope_label: "原承诺范围", units: "占用量", demand_units: "需求量", available_units: "可用量", node_keys: "涉及节点", policy_id: "授权政策引用", forecast_record_id: "预测版本引用", capacity_check_id: "容量回执引用", approved_by_user_id: "具名批准人引用", actor_id: "办理人引用", at: "办理时间", decision: "结论", warning: "提示", unknowns: "未知项",
};
const values: Record<string, string> = {
  scope_task: "范围执行任务", follow_up_task: "后续补齐任务", task: "项目任务", gate: "关口", build: "试制批次", test_run: "逐次测试", certification: "认证", milestone: "正式检查点", direct_binding: "由实际业务对象或变更任务直接绑定", formal_dependency: "经原基线正式依赖关联，尚未判定受变更影响", requires_recheck: "须在原排程流程重新检查", capacity_clear: "原检查时容量无冲突", conflicts: "原检查存在冲突", unknown: "尚未明确", todo: "待执行", in_progress: "执行中", blocked: "受阻", done: "已完成", skipped: "已跳过", working_hours: "工作小时", calendar_days: "日历天", fs: "完成后开始", ss: "开始后开始", ff: "完成后完成", sf: "开始后完成",
};
function Value({ value }: { value: unknown }) {
  if (value == null) return <span className="text-muted-foreground">未记录 / 尚不能确定</span>;
  if (typeof value === "boolean") return <span>{value ? "是" : "否"}</span>;
  if (Array.isArray(value)) return value.length ? <ol className="space-y-2">{value.map((item,i) => <li className="border-l pl-2" key={i}><Value value={item}/></li>)}</ol> : <span className="text-muted-foreground">本次记录为空</span>;
  if (isRecord(value)) return <dl className="space-y-1">{Object.entries(value).map(([key,item]) => <div key={key}><dt className="text-muted-foreground">{labels[key] ?? key}</dt><dd className="whitespace-pre-wrap break-words"><Value value={item}/></dd></div>)}</dl>;
  return <span className="whitespace-pre-wrap break-words">{values[String(value)] ?? String(value)}</span>;
}
export function ChangeScheduleSource({ fields }: { fields: Row }) {
  const times = obj(fields.four_times);
  return <div className="mt-3 space-y-3 text-xs">
    {fields.four_times != null && <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr><th className="p-2">时间性质</th><th className="p-2">版本</th><th className="p-2">开始</th><th className="p-2">结束</th></tr></thead><tbody>{Object.entries({ baseline: "基线", forecast: "预测", commitment: "承诺", actual: "原实际记录" }).map(([kind,label]) => { const row = obj(times[kind]); return <tr className="border-t" key={kind}><th className="p-2 font-normal">{label}</th><td className="p-2">{row.version == null ? "未记录" : `v${row.version}`}</td><td className="p-2">{date(row.start)}</td><td className="p-2">{date(row.end)}</td></tr>; })}</tbody></table><p className="mt-2 text-muted-foreground">时间按当前设备时区显示。实际纠错后的有效实绩在下方另列；缺少时间不能用任务状态补齐。</p></div>}
    <dl className="space-y-3">{Object.entries(fields).filter(([key]) => key !== "four_times").map(([key,value]) => <div key={key}><dt className="font-medium">{labels[key] ?? key}</dt><dd className="mt-1 max-h-96 overflow-auto"><Value value={value}/></dd></div>)}</dl>
  </div>;
}
