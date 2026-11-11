"use client";

/* The review body of one prepared candidate: the same content in the run's own
   confirmation dialog and in 要我决定's package confirmation (D77). Display only. */
import type { ReactNode } from "react";
import { candidateLabels, type CandidatePreview } from "@/lib/domain-candidate";

const fields: Record<string, string> = {
  payload: "本次内容", product_name: "型号", variant_name: "变体", platform: "平台",
  operation: "办理类型",
  reviewer_id: "具名评审人", no_alternative_reason: "无替代方案的理由",
  new_platform: "新建平台", code: "编号", name: "名称", title: "名称", description: "说明",
  compatibility: "兼容范围", platform_version: "平台版本", reason: "原因", effect: "本次影响",
  action: "动作", next_link_version: "新关联版本", expected_link_version: "原关联版本",
  question: "待决问题", owner_id: "负责人编号", due_date: "期限", brief: "说明",
  groups: "内容分组", items: "条目", ops: "修订", op: "动作", content: "内容", sources: "来源",
  source_refs: "来源引用", source_read_set: "读取依据", before: "原内容", after: "确认后的内容",
  item_id: "条目编号", base_version: "原版本", key: "条目键", value: "值", unit: "单位",
  lower: "下限", upper: "上限", availability: "可用情况", item_status: "条目状态",
  statement: "说明", quote: "原文片段", line: "行", expected_revision: "依据版本",
  parameter: "参数", parameter_id: "参数编号", parameter_version: "参数版本", version: "版本",
  condition_note: "条件", test_conditions: "测试条件", unknowns: "未知项", use_cases: "用途",
  requirements: "要求", constraints: "约束", exclusions: "排除范围", entry_kind: "立项入口",
  target_kind: "立项目标", applicable_variants: "适用变体", acceptance_criterion: "判据",
  verification_method: "验证方法", origin: "作者类型", writer_id: "作者编号", confirmed_by: "确认人",
  visibility: "可见范围", kind: "类型", text: "正文", questions: "待决问题",
  value_type: "数值类型", tolerance: "公差", text_value: "文本或选择值", modality: "要求强度",
  exceptions: "例外", nature: "要求性质", related_item_ids: "关联条目", status: "状态",
  answer: "答复", supersedes_item_id: "替代条目", type: "来源类型", id: "记录编号",
};
const values: Record<string, string> = { ...candidateLabels, attach: "关联", detach: "解除", unknown: "未知", ai_draft: "AI 草稿", known: "已知", upsert: "新增或修订", remove: "移除", new_product: "自主新品", customer_requirement: "客户需求", derivative: "派生迭代", private: "私有", category: "品类授权成员", section: "说明章节", option: "备选方案", spec: "规格要求", new: "新方案", do_nothing: "保持现状", worth_it: "立项价值", number: "数值", boolean: "是或否", decided: "已作产品决定", open: "待处理", human: "具名人员" };
const internal = new Set(["confirmation_token", "prepared_by_run_id", "candidate_digest", "prepared_event_id"]);
const enumerated = new Set(["operation", "action", "availability", "item_status", "origin", "kind", "visibility", "value_type", "nature", "status", "entry_kind", "target_kind", "type"]);
export function display(value: unknown): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  return Object.fromEntries(Object.entries(value).filter(([key]) => !internal.has(key)).map(([key, entry]) => [key, key === "payload" ? display(entry) : entry]));
}
export function detail(value: unknown, field?: string): ReactNode {
  if (value == null) return <span className="subtle">未确定</span>;
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string") return field && enumerated.has(field) ? values[value] ?? value : value;
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.length ? <ul className="space-y-2">{value.map((entry, index) => <li key={index}>{detail(entry, field)}</li>)}</ul> : <span className="subtle">无已登记内容</span>;
  if (typeof value === "object") return <dl className="candidate-fields">{Object.entries(value).map(([key, entry]) => <div key={key} className="min-w-0"><dt className="subtle">{fields[key] ?? key}</dt><dd className="whitespace-pre-wrap break-words">{detail(entry, key)}</dd></div>)}</dl>;
  return null;
}
export function platformReview(preview: CandidatePreview) {
  const payload = preview.command.payload, review = preview.review;
  return <div className="space-y-2"><p>{String(review.product_name ?? "当前型号")}{typeof review.variant_name === "string" && ` / ${review.variant_name}`}</p>{detail(review.platform)}<p>动作：{payload.action === "detach" ? "解除关联" : "关联平台"}</p><p>兼容范围：{typeof payload.compatibility === "string" && payload.compatibility || "待确认"}</p><p>平台版本：{typeof payload.platform_version === "string" && payload.platform_version || "待确认"}</p><p>原因：{String(payload.reason ?? "未填写")}</p><p className="subtle">{String(review.effect ?? "核对本次保存范围。")}</p></div>;
}
export function snapshotReview(review: Record<string, unknown>) {
  return <div className="space-y-2 break-words"><p className="font-medium">{String(review.title ?? "实际读取的来源")}</p><p className="subtle">{String(review.url ?? "")}</p><p>保存范围：{review.visibility === "private" ? "原私有上下文受众" : review.visibility === "category" ? "当前品类授权成员" : "范围待核对"}</p><p>{String(review.effect ?? "登记原研究快照，保留小Pai来源与本人确认。")}</p></div>;
}
/** 原值、新值、影响、来源与未确定项 as the server's preview states them (v1.1 §06 §6). */
export function CandidateReviewBody({ preview }: { preview: CandidatePreview }) {
  return <>{preview.command.operation === "platform.link.create" ? platformReview(preview) : preview.command.operation === "research.snapshot.register" ? snapshotReview(preview.review) : detail(display(preview.review))}</>;
}
