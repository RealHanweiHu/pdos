"use client";

import { useRef, useState } from "react";
import type { Role } from "./design-data";
import type { ProposalContext, ProposalDraft } from "./proposal-pai-draft";

import { useCategoryCatalog } from "./category-preview-state";

export type Proposal = {
  id: string;
  aiDraft?: boolean;
  categorySources?: {
    id: string;
    version: number;
    name: string;
    source: string;
  }[];
  title: string;
  category: string;
  entry: "自主新品" | "派生迭代" | "客户需求";
  status: "草稿" | "评审中" | "已批准";
  owner: string;
  reviewer?: string;
  shared: boolean;
  version: number;
  updated: string;
  project?: string;
  summary: string;
  audience: string;
  options: [string, string];
  choice: string;
  baseline?: string;
  source: string;
  specs: string[][];
  questions: { title: string; owner: string; due: string }[];
  history: {
    version: number;
    text: string;
    summary: string;
    snapshot?: Pick<
      Proposal,
      | "title"
      | "audience"
      | "options"
      | "choice"
      | "specs"
      | "questions"
      | "source"
      | "categorySources"
      | "aiDraft"
    >;
  }[];
};
const seedProposals: Proposal[] = [
  {
    id: "PA-001",
    title: "便携充气泵 P1",
    category: "auto",
    entry: "自主新品",
    status: "已批准",
    owner: "林悦",
    reviewer: "郑言",
    shared: true,
    version: 4,
    updated: "10月22日",
    project: "P1",
    summary:
      "为家庭车主在日常停车和短途出行时提供便于收纳的轮胎检查与应急补气方案。",
    audience: "家庭车主 · 日常检查与应急补气",
    options: [
      "便携款：优先收纳与携带，成本和开发周期待项目细化。",
      "长续航款：增加电池容量，体积、成本和开发周期待验证。",
    ],
    choice:
      "选择便携款；保留噪声目标与测试工况的未知项，由产品和测试负责人在项目中接续。",
    source: "用户声音 U-014 · 合成访谈；G0 具名决定",
    specs: [
      ["用途", "轮胎检查与应急补气", "U-014", "已选定"],
      ["噪声", "目标与工况待确认", "PAR-08 v2", "未知"],
      ["压力", "单位与目标待核对", "PAR-02 v3", "待确认"],
      ["充气速度", "供电与环境待确认", "PAR-04 v2", "待确认"],
    ],
    questions: [
      { title: "确认噪声目标", owner: "林悦", due: "10月26日" },
      { title: "确认测试距离、背景与负载", owner: "许澄", due: "10月28日" },
    ],
    history: [
      {
        version: 4,
        text: "G0 已批准 · 郑言具名决定；定义 v1 与 P1 项目已建立",
        summary: "选择便携款，未知项转入项目继续核对。",
      },
    ],
  },
  {
    id: "PA-002",
    title: "P1-L 长续航变体",
    category: "auto",
    entry: "派生迭代",
    status: "草稿",
    owner: "林悦",
    shared: false,
    version: 1,
    updated: "10月23日",
    summary:
      "为长途出行增加续航，先核对电池空间、重量与收纳代价，再决定是否投入独立变体。",
    audience: "长途自驾用户 · 多次补气",
    baseline: "P1 已发布定义 v2",
    options: [
      "增加电池容量：续航目标更高，重量和模具投入待估算。",
      "沿用现款：不新增变体，保留现有体积与开发投入。",
    ],
    choice: "倾向增加续航，等待结构空间核对后决定。",
    source: "父定义 v2 · 电池与收纳差异候选",
    specs: [
      ["续航", "待验证", "父定义 v2", "差异候选"],
      ["收纳空间", "待结构核对", "父定义 v2", "未知"],
      ["平台接口", "沿用候选", "父定义 v2", "待验证"],
    ],
    questions: [
      { title: "核对电池与收纳空间", owner: "陈舟", due: "10月28日" },
    ],
    history: [
      {
        version: 1,
        text: "林悦创建私有草稿",
        summary: "以 P1 定义 v2 为固定父版。",
      },
    ],
  },
  {
    id: "PA-003",
    title: "S2-L 户外接头变体",
    category: "outdoor",
    entry: "派生迭代",
    status: "草稿",
    owner: "林悦",
    shared: false,
    version: 1,
    updated: "10月22日",
    summary:
      "沿用 S2 平台，核对桨板接头、压力范围与使用场景差异，明确本轮改动范围。",
    audience: "桨板用户 · 户外充放气",
    baseline: "S2 已发布定义 v1",
    options: [
      "沿用 S2 平台并更换接头：优先验证兼容性，成本和周期待估算。",
      "重新设计接口：适配范围更广，模具投入和周期待估算。",
    ],
    choice: "优先沿用平台；兼容性未验证前不作满足承诺。",
    source: "差异表 D-02 · 私有客户输入",
    specs: [
      ["接头兼容性", "待验证", "D-02", "未知"],
      ["压力范围", "保留原值，待核对", "S2 定义 v1", "差异候选"],
    ],
    questions: [{ title: "核对接头兼容性", owner: "陈舟", due: "10月26日" }],
    history: [
      {
        version: 1,
        text: "林悦创建私有派生草稿",
        summary: "保留客户输入与固定父版。",
      },
    ],
  },
  {
    id: "PA-004",
    title: "RFQ-07 客户需求核对",
    category: "auto",
    entry: "客户需求",
    status: "草稿",
    owner: "林悦",
    shared: false,
    version: 1,
    updated: "10月21日",
    summary:
      "先与标准品固定定义核对，再判断是否需要开发。原件尚未完整覆盖，不能从已读部分推断整体满足。",
    audience: "RFQ-07 指定客户 · 受限资料",
    options: [
      "标准品匹配：满足时沿现有型号处理，不创建研发项目。",
      "定制开发：确认差异与投入后，再提交立项评审。",
    ],
    choice: "路线待定；优先补齐剩余原件与噪声工况。",
    source: "客户私有原件 RFQ-07 · 已读 6 / 8 页，2 条未知",
    specs: [
      ["原件覆盖", "6 / 8 页", "RFQ-07", "未完整"],
      ["噪声", "保留客户原值与单位", "RFQ-07 第 2 / 5 页", "工况不同"],
    ],
    questions: [
      { title: "补齐未读取的原件与缺失参数", owner: "林悦", due: "10月26日" },
    ],
    history: [
      {
        version: 1,
        text: "林悦创建私有客户需求草稿",
        summary: "客户原件不进入品类共享知识。",
      },
    ],
  },
];

