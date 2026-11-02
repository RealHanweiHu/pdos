export type Role =
  | "product"
  | "lead"
  | "engineering"
  | "quality"
  | "manufacturing"
  | "production"
  | "supply"
  | "management"
  | "external";
export type Screen =
  | "pai"
  | "work"
  | "inbox"
  | "sets"
  | "projects"
  | "knowledge"
  | "category"
  | "proposal"
  | "model"
  | "now"
  | "tasks"
  | "plan"
  | "engineering"
  | "builds"
  | "issues"
  | "release"
  | "stage"
  | "feedback"
  | "documents"
  | "settings";
export type WorkItem = {
  id: string;
  title: string;
  kind: string;
  project: string;
  owner: string;
  due: string;
  status: string;
  action: string;
  tier: "read" | "confirm" | "sign";
  roles: Role[];
  screen: Screen;
  description: string;
  facts: [string, string][];
  source: string;
  result: string;
};
export const roles: { id: Role; name: string; person: string; job: string }[] =
  [
    {
      id: "product",
      name: "产品经理",
      person: "林悦",
      job: "把用户需求变成可开发的产品定义",
    },
    {
      id: "lead",
      name: "项目负责人",
      person: "周宁",
      job: "推动依赖、承诺和跨专业交接",
    },
    {
      id: "engineering",
      name: "研发工程师",
      person: "陈舟",
      job: "完成设计、配置与变更验证",
    },
    {
      id: "quality",
      name: "品质 / 测试",
      person: "许澄",
      job: "接收准确的样件，独立判断验证结果",
    },
    {
      id: "manufacturing",
      name: "制造工程 / NPI",
      person: "高远",
      job: "准备工装与过程，承接制造导入",
    },
    {
      id: "production",
      name: "生产执行",
      person: "吴敏",
      job: "记录实际产出、异常与交样",
    },
    {
      id: "supply",
      name: "采购 / 供应",
      person: "沈禾",
      job: "核对供应承诺、到料与替代",
    },
    {
      id: "management",
      name: "管理者",
      person: "郑言",
      job: "处理跨项目取舍和具名决定",
    },
    {
      id: "external",
      name: "外部协作者",
      person: "协作方 A",
      job: "回应收到的交接与资料请求",
    },
  ];
