"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";

import type { WorkspaceIdentity } from "./workspace-types";

export type WorkPerspective =
  | "personal"
  | "product"
  | "project"
  | "engineering"
  | "quality"
  | "introduction"
  | "supply"
  | "portfolio"
  | "administration";

export type WorkPerspectiveDefinition = {
  id: WorkPerspective;
  label: string;
  description: string;
  priorityRoutes: readonly string[];
  actionLabels: Readonly<Record<string, string>>;
  primaryProjectTab: "overview" | "work-items" | "stages" | "plan" | "engineering" | "quality" | "materials" | "gates" | "documents" | "decisions";
  steps: readonly { label: string; description: string; href: string }[];
};

// Perspectives organize work already available to the person. They neither
// declare a professional appointment nor grant object or action permissions.
const perspectives: Record<WorkPerspective, WorkPerspectiveDefinition> = {
  personal: {
    id: "personal",
    label: "我的工作",
    description: "先处理分派给我的任务、待确认事项和交接。",
    priorityRoutes: ["/my-work", "/ask", "/ai-review", "/projects", "/knowledge"],
    actionLabels: {
      "/my-work": "处理本人待办", "/ask": "交代工作目标", "/ai-review": "核对 AI 建议",
      "/projects": "打开相关项目", "/knowledge": "查阅已核对知识",
    },
    primaryProjectTab: "work-items",
    steps: [
      { label: "确认今天的工作", description: "查看本人责任、期限、等待条件与待签核事项。", href: "/my-work" },
      { label: "核对资料与建议", description: "阅读来源和变更内容，办理当前有权处理的建议。", href: "/ai-review" },
      { label: "执行与交接", description: "进入原工作记录提交结果，由对应人员接收或验证。", href: "/projects" },
    ],
  },
  product: {
    id: "product",
    label: "产品工作",
    description: "从研究证据形成产品选择、定义和立项输入。",
    priorityRoutes: ["/product-work", "/requirements", "/cases", "/my-work", "/ask"],
    actionLabels: {
      "/product-work": "进入产品主题", "/requirements": "核对需求与来源", "/cases": "准备立项评估",
      "/my-work": "处理产品协作待办", "/ask": "交代研究目标",
    },
    primaryProjectTab: "overview",
    steps: [
      { label: "研究与比较", description: "明确用户和使用场景，核对竞品、市场与原始证据。", href: "/product-work" },
      { label: "形成产品定义", description: "比较机会与方案，补齐实验和专业约束，按当前授权办理定义。", href: "/product-work" },
      { label: "衔接需求与立项", description: "把有效定义传入需求和开发案例，分别完成适用评审。", href: "/requirements" },
      { label: "跟踪产品反馈", description: "在原主题核对开发、质量和成本反馈，准备下一版取舍。", href: "/product-work" },
    ],
  },
  project: {
    id: "project",
    label: "项目推进",
    description: "组织责任和计划，处理阻塞、评审与交接。",
    priorityRoutes: ["/projects", "/my-work", "/cases", "/portfolio", "/ask"],
    actionLabels: {
      "/projects": "推进项目计划", "/my-work": "处理项目协调待办", "/cases": "核对立项条件",
      "/portfolio": "查看跨项目阻塞", "/ask": "准备项目跟进",
    },
    primaryProjectTab: "plan",
    steps: [
      { label: "核对立项条件", description: "查看开发案例、评审结论和首版计划的当前准备情况。", href: "/cases" },
      { label: "确认计划与责任", description: "选择项目核对依赖、投入、具名责任和有效基线。", href: "/projects" },
      { label: "处理例外", description: "查看延期与重大阻塞的来源，准备具备授权的协调或决策。", href: "/portfolio" },
      { label: "推进评审和交接", description: "回到项目完成适用评审，跟踪交付接收与未完事项。", href: "/projects" },
    ],
  },
  engineering: {
    id: "engineering",
    label: "工程设计",
    description: "沿设计版本、接口、变更和验证推进专业工作。",
    priorityRoutes: ["/my-work", "/projects", "/ai-review", "/knowledge", "/ask"],
    actionLabels: {
      "/my-work": "处理工程待办", "/projects": "进入工程与变更", "/ai-review": "核对工程建议",
      "/knowledge": "查阅设计经验", "/ask": "分析工程资料",
    },
    primaryProjectTab: "engineering",
    steps: [
      { label: "领取当前责任", description: "查看分派任务、设计输入和前置条件。", href: "/my-work" },
      { label: "核对设计与接口", description: "选择项目查看规格、设计版本、评审资料与共同接口。", href: "/projects" },
      { label: "办理变更与整改", description: "核对影响和有效批准，提交本专业设计或整改证据。", href: "/projects" },
      { label: "验证与交付", description: "跟踪实际验证和交付接收，将经验保留在原记录中。", href: "/projects" },
    ],
  },
  quality: {
    id: "quality",
    label: "测试与品质",
    description: "核对测试配置与证据，推进调查、复验和独立验证。",
    priorityRoutes: ["/my-work", "/projects", "/ai-review", "/knowledge", "/ask"],
    actionLabels: {
      "/my-work": "处理测试与验证待办", "/projects": "进入试制测试与质量", "/ai-review": "核对品质建议",
      "/knowledge": "查阅质量经验", "/ask": "核对报告与失败问题",
    },
    primaryProjectTab: "quality",
    steps: [
      { label: "核对待测与待验证事项", description: "查看本人测试、调查、整改验证和签核责任。", href: "/my-work" },
      { label: "执行测试与登记证据", description: "选择项目核对样机配置、用例、真实结果和原始报告。", href: "/projects" },
      { label: "处理失败与复验", description: "从失败问题追踪整改和新配置复测，保留原结果。", href: "/projects" },
      { label: "确认验证与质量交付", description: "核对当前证据并由有效具名人员完成适用验证和签核。", href: "/projects" },
    ],
  },
  introduction: {
    id: "introduction",
    label: "PIE 与制造导入",
    description: "按具名任务核对可制造性、工装、试制和交付接收。",
    priorityRoutes: ["/my-work", "/projects", "/knowledge", "/ai-review", "/ask"],
    actionLabels: { "/my-work": "处理导入与接收待办", "/projects": "核对试制与交付", "/knowledge": "查阅制造经验", "/ai-review": "核对导入建议", "/ask": "整理导入资料" },
    primaryProjectTab: "quality",
    steps: [
      { label: "核对输入与责任", description: "查看本人任务、版本、前置条件及交付接收人。", href: "/my-work" },
      { label: "准备试制与工装", description: "在项目中核对试制配置、齐套及工装记录。", href: "/projects" },
      { label: "提交执行证据", description: "在原任务记录实际试装、变更实施和异常结果。", href: "/my-work" },
      { label: "办理交付与接收", description: "核对当前文件和未完事项，由实际接收人确认。", href: "/projects" },
    ],
  },
  supply: {
    id: "supply",
    label: "供应协作",
    description: "围绕物料齐套、供样、供方异常与成本协调。",
    priorityRoutes: ["/projects", "/my-work", "/portfolio", "/ai-review", "/ask"],
    actionLabels: {
      "/projects": "进入物料与供应", "/my-work": "处理供应协调待办", "/portfolio": "查看齐套与资源阻塞",
      "/ai-review": "核对供应恢复建议", "/ask": "整理供样与异常资料",
    },
    primaryProjectTab: "materials",
    steps: [
      { label: "核对物料需求", description: "选择项目查阅开发配置、Build 需求和有效供应资料。", href: "/projects" },
      { label: "协调短缺与供样", description: "查看本人待办，核实承诺、实际收样和未知项。", href: "/my-work" },
      { label: "处理异常与恢复", description: "核对恢复方案和关联证据，沿原权限办理后续动作。", href: "/ai-review" },
      { label: "跟踪齐套与成本反馈", description: "回到原项目查看最新状态与实际回执。", href: "/projects" },
    ],
  },
  portfolio: {
    id: "portfolio",
    label: "管理决策",
    description: "查看项目健康、重大例外和产品投入的取舍依据。",
    priorityRoutes: ["/portfolio", "/dashboard", "/cases", "/product-work", "/projects"],
    actionLabels: {
      "/portfolio": "处理组合与重大例外", "/dashboard": "查看当前项目快照", "/cases": "查阅商业与技术评审",
      "/product-work": "查看产品机会与定义", "/projects": "追溯原项目",
    },
    primaryProjectTab: "overview",
    steps: [
      { label: "识别需要决策的例外", description: "查看有权读取的项目健康、重大阻塞和缺失证据。", href: "/portfolio" },
      { label: "比较产品与投入", description: "核对产品机会和立项依据，了解继续、调整或停止的代价。", href: "/product-work" },
      { label: "办理具名评审", description: "进入原案例查看本轮材料，按有效政策完成本人评审或批准。", href: "/cases" },
      { label: "追踪决策落实", description: "回到原项目核对执行和交接结果，保留决策与事实的区别。", href: "/projects" },
    ],
  },
  administration: {
    id: "administration",
    label: "系统管理",
    description: "维护成员、组织流程、模型可用性与账户安全。",
    priorityRoutes: ["/governance/users", "/governance/organization", "/governance/models", "/governance/ai", "/settings/security", "/events"],
    actionLabels: {
      "/governance/users": "管理成员与角色", "/governance/organization": "核对组织与流程",
      "/governance/models": "检查模型配置", "/governance/ai": "检查 AI 运行与资格",
      "/settings/security": "管理账户安全", "/events": "查看事件与运行记录",
    },
    primaryProjectTab: "overview",
    steps: [
      { label: "维护成员与访问", description: "按当前权限管理账户、组织归属和有效代理。", href: "/governance/users" },
      { label: "核对组织流程", description: "检查责任、流程模板与具名批准安排。", href: "/governance/organization" },
      { label: "检查模型与 AI 可用性", description: "查看实际配置、使用限制、资格和失败恢复入口。", href: "/governance/models" },
      { label: "追踪系统异常", description: "从事件与运行记录核对问题，按当前权限执行恢复。", href: "/events" },
    ],
  },
};

