import type { CatalogKind } from "./category-preview-state";

export type Field = {
  key: string;
  label: string;
  type?: "textarea" | "date" | "number";
  required?: boolean;
  options?: string[];
  placeholder?: string;
  extra?: boolean;
  min?: number;
  step?: number | "any";
};
export const catalogFields: Record<CatalogKind, Field[]> = {
  competitor: [
    { key: "name", label: "竞品名称", required: true },
    { key: "brand", label: "品牌" },
    { key: "scenario", label: "用户与场景" },
    {
      key: "evidence",
      label: "数据类型",
      required: true,
      options: ["公开宣传", "实测", "推断", "未知"],
    },
    {
      key: "source",
      label: "来源与位置",
      required: true,
      placeholder: "公开链接、资料名称或测试记录编号",
    },
    { key: "date", label: "资料日期", type: "date" },
    {
      key: "price",
      label: "报价",
      type: "number",
      min: 0,
      step: "any",
      extra: true,
      placeholder: "未知可留空",
    },
    {
      key: "currency",
      label: "币种",
      options: ["CNY", "USD", "EUR", "GBP", "JPY", "其他 / 未确认"],
      extra: true,
    },
    { key: "priceDate", label: "报价日期", type: "date", extra: true },
    {
      key: "priceBasis",
      label: "价格口径",
      options: ["未知", "零售价", "促销价", "渠道报价"],
      extra: true,
    },
    {
      key: "taxShipping",
      label: "税费与运费",
      options: [
        "未知",
        "含税含运",
        "含税不含运",
        "不含税不含运",
        "其他，见备注",
      ],
      extra: true,
    },
    { key: "notes", label: "补充说明", type: "textarea", extra: true },
  ],
  voice: [
    { key: "name", label: "主题", required: true },
    {
      key: "content",
      label: "声音摘要",
      type: "textarea",
      required: true,
      placeholder: "记录观察到的需求、痛点或使用反馈",
    },
    { key: "scenario", label: "用户与场景" },
    {
      key: "channel",
      label: "来源渠道",
      options: ["用户访谈", "公开评论", "问卷", "售后反馈", "其他"],
    },
    {
      key: "source",
      label: "来源与位置",
      required: true,
      placeholder: "公开出处或去标识后的记录编号",
    },
    {
      key: "sample",
      label: "样本量",
      type: "number",
      min: 1,
      step: 1,
      placeholder: "未知可留空",
    },
    {
      key: "classification",
      label: "主题分类",
      options: [
        "使用体验",
        "性能需求",
        "质量问题",
        "价格与购买",
        "其他 / 待分类",
      ],
    },
    { key: "date", label: "采集日期", type: "date" },
    {
      key: "notes",
      label: "适用边界",
      type: "textarea",
      placeholder: "样本、市场或渠道的限制",
    },
  ],
  parameter: [
    { key: "name", label: "参数名称", required: true },
    {
      key: "key",
      label: "稳定参数键",
      required: true,
      placeholder: "例如 noise；修订时保持不变",
    },
    {
      key: "unit",
      label: "单位",
      required: true,
      placeholder: "例如 dB(A)，无单位可填写无量纲",
    },
    {
      key: "direction",
      label: "评价方向",
      options: ["待确认", "越大越好", "越小越好", "目标范围"],
    },
    {
      key: "conditions",
      label: "标准测试条件",
      type: "textarea",
      placeholder: "未知可留空；不推定测试工况",
    },
    {
      key: "method",
      label: "测试方法",
      type: "textarea",
      placeholder: "方法名称、标准或当前未知项",
    },
    {
      key: "criterion",
      label: "通过判据",
      type: "textarea",
      placeholder: "适用的判据；未知可留空",
    },
    { key: "source", label: "依据与适用范围", required: true },
    { key: "notes", label: "补充说明", type: "textarea", extra: true },
  ],
};
export const catalogLabels = {
  competitor: "竞品",
  voice: "用户声音",
  parameter: "参数",
};

export const catalogTabs: Record<CatalogKind, string> = {
  competitor: "竞品库",
  voice: "用户声音",
  parameter: "规格字典",
};