export function useProductPreview(role: Role, person: string) {
  const [proposals, setProposals] = useState(seedProposals);
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [categoryTab, setCategoryTab] = useState("共享知识");
  const [proposalId, setProposalId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Proposal>>({});
  const sequence = useRef(4);
  const allowed = ["product", "management"].includes(role);
  const visible = allowed
    ? proposals.filter(
        (p) => p.shared || p.owner === person || p.reviewer === person,
      )
    : [];
  const catalog = useCategoryCatalog(allowed, person);
  const selected = visible.find((p) => p.id === proposalId);
  const category = catalog.categories.find((c) => c.id === categoryId);
  function save(value: Proposal) {
    setProposals((current) =>
      current.map((p) =>
        p.id === value.id && p.owner === person && p.status === "草稿"
          ? {
              ...value,
              version: p.version + 1,
              updated: "刚刚",
              history: [
                ...p.history,
                {
                  version: p.version,
                  text: `${person}保存修订，保留原版 v${p.version}`,
                  summary: p.summary,
                  snapshot: {
                    title: p.title,
                    audience: p.audience,
                    options: p.options,
                    choice: p.choice,
                    specs: p.specs,
                    questions: p.questions,
                    source: p.source,
                    categorySources: p.categorySources,
                    aiDraft: p.aiDraft,
                  },
                },
              ],
            }
          : p,
      ),
    );
    setDrafts((current) => {
      const next = { ...current };
      delete next[value.id];
      return next;
    });
  }
  function create(title: string, category: string, entry: Proposal["entry"]) {
    const id = `PA-${String(++sequence.current).padStart(3, "0")}`;
    const proposal: Proposal = {
      id,
      title: title.trim(),
      category,
      entry,
      status: "草稿",
      owner: person,
      shared: false,
      version: 1,
      updated: "刚刚",
      summary: "",
      audience: "",
      options: ["", ""],
      choice: "",
      source: "尚未添加依据",
      specs: [],
      questions: [],
      history: [
        {
          version: 1,
          text: `${person}创建私有草稿`,
          summary: "尚未提交评审，不创建项目。",
        },
      ],
    };
    setProposals((current) => [...current, proposal]);
    setProposalId(id);
    setDrafts((current) => ({ ...current, [id]: proposal }));
  }
  function proposalContext(
    categoryId: string,
    baseId?: string,
  ): ProposalContext | undefined {
    if (!allowed) return;
    const category = catalog.categories.find((c) => c.id === categoryId);
    const base = baseId
      ? visible.find((p) => p.id === baseId && p.category === categoryId)
      : undefined;
    if (!category || (baseId && !base)) return;
    const latest = new Map<string, (typeof catalog.catalogRecords)[number]>();
    for (const record of catalog.catalogRecords.filter(
      (r) => r.category === categoryId,
    )) {
      if (
        !latest.has(record.id) ||
        latest.get(record.id)!.version < record.version
      )
        latest.set(record.id, record);
    }
    return structuredClone({
      category,
      records: [...latest.values()].filter((r) => r.state === "active"),
      base,
      working: base ? drafts[base.id] : undefined,
    });
  }
  function confirmProposalDraft(draft: ProposalDraft) {
    if (!allowed || draft.status !== "ready")
      return { error: "当前身份或草稿状态不能保存。" };
    const { category, base, working, records } = draft.context;
    if (!catalog.categories.some((c) => c.id === category.id))
      return { error: "品类已不可用，请重新选择。" };
    if (!draft.values.title.trim()) return { error: "请填写提案名称。" };
    const current = base ? visible.find((p) => p.id === base.id) : undefined;
    if (
      base &&
      (!current ||
        current.category !== category.id ||
        current.status !== "草稿" ||
        current.owner !== person)
    )
      return { error: "只能完善本人可编辑的提案草稿。" };
    if (
      base &&
      (current!.version !== base.version ||
        JSON.stringify(drafts[base.id] ?? current) !==
          JSON.stringify(working ?? base))
    )
      return {
        error: "提案已有新修改，请重新打开当前版本，避免覆盖你的编辑。",
      };
    if (base && !draft.reason.trim()) return { error: "请补充修订原因。" };
    if (
      base &&
      JSON.stringify(draft.values) ===
        JSON.stringify(
          Object.fromEntries(
            Object.keys(draft.values).map((key) => [
              key,
              base[key as keyof Proposal],
            ]),
          ),
        )
    )
      return { error: "尚无内容变化，可以继续对话补充。" };
    const id = base?.id ?? `PA-${String(++sequence.current).padStart(3, "0")}`;
    const version = (base?.version ?? 0) + 1;
    const sources = new Map(
      (base?.categorySources ?? []).map((r) => [`${r.id}:${r.version}`, r]),
    );
    records.forEach((r) =>
      sources.set(`${r.id}:${r.version}`, {
        id: r.id,
        version: r.version,
        name: r.values.name,
        source: r.values.source || "来源待补充",
      }),
    );
    const value: Proposal = {
      ...(base ?? {}),
      ...draft.values,
      id,
      category: category.id,
      version,
      owner: person,
      title: draft.values.title.trim(),
      status: "草稿",
      shared: base?.shared ?? false,
      updated: "刚刚",
      aiDraft: true,
      categorySources: [...sources.values()],
      source: base
        ? `${base.source.split("；品类补充参考：")[0]}；品类补充参考：${[...sources.values()].map((r) => `${r.id} v${r.version}`).join("、") || "暂无新增依据"}`
        : draft.values.source,
      history: base
        ? [
            ...base.history,
            {
              version: base.version,
              text: `小Pai起草 · ${person}确认修订：${draft.reason}`,
              summary: base.summary,
              snapshot: {
                title: base.title,
                audience: base.audience,
                options: base.options,
                choice: base.choice,
                specs: base.specs,
                questions: base.questions,
                source: base.source,
                categorySources: base.categorySources,
                aiDraft: base.aiDraft,
              },
            },
          ]
        : [
            {
              version: 1,
              text: `小Pai起草 · ${person}确认创建私有草稿`,
              summary: "尚未提交评审，不创建项目。",
            },
          ],
    };
    setProposals((all) =>
      base ? all.map((p) => (p.id === id ? value : p)) : [...all, value],
    );
    setDrafts((all) => {
      const next = { ...all };
      delete next[id];
      return next;
    });
    return { id, version, proposal: structuredClone(value) };
  }
  function submit(id: string, reviewer: string) {
    setProposals((current) =>
      current.map((p) =>
        p.id === id && p.status === "草稿" && p.owner === person
          ? {
              ...p,
              status: "评审中",
              reviewer,
              updated: "刚刚",
              history: [
                ...p.history,
                {
                  version: p.version,
                  text: `${person}提交 G0 评审 · ${reviewer}具名评审`,
                  summary: `固定 v${p.version}；尚未批准、未建立项目。`,
                },
              ],
            }
          : p,
      ),
    );
  }
  return {
    ...catalog,
    proposalContext,
    confirmProposalDraft,
    categoryTab,
    setCategoryTab,
    visible,
    selected,
    category,
    categoryId,
    proposalId,
    setCategoryId,
    setProposalId,
    drafts,
    setDrafts,
    save,
    create,
    submit,
    person,
    allowed,
  };
}
export type ProductController = ReturnType<typeof useProductPreview>;
