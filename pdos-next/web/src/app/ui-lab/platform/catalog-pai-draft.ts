import { catalogFields, catalogLabels } from "./catalog-fields";
import {
  latestCatalogRecords,
  type CatalogKind,
  type CatalogRecord,
} from "./category-preview-state";
import type { PaiScope } from "./pai-preview-state";

export type CatalogDraft = {
  categoryId: string;
  categoryName: string;
  kind: CatalogKind;
  base?: CatalogRecord;
  values: Record<string, string>;
  reason: string;
  action: "save" | "withdraw";
  status: "ready" | "saved" | "discarded" | "superseded";
  deidentified: boolean;
  savedRecord?: CatalogRecord;
  savedId?: string;
  savedVersion?: number;
};
export type CatalogIntent = { draft?: CatalogDraft; error?: string };

// Only explicit text and the captured page/record context populate this synthetic preview.
export function catalogDraftFromPrompt(
  prompt: string,
  scope: PaiScope,
  records: CatalogRecord[],
  previous?: CatalogDraft,
): CatalogIntent | undefined {
  const intent = prompt.split(/[，,；;\n]/)[0];
  const request =
    /新增|新建|创建|添加|维护|修订|修改|更新|补充|撤回|恢复/.test(intent) &&
    !/^\s*(?:修订原因|撤回原因|原因)/.test(intent);
  const explicitKind: CatalogKind | undefined = !request
    ? undefined
    : /竞品/.test(intent)
      ? "competitor"
      : /用户声音|声音摘要|用户反馈/.test(intent)
        ? "voice"
        : /规格字典|参数|测试条件/.test(intent)
          ? "parameter"
          : undefined;
  const adding = request && /新增|新建|创建|添加|补充一条/.test(intent);
  const maintaining =
    request && /维护|修订|修改|更新|补充|撤回|恢复/.test(intent);
  if (!explicitKind && /(?:新增|新建|创建|建立).{0,30}品类/.test(prompt))
    return undefined;
  const kind = explicitKind ?? previous?.kind ?? scope.catalogKind;
  const fieldFollowUp =
    (previous || scope.catalogRecord) &&
    /名称|主题|来源|摘要|样本|场景|单位|测试|判据|原因|品牌|报价/.test(prompt);
  if (!kind || (!adding && !maintaining && !fieldFollowUp)) return undefined;
  const categoryId = scope.id.startsWith("category:")
    ? scope.id.slice(9)
    : undefined;
  if (!categoryId)
    return {
      error: "先打开要维护的品类，再从页面小Pai继续，我会自动带入品类范围。",
    };
  const continuing =
    !adding && previous?.categoryId === categoryId && previous.kind === kind;
  const available = latestCatalogRecords(records).filter(
    (r) => r.category === categoryId && r.kind === kind,
  );
  const matches = available.filter(
    (r) => prompt.includes(r.id) || prompt.includes(r.values.name),
  );
  if (!adding && matches.length > 1)
    return {
      error: "提到了多条记录。请打开其中一条记录，再选择与小Pai一起维护。",
    };
  const scoped =
    scope.catalogRecord?.category === categoryId &&
    scope.catalogRecord.kind === kind
      ? scope.catalogRecord
      : undefined;
  const bound = continuing ? previous.base : scoped;
  if (!adding && bound && matches[0] && bound.id !== matches[0].id)
    return {
      error:
        "消息提到的记录与当前绑定记录不同。请从目标记录重新打开小Pai，避免修改错对象。",
    };
  const base = adding
    ? undefined
    : continuing
      ? previous.base
      : (scoped ?? matches[0]);
  if (!adding && !continuing && !base)
    return {
      error: `请先打开需要维护的${catalogLabels[kind]}记录，或在消息中给出记录名称或编号。`,
    };
  const defaults = Object.fromEntries(
    catalogFields[kind].map((f) => [
      f.key,
      f.options?.find((v) => /未知|待确认|待分类|未确认/.test(v)) ??
        (f.options?.includes("其他") ? "其他" : f.options ? "" : ""),
    ]),
  );
  const seeded =
    scope.catalogKind === kind &&
    (adding ? !scope.catalogRecord : !!scoped && scoped.id === base?.id)
      ? scope.catalogValues
      : undefined;
  const values = {
    ...defaults,
    ...(base?.values ?? {}),
    ...(continuing ? previous.values : (seeded ?? {})),
  };
  const aliases: Record<string, string[]> = {
    name: ["竞品名称", "参数名称", "主题", "名称"],
    source: ["来源与位置", "依据与适用范围", "来源", "依据"],
    content: ["声音摘要", "摘要"],
    sample: ["样本量"],
    key: ["稳定参数键", "参数键"],
    conditions: ["标准测试条件", "测试条件"],
    notes: ["补充说明", "适用边界"],
    scenario: ["用户与场景", "场景"],
    reason: ["修订原因", "撤回原因", "原因"],
  };
  const allLabels = [
    ...catalogFields[kind].flatMap((f) => aliases[f.key] ?? [f.label]),
    ...aliases.reason,
  ]
    .sort((a, b) => b.length - a.length)
    .join("|");
  const read = (labels: string[]) =>
    prompt
      .match(
        new RegExp(
          `(?:${labels.join("|")})\\s*(?:改为|改成|是|为|[:：])\\s*([^；;\\n]*?)(?=[，,]\\s*(?:${allLabels})\\s*(?:改为|改成|是|为|[:：])|[；;\\n]|$)`,
        ),
      )?.[1]
      ?.trim()
      .replace(/^[“「"']|[”」"']$/g, "");
  for (const field of catalogFields[kind]) {
    const value = read(aliases[field.key] ?? [field.label]);
    if (
      value !== undefined &&
      (!field.options || field.options.includes(value))
    )
      values[field.key] = value;
  }
  if (adding && !values.name) {
    const noun =
      kind === "competitor" ? "竞品" : kind === "voice" ? "用户声音" : "参数";
    values.name =
      prompt
        .match(
          new RegExp(
            `(?:新增|新建|创建|添加)(?:一条|一个)?${noun}\\s*[:：]\\s*([^，,；;\\n]+)`,
          ),
        )?.[1]
        ?.trim() ?? "";
  }
  if (base && kind === "parameter" && values.key !== base.values.key)
    return { error: "修订不能更换稳定参数键。如需不同参数，请另行新增。" };
  const actionText = prompt
    .split(/[；;\n]/)
    .filter((part) => !/^\s*(?:修订原因|撤回原因|原因)/.test(part))
    .join("；");
  const action = /撤回/.test(actionText)
    ? "withdraw"
    : /恢复/.test(actionText)
      ? "save"
      : continuing
        ? previous.action
        : "save";
  if (action === "withdraw" && (!base || base.state === "withdrawn"))
    return { error: "只能撤回当前有效记录；已撤回记录可以恢复并修订。" };
  return {
    draft: {
      categoryId,
      categoryName: scope.label,
      kind,
      base,
      values,
      reason: read(aliases.reason) ?? (continuing ? previous.reason : ""),
      action,
      status: "ready",
      deidentified: false,
    },
  };
}
