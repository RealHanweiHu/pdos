import type { CatalogRecord, ProductCategory } from "./category-preview-state";
import type { Proposal } from "./product-preview-state";

export type ProposalContext = {
  category: ProductCategory;
  records: CatalogRecord[];
  base?: Proposal;
  working?: Proposal;
};
export type ProposalValues = Pick<
  Proposal,
  | "title"
  | "entry"
  | "summary"
  | "audience"
  | "options"
  | "choice"
  | "specs"
  | "questions"
  | "source"
>;
export type ProposalDraft = {
  context: ProposalContext;
  values: ProposalValues;
  status: "ready" | "saved" | "discarded" | "superseded";
  reason: string;
  savedProposal?: Proposal;
  savedId?: string;
  savedVersion?: number;
};

export function proposalHasParameter(
  specs: ProposalValues["specs"],
  record: CatalogRecord,
) {
  return specs.some((row) => row[2]?.trim().split(/\s+/)[0] === record.id);
}

export function addProposalParameter(
  draft: ProposalDraft,
  record: CatalogRecord,
): ProposalDraft {
  if (
    draft.status !== "ready" ||
    record.category !== draft.context.category.id ||
    record.kind !== "parameter" ||
    record.state !== "active" ||
    proposalHasParameter(draft.values.specs, record)
  )
    return draft;
  const reference = `${record.id} v${record.version}`;
  const known = draft.context.records.some(
    (r) => r.id === record.id && r.version === record.version,
  );
  return {
    ...draft,
    context: {
      ...draft.context,
      records: known
        ? draft.context.records
        : [...draft.context.records, structuredClone(record)],
    },
    values: {
      ...draft.values,
      specs: [
        ...draft.values.specs,
        [
          record.values.name,
          `目标待确认 · ${record.values.unit || "单位未知"}`,
          reference,
          "手动添加 / 待确认",
        ],
      ],
      source: known
        ? draft.values.source
        : `${draft.values.source}${draft.values.source ? "；" : ""}补充规格字典：${reference}`,
    },
  };
}

export function proposalDraftFromPrompt(
  prompt: string,
  context: ProposalContext,
  previous?: ProposalDraft,
): ProposalDraft {
  const { category, records, base, working } = context;
  const source = records.map((r) => `${r.id} v${r.version}`).join("、");
  const voice = records.find((r) => r.kind === "voice");
  const original = working ?? base;
  const originalValues: ProposalValues | undefined = original
    ? {
        title: original.title,
        entry: original.entry,
        audience: original.audience,
        summary: original.summary,
        options: original.options,
        choice: original.choice,
        specs: original.specs,
        questions: original.questions,
        source: original.source,
      }
    : undefined;
  const values: ProposalValues = previous
    ? structuredClone(previous.values)
    : originalValues
      ? structuredClone(originalValues)
      : {
          title: `${category.name} · 新产品方向`,
          entry: "自主新品",
          audience: category.description,
          summary: voice
            ? `围绕「${voice.values.name}」探索产品机会。${voice.values.content || "具体问题仍需补充。"}现有信号的代表性与投入价值待核对。`
            : "尚无足够用户依据，先明确目标用户与要解决的问题。",
          options: [
            "聚焦核心场景形成新方案；成本、周期与可行性待估算。",
            "沿用现有产品或暂不开发；先补齐需求与适用性证据。",
          ],
          choice: "尚未决定，先核对用户价值、技术可行性与投入。",
          specs: records
            .filter((r) => r.kind === "parameter")
            .map((r) => [
              r.values.name,
              `目标待确认 · ${r.values.unit || "单位未知"}`,
              `${r.id} v${r.version}`,
              "AI起草 / 未知",
            ]),
          questions: [
            { title: "核对需求代表性、关键规格与方案投入", owner: "", due: "" },
          ],
          source: source
            ? `品类资料快照：${source}`
            : "当前品类暂无共享资料，依据待补充",
        };
  const read = (names: string) =>
    prompt
      .match(
        new RegExp(`(?:^|[；;\\n])\\s*(?:${names})\\s*[:：]\\s*([^；;\\n]+)`),
      )?.[1]
      ?.trim();
  const fields = {
    title: "提案名称|标题|名称",
    audience: "目标用户与场景|目标用户|场景",
    summary: "要解决的问题|问题|叙述",
    choice: "当前取舍与理由|取舍|建议",
  } as const;
  for (const key of Object.keys(fields) as (keyof typeof fields)[]) {
    const value = read(fields[key]);
    if (value) values[key] = value;
  }
  const named = prompt
    .match(
      /(?:新建|创建|起草)(?:一份|一个)?(?:立项)?提案[：:「“]([^；;\n」”]+)/,
    )?.[1]
    ?.trim();
  if (named) values.title = named;
  const entry = read("提案入口|入口");
  if (entry && ["自主新品", "派生迭代", "客户需求"].includes(entry))
    values.entry = entry as Proposal["entry"];
  const a = read("方案A|方案 A"),
    b = read("方案B|方案 B");
  if (a) values.options[0] = a;
  if (b) values.options[1] = b;
  if (base && /补齐.*规格|补充.*规格/.test(prompt)) {
    for (const r of records.filter((r) => r.kind === "parameter")) {
      if (
        !values.specs.some(
          (row) => row[0] === r.values.name || row[2]?.startsWith(r.id + " "),
        )
      )
        values.specs.push([
          r.values.name,
          `目标待确认 · ${r.values.unit || "单位未知"}`,
          `${r.id} v${r.version}`,
          "AI起草 / 未知",
        ]);
    }
  }
  const question = read("待决问题");
  if (question) values.questions.push({ title: question, owner: "", due: "" });
  return {
    context: previous?.context ?? context,
    values,
    status: "ready",
    reason:
      read("修订原因|原因") ??
      previous?.reason ??
      (base ? "依据当前品类资料补齐提案草稿" : ""),
  };
}
