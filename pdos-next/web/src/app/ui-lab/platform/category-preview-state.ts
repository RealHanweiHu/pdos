"use client";

import { useRef, useState } from "react";
import { catalogFields } from "./catalog-fields";
import type { CatalogDraft } from "./catalog-pai-draft";

export type ProductCategory = {
  id: string;
  name: string;
  description: string;
  owner: string;
  models: string[];
  project?: string;
};
const initialCategories: ProductCategory[] = [
  {
    id: "auto",
    name: "汽车充气泵",
    description: "轮胎检查、日常补气与出行应急",
    owner: "林悦",
    models: ["P1 便携款"],
    project: "P1",
  },
  {
    id: "outdoor",
    name: "户外充气泵",
    description: "桨板与户外装备的充放气体验",
    owner: "林悦",
    models: ["S1 平台款", "S2 桨板泵"],
    project: "S2",
  },
  {
    id: "micro",
    name: "微型泵",
    description: "小型设备的流体输送与集成应用",
    owner: "高远",
    models: ["D3 微型隔膜泵"],
    project: "D3",
  },
];
export type CatalogKind = "competitor" | "voice" | "parameter";
export type CatalogRecord = {
  id: string;
  category: string;
  kind: CatalogKind;
  version: number;
  state: "active" | "withdrawn";
  values: Record<string, string>;
  origin: "human" | "imported" | "ai_draft";
  author: string;
  reason: string;
};
const initialRecords: CatalogRecord[] = [
  {
    id: "C-02",
    category: "auto",
    kind: "competitor",
    version: 1,
    state: "active",
    origin: "imported",
    author: "林悦",
    reason: "导入公开资料（合成示例）",
    values: {
      name: "C-02 便携充气泵",
      brand: "示例品牌 C",
      scenario: "家庭车主 · 便携补气",
      evidence: "公开宣传",
      source: "C-02 公开参数页（合成示例）",
      date: "",
      price: "",
      currency: "CNY",
      priceBasis: "未知",
      priceDate: "",
      taxShipping: "未知",
      notes: "尚未实测；压力、噪声口径待核对。",
    },
  },
  {
    id: "U-014",
    category: "auto",
    kind: "voice",
    version: 1,
    state: "active",
    origin: "human",
    author: "林悦",
    reason: "记录合成访谈摘要",
    values: {
      name: "随车收纳与操作便利",
      scenario: "家庭车主 · 日常停车与短途出行",
      content: "应急补气设备需要便于随车收纳，并能快速完成轮胎检查。",
      channel: "用户访谈",
      source: "U-014 合成访谈摘要",
      sample: "",
      date: "",
      classification: "使用体验",
      notes: "样本量未登记，不能推断普遍需求。",
    },
  },
  ...[
    ["PAR-02", "最大压力", "3", "pressure_max", "kPa", "压力口径、温度"],
    ["PAR-08", "噪声", "2", "noise", "dB(A)", "距离、背景、负载"],
    ["PAR-04", "充气速度", "2", "flow_rate", "L/min", "压力、供电、环境"],
  ].map(
    ([id, name, version, key, unit, conditions]): CatalogRecord => ({
      id,
      category: "auto",
      kind: "parameter",
      version: Number(version),
      state: "active",
      origin: "imported",
      author: "林悦",
      reason: "沿用当前参数版本（合成示例）",
      values: {
        name,
        key,
        unit,
        direction: "待确认",
        conditions,
        method: "未知，待专业确认",
        criterion: "未知，待专业确认",
        source: "品类规格字典 · 合成参考",
        notes: "引用时需核对工况与适用性。",
      },
    }),
  ),
];
export function latestCatalogRecords(records: CatalogRecord[]) {
  const latest = new Map<string, CatalogRecord>();
  records.forEach((record) => {
    if ((latest.get(record.id)?.version ?? 0) < record.version)
      latest.set(record.id, record);
  });
  return [...latest.values()];
}
export function useCategoryCatalog(allowed: boolean, person: string) {
  const [categories, setCategories] = useState(initialCategories);
  const [records, setRecords] = useState(initialRecords);
  const sequence = useRef(20);
  function createCategory(name: string, description: string) {
    if (!allowed || !name.trim()) return { error: "请填写品类名称。" };
    if (
      categories.some(
        (v) =>
          v.name.trim().toLocaleLowerCase() === name.trim().toLocaleLowerCase(),
      )
    )
      return { error: "已有同名品类，请使用不同名称。" };
    const id = `category-${++sequence.current}`;
    setCategories((current) => [
      ...current,
      {
        id,
        name: name.trim(),
        description: description.trim(),
        owner: person,
        models: [],
      },
    ]);
    return { id };
  }
  function updateCategory(id: string, name: string, description: string) {
    if (!allowed || !categories.some((v) => v.id === id))
      return { error: "当前品类不可维护。" };
    if (!name.trim()) return { error: "请填写品类名称。" };
    if (
      categories.some(
        (v) =>
          v.id !== id &&
          v.name.trim().toLocaleLowerCase() === name.trim().toLocaleLowerCase(),
      )
    )
      return { error: "已有同名品类，请使用不同名称。" };
    setCategories((current) =>
      current.map((v) =>
        v.id === id
          ? { ...v, name: name.trim(), description: description.trim() }
          : v,
      ),
    );
    return { id };
  }
  function saveCatalog(
    kind: CatalogKind,
    category: string,
    values: Record<string, string>,
    previous?: CatalogRecord,
    reason = "",
    restoring = false,
    origin: CatalogRecord["origin"] = "human",
  ) {
    if (!allowed || !categories.some((v) => v.id === category))
      return { error: "当前品类不可维护。" };
    if (previous && (previous.category !== category || previous.kind !== kind))
      return { error: "记录与当前品类不匹配，请重新打开。" };
    const latest =
      previous &&
      latestCatalogRecords(records).find((v) => v.id === previous.id);
    if (
      previous &&
      (!latest ||
        latest.version !== previous.version ||
        (latest.state === "withdrawn" && !restoring))
    )
      return { error: "记录已更新，请关闭后重新打开当前版本。" };
    const trimmed = Object.fromEntries(
      Object.entries(values).map(([key, value]) => [key, value.trim()]),
    );
    if (!trimmed.name) return { error: "请填写名称。" };
    for (const field of catalogFields[kind]) {
      const value = trimmed[field.key];
      if (field.required && !value) return { error: `请填写${field.label}。` };
      if (value && field.options && !field.options.includes(value))
        return { error: `请核对${field.label}。` };
      if (
        value &&
        field.type === "number" &&
        (!Number.isFinite(Number(value)) ||
          Number(value) < (field.min ?? 0) ||
          (field.step === 1 && !Number.isInteger(Number(value))))
      )
        return { error: `请填写有效的${field.label}。` };
    }
    if (kind === "parameter" && !trimmed.key)
      return { error: "请填写稳定参数键。" };
    if (kind === "parameter" && previous && trimmed.key !== previous.values.key)
      return { error: "修订不能更换稳定参数键。" };
    if (
      kind === "parameter" &&
      latestCatalogRecords(records).some(
        (v) =>
          v.category === category &&
          v.kind === kind &&
          v.id !== previous?.id &&
          v.values.key.toLowerCase() === trimmed.key.toLowerCase(),
      )
    )
      return { error: "该参数键已存在，请修订原参数或使用不同键。" };
    const id =
      previous?.id ??
      `${kind === "competitor" ? "C" : kind === "voice" ? "U" : "PAR"}-${++sequence.current}`;
    const record: CatalogRecord = {
      id,
      category,
      kind,
      version: (previous?.version ?? 0) + 1,
      state: "active",
      values: trimmed,
      origin,
      author: origin === "ai_draft" ? "小Pai" : person,
      reason: reason.trim() || "新增记录",
    };
    setRecords((current) => [...current, record]);
    return { id, record: structuredClone(record) };
  }

  function withdrawCatalog(previous: CatalogRecord, reason: string) {
    if (!allowed || !reason.trim()) return { error: "请说明撤回原因。" };
    const latest = latestCatalogRecords(records).find(
      (v) => v.id === previous.id,
    );
    if (
      !latest ||
      latest.version !== previous.version ||
      latest.state === "withdrawn"
    )
      return { error: "记录已更新，请重新打开。" };
    const record: CatalogRecord = {
      ...latest,
      version: latest.version + 1,
      state: "withdrawn",
      author: person,
      origin: "human",
      reason: reason.trim(),
    };
    setRecords((current) => [...current, record]);
    return { id: latest.id, record: structuredClone(record) };
  }

  function confirmCatalogDraft(draft: CatalogDraft) {
    if (!allowed || draft.status !== "ready")
      return { error: "当前候选不可保存。" };
    if (
      draft.base &&
      (draft.base.category !== draft.categoryId ||
        draft.base.kind !== draft.kind)
    )
      return { error: "候选范围与原记录不一致。" };
    if (draft.base && !draft.reason.trim())
      return { error: "请说明本次维护原因。" };
    if (draft.action === "withdraw") {
      if (!draft.base) return { error: "请先选择要撤回的记录。" };
      const result = withdrawCatalog(
        draft.base,
        `${draft.reason.trim()}（${person}确认）`,
      );
      return {
        ...result,
        version: result.id ? draft.base.version + 1 : undefined,
      };
    }
    if (!draft.deidentified)
      return { error: "请先核对共享内容不含客户身份信息。" };
    const values =
      draft.kind === "parameter"
        ? {
            ...draft.values,
            conditions: draft.values.conditions?.trim() || "未知，待确认",
            method: draft.values.method?.trim() || "未知，待确认",
            criterion: draft.values.criterion?.trim() || "未知，待确认",
          }
        : draft.values;
    if (
      draft.base?.state === "active" &&
      catalogFields[draft.kind].every(
        (f) =>
          (values[f.key] ?? "").trim() ===
          (draft.base!.values[f.key] ?? "").trim(),
      )
    )
      return { error: "还没有修改内容，可以继续对话补充或编辑候选。" };
    const result = saveCatalog(
      draft.kind,
      draft.categoryId,
      values,
      draft.base,
      `${draft.reason.trim() || "新增资料"}（${person}确认）`,
      draft.base?.state === "withdrawn",
      "ai_draft",
    );
    return {
      ...result,
      version: result.id ? (draft.base?.version ?? 0) + 1 : undefined,
    };
  }
  return {
    categories,
    catalogRecords: records,
    createCategory,
    updateCategory,
    confirmCatalogDraft,
    saveCatalog,
    withdrawCatalog,
  };
}
