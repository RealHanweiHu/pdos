"use client";

import { useEffect, useRef, useState } from "react";
import { projects, roles, type Role, type Screen } from "./design-data";
import {
  categoryDraftFromPrompt,
  type CategoryDraft,
} from "./category-pai-draft";
import { catalogDraftFromPrompt, type CatalogDraft } from "./catalog-pai-draft";
import {
  proposalDraftFromPrompt,
  type ProposalContext,
  type ProposalDraft,
} from "./proposal-pai-draft";
import type { CatalogKind, CatalogRecord } from "./category-preview-state";

export type PaiScope = {
  id: string;
  label: string;
  projectId?: string;
  screen?: Screen;
  proposalContext?: ProposalContext;
  proposalIntent?: "create" | "revise";
  catalogKind?: CatalogKind;
  catalogRecord?: CatalogRecord;
  catalogValues?: Record<string, string>;
};
export type PaiArtifact = {
  id: string;
  title: string;
  body: string;
  kind: "document" | "table";
  version: number;
};
type Message = {
  id: string;
  author: "user" | "pai";
  text: string;
  skill?: string;
  artifactId?: string;
  scope?: PaiScope;
  proposalDraft?: ProposalDraft;
  categoryDraft?: CategoryDraft;
  catalogDraft?: CatalogDraft;
};
export type Conversation = {
  updatedAt: number;
  id: string;
  owner: Role;
  scope: PaiScope;
  title: string;
  pinned: boolean;
  archived: boolean;
  messages: Message[];
  artifacts: PaiArtifact[];
  draft: string;
  skill: string;
  files: string[];
  status: "idle" | "running" | "waiting" | "done" | "stopped";
  task?: {
    prompt: string;
    scope: PaiScope;
    skill: string;
    follow: boolean;
    catalogRecords?: CatalogRecord[];
  };
};
export const generalScope: PaiScope = { id: "general", label: "通用对话" };
export const skillCatalog: {
  name: string;
  description: string;
  roles?: Role[];
}[] = [
  {
    name: "立项提案",
    description: "结合品类资料起草与完善私有提案",
    roles: ["product", "management"],
  },
  {
    name: "品类资料维护",
    description: "整理竞品、用户声音和规格字典，准备可核对的修订",
    roles: ["product", "management"],
  },
  {
    name: "品类整理",
    description: "明确名称与场景，准备可确认的品类候选",
    roles: ["product", "management"],
  },
  { name: "文档起草", description: "组织想法、起草与修改内容" },
  {
    name: "资料研究",
    description: "整理依据、比较方案与标记未知",
    roles: roles.filter((r) => r.id !== "external").map((r) => r.id),
  },
  {
    name: "工作与计划",
    description: "梳理依赖、安排与后续工作",
    roles: ["lead", "management", "product"],
  },
  {
    name: "工程变更",
    description: "分析配置差异与影响",
    roles: ["engineering", "manufacturing", "lead"],
  },
  {
    name: "试制与验证",
    description: "准备验证计划、梳理样件与结果",
    roles: ["quality", "manufacturing", "production", "lead"],
  },
  {
    name: "供应协作",
    description: "整理到料、承诺与交接",
    roles: ["supply", "lead"],
  },
];
export const statusLabels: Record<Conversation["status"], string> = {
  idle: "新对话",
  running: "进行中",
  waiting: "需要你处理",
  done: "已完成",
  stopped: "已停止",
};
const initialId = (role: Role, scope: PaiScope) => `${role}:${scope.id}`;
function blank(owner: Role, scope: PaiScope, id: string): Conversation {
  return {
    updatedAt: 0,
    id,
    owner,
    scope,
    title: "新对话",
    pinned: false,
    archived: false,
    messages: [],
    artifacts: [],
    draft: "",
    skill: "",
    files: [],
    status: "idle",
  };
}
function initialConversations() {
  return roles.flatMap(({ id: owner }) => {
    const scopes: PaiScope[] =
      owner === "external"
        ? [
            generalScope,
            { id: "package", label: "授权交付包 PKG-04", screen: "release" },
          ]
        : [
            generalScope,
            ...projects.map((p) => ({
              id: p.id,
              label: p.name,
              projectId: p.id,
              screen: "now" as const,
            })),
          ];
    return scopes.map((scope) => blank(owner, scope, initialId(owner, scope)));
  });
}
function draftArtifact(
  prompt: string,
  scope: PaiScope,
  id: string,
): PaiArtifact {
  const table = /比较|对比|表格/.test(prompt);
  const project = scope.projectId ? scope.label : "新方案";
  return table
    ? {
        id,
        title: `${project} · 方案比较`,
        kind: "table",
        version: 1,
        body: "比较项|方案 A · 先验证关键假设|方案 B · 完整准备后验证\n目标|尽早获得关键证据|集中完成验证\n投入|首轮范围较小|前置准备较多\n主要风险|后续可能补充验证|关键问题暴露较晚\n仍需确认|最关键的假设与样本|资料完整性与资源窗口\n建议下一步|明确首轮验收条件|明确准备完成的判据",
      }
    : {
        id,
        title: scope.projectId ? `${scope.label} · 工作方案` : "想法与行动方案",
        kind: "document",
        version: 1,
        body: `# ${scope.projectId ? scope.label + " · 工作方案" : "想法与行动方案"}\n\n## 目标\n${prompt}\n\n## 推进方式\n先明确要回答的问题，再准备足够的依据。首轮聚焦最影响判断的一件事，记录结果后决定下一步。\n\n## 第一轮工作\n• 整理已有材料，区分事实、假设和未知。\n• 明确负责人、所需输入与完成判据。\n• 优先验证关键假设，保留原始记录。\n\n## 待补充\n具体负责人、日期和验收阈值尚未指定，不替你填入承诺。\n\n## 下一步\n补齐关键条件后，继续细化执行安排。`,
      };
}