export const screenNames: Record<Screen, string> = {
  pai: "小Pai",
  work: "我的工作",
  inbox: "收件箱",
  sets: "项目集",
  projects: "项目",
  knowledge: "知识",
  category: "品类",
  proposal: "立项提案",
  model: "型号与定义",
  now: "概览",
  tasks: "任务",
  plan: "计划",
  engineering: "产品与工程",
  builds: "试制与验证",
  issues: "问题与变更",
  release: "评审与交付",
  stage: "阶段与门禁",
  feedback: "现场反馈",
  documents: "文件",
  settings: "设置",
};
export const projectTabs: Screen[] = ["now", "tasks", "plan", "documents"];
export const projectScreens: Screen[] = [
  ...projectTabs,
  "engineering",
  "builds",
  "issues",
  "release",
  "stage",
  "feedback",
];
export const allInternal: Role[] = [
  "product",
  "lead",
  "engineering",
  "quality",
  "manufacturing",
  "production",
  "supply",
  "management",
];
export const projects = [
  {
    id: "P1",
    name: "便携充气泵 P1",
    category: "汽车充气泵",
    phase: "工程验证",
    lead: "周宁",
    health: "需关注",
    next: "验证评审",
    commitment: "11月06日",
    forecast: "11月09日",
    baseline: "11月05日",
    actual: "尚未发生",
    note: "噪声复测与试制件接收待完成",
    stages: ["立项", "定义", "工程验证", "试产", "交付"],
    at: 2,
  },
  {
    id: "S2",
    name: "桨板泵 S2 派生",
    category: "户外充气泵",
    phase: "定义",
    lead: "林悦",
    health: "正常",
    next: "规格冻结",
    commitment: "11月02日",
    forecast: "11月02日",
    baseline: "11月02日",
    actual: "尚未发生",
    note: "沿用平台，核对接口差异",
    stages: ["派生立项", "定义", "差异验证", "交付"],
    at: 1,
  },
  {
    id: "D3",
    name: "微型隔膜泵 D3",
    category: "微型泵",
    phase: "试产",
    lead: "高远",
    health: "待核对",
    next: "制造放行",
    commitment: "未提供",
    forecast: "未知",
    baseline: "11月12日",
    actual: "尚未发生",
    note: "制造接收结论待提供",
    stages: ["立项", "定义", "工程验证", "试产", "交付"],
    at: 3,
  },
];
export const items: WorkItem[] = [
  {
    id: "PD-041",
    title: "确认便携款的噪声目标与工况",
    kind: "要我决定",
    project: "P1",
    owner: "林悦",
    due: "今天",
    status: "待确认",
    action: "确认定义候选",
    tier: "confirm",
    roles: ["product"],
    screen: "engineering",
    description:
      "先明确适用场景，再确认噪声目标。当前值仍未知，不把竞品宣传值当作验证依据。",
    facts: [
      ["当前版本", "定义 v3"],
      ["目标值", "未知，待产品确认"],
      ["测试工况", "距离与负载待确认"],
      ["影响", "仅更新草稿，正式冻结仍需具名发布"],
    ],
    source: "用户声音 U-014 · 提案 v4 · 定义候选 C-07",
    result: "定义候选已在预览中确认，等待规格冻结。",
  },
  {
    id: "PD-042",
    title: "审阅 S2-L 接头变体提案",
    kind: "我的任务",
    project: "S2",
    owner: "林悦",
    due: "10月26日",
    status: "进行中",
    action: "保存提案修订",
    tier: "confirm",
    roles: ["product"],
    screen: "proposal",
    description: "核对接口、压力范围与原平台差距，再提交独立的立项评审。",
    facts: [
      ["父型号", "S2 · 定义 v1"],
      ["候选", "S2-L 派生提案 v1"],
      ["待核对", "接头兼容性"],
      ["客户资料", "私有，未进入共享品类"],
    ],
    source: "派生提案 v1 · 差异表 D-02",
    result: "修订已保存到本次预览，尚未提交 G0。",
  },
  {
    id: "PM-016",
    title: "协调噪声复测的测试资源",
    kind: "要我协调",
    project: "P1",
    owner: "周宁",
    due: "今天",
    status: "有冲突",
    action: "采用方案 A（保留承诺）",
    tier: "confirm",
    roles: ["lead"],
    screen: "plan",
    description:
      "两个项目占用同一消音室。比较替代时段后采用候选；对外承诺不会被自动改写。",
    facts: [
      ["方案 A", "保持复测顺序，预测延后 3 天"],
      ["方案 B", "更换时段，待品质确认资源"],
      ["原承诺", "11月06日，保持独立记录"],
      ["预测", "11月09日"],
    ],
    source: "计划 v3 · 资源冲突 R-08",
    result: "计划候选已采用；原承诺保留，需另行协商。",
  },
  {
    id: "PM-017",
    title: "等供应商确认第二批电机到样",
    kind: "等外部回复",
    project: "P1",
    owner: "周宁",
    due: "10月26日",
    status: "等外部",
    action: "查看供应回复",
    tier: "read",
    roles: ["lead", "supply"],
    screen: "plan",
    description: "供应商声称周一到样，当前尚无实到记录。",
    facts: [
      ["发出请求", "10月21日"],
      ["对方承诺", "10月26日"],
      ["实际到达", "尚未记录"],
      ["影响对象", "Build B-03 · Lot B"],
    ],
    source: "供应往来 E-12 · 独立承诺 COM-09",
    result: "查看供应回复，不改变到样事实。",
  },
  {
    id: "EN-032",
    title: "核对减振支架变更的工程影响",
    kind: "要我决定",
    project: "P1",
    owner: "陈舟",
    due: "今天",
    status: "待工程决定",
    action: "签署工程决定",
    tier: "sign",
    roles: ["engineering"],
    screen: "issues",
    description:
      "减振支架会影响安装接口与验证范围。工程决定和制造接收独立记录。",
    facts: [
      ["当前配置", "工程 E-06"],
      ["变更候选", "E-07 · 支架调整"],
      ["工程影响", "安装接口与耐久复测"],
      ["制造影响", "治具定位，待制造负责人确认"],
    ],
    source: "变更 CH-08 · 根因验证 I-12",
    result: "工程决定已在预览中签署；制造决定仍待完成。",
  },
  {
    id: "EN-033",
    title: "补齐本轮样机的装配制品",
    kind: "我的任务",
    project: "P1",
    owner: "陈舟",
    due: "10月24日",
    status: "进行中",
    action: "登记制品版本",
    tier: "confirm",
    roles: ["engineering"],
    screen: "engineering",
    description: "把已完成的装配图与 BOM 版本绑定到本轮工程配置。",
    facts: [
      ["装配图", "D-106 rev.C"],
      ["BOM", "BOM-018 v6"],
      ["固定配置", "E-06"],
      ["本轮样机", "按 E-06 执行，不自动跟随新版"],
    ],
    source: "工程配置 E-06 · 制品清单",
    result: "制品版本已登记到本次预览。",
  },
  {
    id: "QA-018",
    title: "接收 B-03 的首批 4 件样机",
    kind: "要我接收",
    project: "P1",
    owner: "许澄",
    due: "今天",
    status: "待接收",
    action: "确认接收 4 件",
    tier: "confirm",
    roles: ["quality"],
    screen: "builds",
    description:
      "仅接收已交付且身份明确的 Lot A；Lot B 的 2 件尚未交付，保持等待。",
    facts: [
      ["批次 / 样件", "Lot A · A01–A04"],
      ["工程 / 制造配置", "E-06 / M-04"],
      ["接收数量", "4 件；另 2 件未到"],
      ["资料", "装配记录、方法与样件标识可用"],
    ],
    source: "交接 H-024 · 样件台账 · E-06 / M-04",
    result: "4 件已接收，Lot B 的 2 件仍待交付。",
  },
  {
    id: "QA-020",
    title: "核对噪声复测的替代时段",
    kind: "要我协调",
    project: "P1",
    owner: "许澄",
    due: "今天",
    status: "待核对",
    action: "确认替代时段可用",
    tier: "confirm",
    roles: ["quality"],
    screen: "plan",
    description:
      "核对替代时段的环境、方法与人员，再交回项目负责人选择计划。此处仅演示已具备核对依据的场景。",
    facts: [
      ["候选时段", "11月05日–06日 · 仅为候选，尚未占用"],
      ["核对依据", "合成核对单 RC-08 · 环境与方法适用，品质人员可用"],
      ["样件", "正式执行仍须接收适用样件"],
      ["核对边界", "只确认替代资源可用，不采用计划、不改写承诺"],
    ],
    source: "资源冲突 R-08 · 合成核对单 RC-08",
    result:
      "替代时段已核对可用（预览），等待周宁选择计划；尚未预约或开始测试。",
  },
  {
    id: "QA-019",
    title: "独立验证 I-09 的低温启机整改",
    kind: "要我验证",
    project: "P1",
    owner: "许澄",
    due: "10月27日",
    status: "待复测",
    action: "提交验证结论",
    tier: "sign",
    roles: ["quality"],
    screen: "issues",
    description:
      "完成动作不代表问题关闭；用新一轮实际样件与测试原值作出独立结论。",
    facts: [
      ["问题", "I-09 · 低温启机"],
      ["整改实施", "B-02 已采用 E-05 / M-03"],
      ["测试运行", "TR-05 原值已完整返回，待独立判断"],
      ["问题状态", "保持未关闭"],
    ],
    source: "I-09 → CH-06 → E-05 → B-02 → TR-05",
    result: "验证结论已在预览中提交；关闭问题仍为独立动作。",
  },
  {
    id: "MF-011",
    title: "决定新支架方案的制造接收",
    kind: "要我决定",
    project: "P1",
    owner: "高远",
    due: "今天",
    status: "待制造决定",
    action: "签署制造决定",
    tier: "sign",
    roles: ["manufacturing"],
    screen: "issues",
    description: "检查治具定位、作业方法与检验准备，只对制造适用范围作出决定。",
    facts: [
      ["治具", "J-04 需改版"],
      ["过程文件", "WI-06 候选"],
      ["工程决定", "独立记录"],
      ["适用范围", "后续 Build B-04，已制批次不追改"],
    ],
    source: "CH-08 · 制造影响清单",
    result: "制造决定已在预览中签署；后续实施仍需登记。",
  },
  {
    id: "MF-013",
    title: "补齐 P1 的制造准备记录",
    kind: "我的任务",
    project: "P1",
    owner: "高远",
    due: "10月26日",
    status: "待补齐",
    action: "保存制造准备记录",
    tier: "confirm",
    roles: ["manufacturing"],
    screen: "builds",
    description: "逐项记录工具、方法、人员、物料和检验准备；未完成项保留。",
    facts: [
      ["当前配置", "E-06 / M-04"],
      ["候选改进", "E-07 / M-05 待分别决定"],
      ["检验", "噪声方法待签署"],
      ["后续活动", "待专业决定后准备"],
    ],
    source: "P1 · 制造准备清单",
    result: "制造准备记录已保存；未完成项保留。",
  },
  {
    id: "MF-012",
    title: "核对 D3 试产的工装与检验准备",
    kind: "我的任务",
    project: "D3",
    owner: "高远",
    due: "10月28日",
    status: "待补齐",
    action: "保存准备记录",
    tier: "confirm",
    roles: ["manufacturing"],
    screen: "builds",
    description:
      "明确工具、工艺、人员、物料与检验的各自准备状态，不生成综合得分。",
    facts: [
      ["工装", "定位夹具已试用"],
      ["人员", "作业培训待记录"],
      ["检验", "抽检方法待签署"],
      ["范围", "Pilot P-02"],
    ],
    source: "制造准备 M-05 · Pilot P-02",
    result: "准备记录已保存；人员与检验缺项保留。",
  },
  {
    id: "PR-004",
    title: "记录 B-03 第二批的实制与交样",
    kind: "我的任务",
    project: "P1",
    owner: "吴敏",
    due: "今天",
    status: "待交样",
    action: "登记实际交样",
    tier: "confirm",
    roles: ["production"],
    screen: "builds",
    description: "按真实生产结果登记 Lot B 两件样机；已交首批不重复交样。",
    facts: [
      ["本批数量", "2 件 · B01–B02"],
      ["实际配置", "E-06 / M-04"],
      ["首批", "Lot A 已独立交样"],
      ["接收方", "许澄 · 品质"],
    ],
    source: "Build B-03 · Lot B · 装配记录",
    result: "Lot B 已登记交样，等待品质独立接收。",
  },
  {
    id: "SU-007",
    title: "核对供应商电机承诺与实到",
    kind: "我的任务",
    project: "P1",
    owner: "沈禾",
    due: "今天",
    status: "待核对",
    action: "登记供应情况",
    tier: "confirm",
    roles: ["supply"],
    screen: "plan",
    description: "对方回复是承诺来源，入厂点收才是实际到达；分别保留。",
    facts: [
      ["对方承诺", "10月26日"],
      ["实到", "尚未点收"],
      ["替代料", "尚未批准"],
      ["影响", "第二批装配"],
    ],
    source: "供应回复 E-12 · 点收原件待提供",
    result: "供应情况已记录，实到仍为未知。",
  },
  {
    id: "MG-003",
    title: "决定两项目共享测试资源的取舍",
    kind: "要我决定",
    project: "P1",
    owner: "郑言",
    due: "今天",
    status: "待决定",
    action: "签署取舍决定",
    tier: "sign",
    roles: ["management"],
    screen: "plan",
    description:
      "评估产品交期与验证风险，批准明确的优先顺序。具体计划仍回到项目办理。",
    facts: [
      ["冲突", "P1 与 S2 共用消音室"],
      ["时间", "11月02日–11月04日"],
      ["涉及人员", "品质资源 1 组"],
      ["方案", "P1 优先，S2 调整候选待确认"],
    ],
    source: "资源冲突 R-08 · 两项目计划候选",
    result: "取舍决定已记录；项目负责人分别接续计划。",
  },
  {
    id: "EX-002",
    title: "回应收到的样品交付包",
    kind: "要我接收",
    project: "P1",
    owner: "协作方 A",
    due: "10月28日",
    status: "待回应",
    action: "确认收到固定包",
    tier: "sign",
    roles: ["external"],
    screen: "release",
    description: "仅能查看向你授权的固定包。收到资料与业务生效是两个独立状态。",
    facts: [
      ["固定包", "PKG-04 · v2"],
      ["用途", "客户样品评估"],
      ["授权内容", "规格摘要、操作说明、样品标识"],
      ["内部资料", "不在本次授权范围"],
    ],
    source: "外部交接 OUT-08 · PKG-04 v2",
    result: "收到回执已在预览中记录，业务生效仍待对账。",
  },
];
export const knowledge = [
  [
    "K-014",
    "低温启机的测量边界",
    "已发布",
    "汽车充气泵 · 指定低温工况",
    "历史方法验证 TR-02",
  ],
  ["K-019", "低温启机的测量方法", "候选", "桨板泵 · 工况待验证", "TR-05"],
  [
    "K-006",
    "旧版接头装配经验",
    "已失效",
    "不再推荐用于新型号",
    "被 K-021 取代",
  ],
];
export const coverage = [
  ["个人工作", "按责任分诊、资源协调、独立承诺、办理结果", "work"],
  ["品类与立项", "共享知识、客户原件、标准匹配、提案四视图、G0", "category"],
  ["型号与定义", "定义版本、平台关联、派生差异、冻结", "model"],
  [
    "项目推进",
    "项目三视图、任务列表/看板、概览、计划、文件；专业工作按需展开",
    "projects",
  ],
  ["计划与供应", "工作包、依赖、四时间、资源、承诺、外部等待", "plan"],
  ["工程与制造", "工程配置、制品/BOM、制造准备、实际双配置", "engineering"],
  ["实物与验证", "Build、Lot、样件、分批接收、测试、原值与处置", "builds"],
  ["问题与迭代", "遏制、根因、措施、双线影响、双专业决定、独立验证", "issues"],
  ["制造与交付", "Pilot、固定包、专业放行、外部回执与生效", "release"],
  ["现场与知识", "现场反馈、正式改进计划、知识候选/发布/失效", "feedback"],
  ["资源与协作", "计划内资源需求、跨项目取舍、本人协调待办", "plan"],
  [
    "小Pai与治理",
    "上下文/技能、会话、后台运行、T1确认/T2具名、恢复",
    "settings",
  ],
] as const;