const businessPerspectives: readonly WorkPerspective[] = ["personal", "product", "project", "engineering", "quality", "introduction", "supply", "portfolio"];
const internalRoles = new Set(["owner", "admin", "project_manager", "engineer", "quality"]);

export function getAvailablePerspectives(role: string): WorkPerspective[] {
  if (!internalRoles.has(role)) return [];
  return role === "owner" || role === "admin"
    ? [...businessPerspectives, "administration"]
    : [...businessPerspectives];
}

export function getDefaultPerspective(role: string): WorkPerspective {
  return role === "engineer" ? "engineering" : role === "quality" ? "quality" : "personal";
}

export function getPerspective(id: WorkPerspective): WorkPerspectiveDefinition {
  return Object.hasOwn(perspectives, id) ? perspectives[id] : perspectives.personal;
}

const preferenceEvent = "pdos:work-perspective-preference";
const memoryPreferences = new Map<string, string>();
const sessionFallbackKeys = new Set<string>();

function readPreference(key: string) {
  if (sessionFallbackKeys.has(key)) return memoryPreferences.get(key) ?? null;
  try { return window.localStorage.getItem(key); }
  catch { return memoryPreferences.get(key) ?? null; }
}

export function useWorkPerspective(identity: WorkspaceIdentity) {
  const role = identity.user.role;
  const key = `pdos.work-perspective:${encodeURIComponent(identity.tenant.id)}:${encodeURIComponent(identity.user.id)}`;
  const availableIds = useMemo(() => getAvailablePerspectives(role), [role]);
  const available = useMemo(() => availableIds.map(getPerspective), [availableIds]);
  const defaultPerspective = getDefaultPerspective(role);

  const subscribe = useCallback((listener: () => void) => {
    function onStorage(event: StorageEvent) {
      if (event.key !== null && event.key !== key) return;
      if (event.key === null) {
        sessionFallbackKeys.clear();
        memoryPreferences.clear();
        listener();
        return;
      }
      sessionFallbackKeys.delete(key);
      if (event.newValue === null) memoryPreferences.delete(key);
      else memoryPreferences.set(key, event.newValue);
      listener();
    }
    function onPreference(event: Event) {
      const detail = (event as CustomEvent<{ key?: string }>).detail;
      if (!detail?.key || detail.key === key) listener();
    }
    window.addEventListener("storage", onStorage);
    window.addEventListener(preferenceEvent, onPreference);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(preferenceEvent, onPreference);
    };
  }, [key]);
  const getSnapshot = useCallback((): WorkPerspective => {
    if (availableIds.length === 0) return defaultPerspective;
    const remembered = readPreference(key);
    return availableIds.find((id) => id === remembered) ?? defaultPerspective;
  }, [availableIds, defaultPerspective, key]);
  const getServerSnapshot = useCallback(() => defaultPerspective, [defaultPerspective]);
  const selected = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const setPerspective = useCallback((id: WorkPerspective) => {
    if (!availableIds.includes(id)) return;
    memoryPreferences.set(key, id);
    try {
      window.localStorage.setItem(key, id);
      sessionFallbackKeys.delete(key);
    } catch {
      sessionFallbackKeys.add(key);
    }
    window.dispatchEvent(new CustomEvent(preferenceEvent, { detail: { key } }));
  }, [availableIds, key]);

  return { perspective: getPerspective(selected), setPerspective, available };
}