export function usePaiPreview(
  role: Role,
  pageScope: PaiScope,
  full: boolean,
  scopeLabels: Record<string, string> = {},
  catalogRecords: CatalogRecord[] = [],
) {
  const [conversations, setConversations] = useState(initialConversations);
  const [activeIds, setActiveIds] = useState<Record<string, string>>({});
  const [scopeIds, setScopeIds] = useState<Record<string, string>>({});
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const serial = useRef(0);
  useEffect(() => {
    const runningTimers = timers.current;
    return () => {
      runningTimers.forEach(clearTimeout);
    };
  }, []);
  const currentId = full
    ? (activeIds[role] ?? initialId(role, generalScope))
    : (scopeIds[`${role}:${pageScope.id}`] ?? initialId(role, pageScope));
  const resolved = conversations.map((c) => ({
    ...c,
    scope: { ...c.scope, label: scopeLabels[c.scope.id] ?? c.scope.label },
  }));
  const current =
    resolved.find((c) => c.id === currentId && c.owner === role) ??
    blank(role, pageScope, currentId);
  const mine = resolved.filter((c) => c.owner === role);
  function update(id: string, mutate: (c: Conversation) => Conversation) {
    setConversations((all) => {
      const updatedAt = Math.max(0, ...all.map((c) => c.updatedAt)) + 1;
      return all.map((c) => (c.id === id ? { ...mutate(c), updatedAt } : c));
    });
  }
  function ensure() {
    setConversations((all) =>
      all.some((c) => c.id === current.id) ? all : [...all, current],
    );
  }
  function patch(value: Partial<Conversation>) {
    ensure();
    update(current.id, (c) => ({ ...c, ...value }));
  }
  function select(id: string) {
    const conversation = mine.find((c) => c.id === id);
    if (!conversation) return;
    setActiveIds((ids) => ({ ...ids, [role]: id }));
    setScopeIds((ids) => ({
      ...ids,
      [`${role}:${conversation.scope.id}`]: id,
    }));
  }
  function bindScope(scope: PaiScope) {
    update(current.id, (c) => ({ ...c, scope }));
    setScopeIds((ids) => ({ ...ids, [`${role}:${scope.id}`]: current.id }));
  }
  function newChat(scope = full ? generalScope : pageScope, draft = "") {
    const id = `${role}:new-${++serial.current}`;
    setConversations((all) => [...all, { ...blank(role, scope, id), draft }]);
    setActiveIds((ids) => ({ ...ids, [role]: id }));
    setScopeIds((ids) => ({ ...ids, [`${role}:${scope.id}`]: id }));
  }
  function complete(id: string) {
    timers.current.delete(id);
    update(id, (c) => {
      if (c.status !== "running" || !c.task) return c;
      const { prompt, scope, skill, follow } = c.task;
      const messageId = `${id}:reply-${c.messages.length}`;
      const priorProposal = c.messages.findLast(
        (m) => m.proposalDraft?.status === "ready",
      )?.proposalDraft;
      const proposalIntent =
        /(?:新建|创建|起草|准备|完善|补充|修改|查漏).{0,30}提案|提案.{0,10}(?:新建|创建|完善|修改|查漏)/.test(
          prompt,
        ) ||
        ((!!priorProposal || !!scope.proposalContext?.base) &&
          /名称|标题|场景|目标用户|问题|方案|取舍|建议|规格|修订原因/.test(
            prompt,
          ));
      if (proposalIntent) {
        const context = priorProposal?.context ?? scope.proposalContext;
        const allowed = c.owner === "product" || c.owner === "management";
        const frozen = context?.base && context.base.status !== "草稿";
        const candidate =
          context && allowed && !frozen
            ? proposalDraftFromPrompt(prompt, context, priorProposal)
            : undefined;
        return {
          ...c,
          status: candidate || priorProposal ? "waiting" : "done",
          messages: [
            ...c.messages.map((m) =>
              candidate && m.proposalDraft?.status === "ready"
                ? {
                    ...m,
                    proposalDraft: {
                      ...m.proposalDraft,
                      status: "superseded" as const,
                    },
                  }
                : m,
            ),
            {
              id: messageId,
              author: "pai",
              scope,
              skill: "立项提案",
              proposalDraft: candidate,
              text: !allowed
                ? "当前身份没有提案管理权限。"
                : !context
                  ? "请先打开一个品类，或在新建提案中选择所属品类，我会带入对应资料。"
                  : frozen
                    ? "这份提案已固定，不能直接修订。可以查看资料，后续定义变更在项目中继续。"
                    : context.base
                      ? "已保留原稿，补充内容整理成了修订候选。打开编辑区核对，也可以继续告诉我要调整什么。"
                      : "已结合品类资料整理了一份私有草稿。规格目标与负责人等未知项留待确认。",
            },
          ],
        };
      }
      const priorCatalog = c.messages.findLast(
        (m) => m.catalogDraft?.status === "ready",
      );
      const catalogIntent = catalogDraftFromPrompt(
        prompt,
        scope,
        c.task.catalogRecords ?? [],
        priorCatalog?.catalogDraft,
      );
      if (catalogIntent) {
        const allowed = c.owner === "product" || c.owner === "management";
        const candidate = allowed ? catalogIntent.draft : undefined;
        return {
          ...c,
          status:
            candidate ||
            c.messages.some(
              (m) =>
                m.catalogDraft?.status === "ready" ||
                m.proposalDraft?.status === "ready" ||
                m.categoryDraft?.status === "ready",
            )
              ? "waiting"
              : "done",
          messages: [
            ...c.messages.map((m) =>
              candidate && m.catalogDraft?.status === "ready"
                ? {
                    ...m,
                    catalogDraft: {
                      ...m.catalogDraft,
                      status: "superseded" as const,
                    },
                  }
                : m,
            ),
            {
              id: messageId,
              author: "pai",
              scope,
              skill: "品类资料维护",
              catalogDraft: candidate,
              text: !allowed
                ? "当前身份未分配品类管理权限，不能维护共享资料。"
                : (catalogIntent.error ??
                  (candidate?.base
                    ? "已保留原版，整理好这次修改。打开编辑区核对，或继续补充。"
                    : "已带入当前品类。先看看资料摘要，缺失内容可以继续补充。")),
            },
          ],
        };
      }
      const priorCategory = c.messages.findLast(
        (m) => m.categoryDraft?.status === "ready",
      );
      const creatingCategory =
        /(?:新建|创建|建立|新增).{0,45}品类|品类.{0,10}(?:新建|创建|建立|新增)/.test(
          prompt,
        );
      const revisingCategory =
        priorCategory && /名称|名字|品类|场景/.test(prompt);
      if (creatingCategory || revisingCategory) {
        const allowed = c.owner === "product" || c.owner === "management";
        const draft = allowed
          ? categoryDraftFromPrompt(
              prompt,
              creatingCategory ? undefined : priorCategory?.categoryDraft,
            )
          : undefined;
        return {
          ...c,
          status: allowed ? "waiting" : "done",
          messages: [
            ...c.messages.map((m) =>
              allowed && m.categoryDraft?.status === "ready"
                ? {
                    ...m,
                    categoryDraft: {
                      ...m.categoryDraft,
                      status: "superseded" as const,
                    },
                  }
                : m,
            ),
            {
              id: messageId,
              author: "pai",
              skill: allowed ? "品类整理" : "通用对话",
              scope,
              text: allowed
                ? "品类草稿已整理好。可以继续聊场景，或打开编辑区核对后创建。"
                : "当前身份未分配品类管理权限，可以先讨论方向，创建需由有权限的成员办理。",
              categoryDraft: draft,
            },
          ],
        };
      }
      const modifying =
        c.artifacts.length > 0 && /修改|补充|改成|简短|精简/.test(prompt);
      const makeArtifact =
        modifying ||
        /方案|计划|提纲|文档|起草|写一|比较|对比|表格/.test(prompt);
      const previous = c.artifacts.at(-1);
      const artifact = makeArtifact
        ? modifying && previous
          ? {
              ...previous,
              id: messageId,
              version: previous.version + 1,
              body:
                /简短|精简/.test(prompt) && previous.kind === "document"
                  ? `# ${previous.title}\n\n## 目标\n明确问题，形成可执行的下一步。\n\n## 行动\n• 核对已有事实与未知。\n• 验证关键假设。\n• 依据结果调整安排。`
                  : `${previous.body}\n\n${previous.kind === "table" ? "补充要求|" + prompt + "|待具体化" : "## 补充要求\n" + prompt}`,
            }
          : draftArtifact(prompt, scope, messageId)
        : undefined;
      const text = follow
        ? `我已整理“${scope.label}”的跟进要点。继续前，需要你明确本轮最重要的完成判据；尚未替任何人修改承诺。`
        : artifact
          ? modifying
            ? "已形成修订版，原稿仍可从上面的消息打开。你也可以直接在内容区编辑。"
            : "已整理一份可继续修改的草稿。未明确的负责人、日期和判据保留为待补充。"
          : /想法|复杂|拆解|开始/.test(prompt)
            ? "可以先从三件事开始：\n\n1. 你想改变什么现状？\n2. 什么结果能说明这件事做好了？\n3. 目前最不确定的条件是什么？\n\n先说你的想法，我们再一起把第一步缩小。"
            : /你好|hello|hi|在吗/i.test(prompt)
              ? "你好，我是小Pai。可以一起讨论问题、整理资料，也可以帮你推进当前工作。想从哪里开始？"
              : `收到你的问题：“${prompt}”。\n\n这里是交互预览，暂不生成真实模型回答。可以试试“起草一份方案”“比较两个方案”，体验成果展开和继续修改。`;
      return {
        ...c,
        status:
          follow ||
          c.messages.some(
            (m) =>
              m.proposalDraft?.status === "ready" ||
              m.categoryDraft?.status === "ready" ||
              m.catalogDraft?.status === "ready",
          )
            ? "waiting"
            : "done",
        artifacts: artifact ? [...c.artifacts, artifact] : c.artifacts,
        messages: [
          ...c.messages,
          {
            id: messageId,
            author: "pai",
            text,
            skill,
            artifactId: artifact?.id,
            scope,
          },
        ],
      };
    });
  }
  function scopeForPage(): PaiScope {
    return full
      ? current.scope
      : {
          ...pageScope,
          ...(current.scope.id === pageScope.id
            ? {
                proposalIntent: current.scope.proposalIntent,
                proposalContext:
                  pageScope.proposalContext ?? current.scope.proposalContext,
              }
            : {}),
          ...(current.scope.id === pageScope.id &&
          current.scope.catalogKind === pageScope.catalogKind
            ? {
                catalogRecord: current.scope.catalogRecord,
                catalogValues: current.scope.catalogValues,
              }
            : {}),
        };
  }
  function send() {
    if (
      !current.draft.trim() ||
      current.status === "running" ||
      current.archived
    )
      return;
    ensure();
    const scope = scopeForPage();
    const prompt = current.draft.trim();
    const follow = /跟进|持续|等待/.test(prompt);
    const skill =
      current.skill ||
      (/方案|文档|提纲|写|计划/.test(prompt)
        ? "文档起草"
        : /比较|研究|资料/.test(prompt) && role !== "external"
          ? "资料研究"
          : "通用对话");
    update(current.id, (c) => ({
      ...c,
      scope,
      draft: "",
      files: [],
      title: c.messages.length ? c.title : prompt.slice(0, 24),
      status: "running",
      task: {
        prompt,
        scope,
        skill,
        follow,
        catalogRecords:
          role === "product" || role === "management" ? catalogRecords : [],
      },
      messages: [
        ...c.messages,
        {
          id: `${c.id}:request-${c.messages.length}`,
          author: "user",
          text:
            prompt +
            (c.files.length
              ? `\n附件名称：${c.files.join("、")}（本预览未读取内容）`
              : ""),
          scope,
        },
      ],
    }));
    setActiveIds((ids) => ({ ...ids, [role]: current.id }));
    setScopeIds((ids) => ({ ...ids, [`${role}:${scope.id}`]: current.id }));
    // This timer only demonstrates interaction states. It never starts a model or business command.
    timers.current.set(
      current.id,
      setTimeout(() => complete(current.id), follow ? 6500 : 1200),
    );
  }
  function stop() {
    clearTimeout(timers.current.get(current.id));
    timers.current.delete(current.id);
    patch({ status: "stopped" });
  }
  function resume() {
    if (!current.task || current.status !== "stopped") return;
    patch({ status: "running" });
    timers.current.set(
      current.id,
      setTimeout(() => complete(current.id), 1800),
    );
  }
  function archive() {
    if (current.status === "running" || current.status === "waiting") return;
    patch({ archived: true });
    newChat(full ? current.scope : pageScope);
  }
  return {
    current,
    mine,
    pageScope,
    patch,
    select,
    newChat,
    send,
    stop,
    resume,
    archive,
    bindScope,
    activateCurrent() {
      ensure();
      if (!full) update(current.id, (c) => ({ ...c, scope: scopeForPage() }));
      setActiveIds((ids) => ({ ...ids, [role]: current.id }));
    },
    saveArtifact(id: string, body: string) {
      update(current.id, (c) => ({
        ...c,
        artifacts: c.artifacts.map((a) => (a.id === id ? { ...a, body } : a)),
      }));
    },
    reviseSavedDraft(messageId: string) {
      if (
        (role !== "product" && role !== "management") ||
        current.archived ||
        current.status === "running"
      )
        return;
      const original = current.messages.find((m) => m.id === messageId);
      const proposal = original?.proposalDraft;
      const catalog = original?.catalogDraft;
      const proposalDraft: ProposalDraft | undefined =
        proposal?.status === "saved" && proposal.savedProposal
          ? { ...proposalDraftFromPrompt("", { ...proposal.context, base: structuredClone(proposal.savedProposal), working: undefined }), reason: "" }
          : undefined;
      const catalogDraft: CatalogDraft | undefined =
        catalog?.status === "saved" && catalog.savedRecord
          ? {
              ...catalog,
              base: structuredClone(catalog.savedRecord),
              values: structuredClone(catalog.savedRecord.values),
              status: "ready",
              reason: "",
              action: "save",
              deidentified: false,
              savedId: undefined,
              savedVersion: undefined,
              savedRecord: undefined,
            }
          : undefined;
      if (!proposalDraft && !catalogDraft) return;
      const id = `${current.id}:edit-${++serial.current}`;
      update(current.id, (c) => ({
        ...c,
        status: "waiting",
        messages: [
          ...c.messages,
          {
            id,
            author: "pai",
            text: "已带入刚保存的版本。可以直接编辑，也可以继续告诉我需要调整的内容。",
            scope: c.scope,
            proposalDraft,
            catalogDraft,
          },
        ],
      }));
      return id;
    },
    updateProposalDraft(messageId: string, value: Partial<ProposalDraft>) {
      if (role !== "product" && role !== "management") return;
      if (value.status === "saved" && value.savedProposal) {
        const draft = current.messages.find(
          (m) => m.id === messageId,
        )?.proposalDraft;
        if (draft)
          bindScope({
            id: `proposal:${value.savedProposal.id}`,
            label: value.savedProposal.title,
            screen: "proposal",
            proposalIntent: "revise",
            proposalContext: {
              ...draft.context,
              base: value.savedProposal,
              working: undefined,
            },
          });
      }
      update(current.id, (c) => {
        const messages = c.messages.map((m) =>
          m.id === messageId && m.proposalDraft?.status === "ready"
            ? { ...m, proposalDraft: { ...m.proposalDraft, ...value } }
            : m,
        );
        return {
          ...c,
          messages,
          status:
            c.status === "waiting" &&
            !messages.some(
              (m) =>
                m.proposalDraft?.status === "ready" ||
                m.categoryDraft?.status === "ready" ||
                m.catalogDraft?.status === "ready",
            )
              ? "done"
              : c.status,
        };
      });
    },
    updateCategoryDraft(messageId: string, value: Partial<CategoryDraft>) {
      if (role !== "product" && role !== "management") return;
      if (value.status === "created" && value.categoryId) {
        bindScope({
          id: `category:${value.categoryId}`,
          label: value.name || "品类",
          screen: "category",
        });
      }
      update(current.id, (c) => {
        const messages = c.messages.map((m) =>
          m.id === messageId && m.categoryDraft?.status === "ready"
            ? { ...m, categoryDraft: { ...m.categoryDraft, ...value } }
            : m,
        );
        return {
          ...c,
          messages,
          status:
            c.status === "waiting" &&
            !messages.some(
              (m) =>
                m.proposalDraft?.status === "ready" ||
                m.categoryDraft?.status === "ready" ||
                m.catalogDraft?.status === "ready",
            )
              ? "done"
              : c.status,
        };
      });
    },
    updateCatalogDraft(messageId: string, value: Partial<CatalogDraft>) {
      if (role !== "product" && role !== "management") return;
      if (value.status === "saved" && value.savedRecord) {
        const draft = current.messages.find(
          (m) => m.id === messageId,
        )?.catalogDraft;
        if (draft)
          bindScope({
            id: `category:${draft.categoryId}`,
            label: draft.categoryName,
            screen: "category",
            catalogKind: draft.kind,
            catalogRecord: value.savedRecord,
            catalogValues: undefined,
          });
      }
      update(current.id, (c) => {
        const messages = c.messages.map((m) =>
          m.id === messageId && m.catalogDraft?.status === "ready"
            ? { ...m, catalogDraft: { ...m.catalogDraft, ...value } }
            : m,
        );
        return {
          ...c,
          messages,
          status:
            c.status === "waiting" &&
            !messages.some(
              (m) =>
                m.proposalDraft?.status === "ready" ||
                m.categoryDraft?.status === "ready" ||
                m.catalogDraft?.status === "ready",
            )
              ? "done"
              : c.status,
        };
      });
    },
    needsAttention: mine.filter((c) => c.status === "waiting"),
    running: mine.filter((c) => c.status === "running"),
  };
}
export type PaiController = ReturnType<typeof usePaiPreview>;
