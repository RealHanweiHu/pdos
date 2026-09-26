/** Operating instructions for the existing NPD v1 workflow; not a new Gate policy. */
export type ProcessTab = "work-items" | "engineering" | "quality" | "gates" | "documents" | "decisions";
export type ProcessStep = { title: string; owner: string; record: string; tab: ProcessTab };
export type StageRule = { code: string; title: string; purpose: string; steps: ProcessStep[]; review: string[] };
export const NPD_PROCESS_VERSION = "NPD 管理流程 v1.1";
export const NPD_PROCESS_RULES: StageRule[] = [
  {
    code: "concept", title: "概念与立项", purpose: "说清楚为谁做、解决什么问题、是否值得投入。",
    steps: [
      { title: "整理需求与产品边界", owner: "产品负责人", record: "客户或市场需求、使用场景、产品类型、功能范围及明确不做的内容", tab: "documents" },
      { title: "单列 ID 周期并评估四专业可行性", owner: "ID、结构、硬件、嵌入式负责人", record: "ID 来源、负责人、预计工期、评审与反馈等待、冻结日期；各专业风险和可并行预研任务", tab: "work-items" },
      { title: "确认 ID 专项计划并作出立项决定", owner: "项目负责人组织，产品与四专业负责人评审", record: "立项依据、ID 计划与确认人、四专业分工、关键依赖及初始进度基线", tab: "decisions" },
    ],
    review: ["需求来源与范围清楚，关键未知项有后续验证安排", "ID 专项计划、资源、评审/反馈周期和冻结目标已经确认；未决项记录在立项决策中", "已指定项目负责人和四专业负责人，立项计划确认不等于 ID 方案已冻结"],
  },
  {
    code: "planning", title: "规格与计划", purpose: "在设计开始前约定做成什么样、怎样验证、由谁完成。",
    steps: [
      { title: "确认规格与验收方法", owner: "产品与研发负责人", record: "规格版本、参数与单位、客户要求、验证方法及待澄清项", tab: "engineering" },
      { title: "拆分四专业任务与交接依赖", owner: "项目负责人会同 ID、结构、硬件、嵌入式负责人", record: "每项任务的唯一负责人、开始/截止日期、前置任务、输入版本、交付记录和接收方；ID 单列周期", tab: "work-items" },
      { title: "选择项目测试基线", owner: "品质负责人会同研发", record: "产品类型对应的测试模板、适用项、排除理由和项目特殊要求", tab: "quality" },
    ],
    review: ["规格和测试范围已由相关负责人核对", "任务负责人、依赖及关键日期明确，风险有处理安排"],
  },
  {
    code: "design", title: "设计与设计评审", purpose: "把已确认的规格变成可制作、可验证的设计版本。",
    steps: [
      { title: "完成 ID、结构、硬件与嵌入式设计", owner: "ID、结构、硬件、嵌入式各自负责人", record: "ID 冻结确认、结构图档/板框、原理图/PCB、BOM 与固件的兼容版本引用", tab: "engineering" },
      { title: "按接口依赖完成专业评审与联调", owner: "四专业负责人共同评审，品质与制造参与", record: "板框/器件空间、PIN/协议、结构装配、硬件与固件联调结论；延期或变更对后续任务的影响", tab: "work-items" },
      { title: "确认工程样机输入", owner: "研发负责人", record: "用于制作 EVT 样机的设计/BOM/固件版本及未解决事项", tab: "documents" },
    ],
    review: ["工程样机的设计输入可定位到明确版本", "关键设计问题已有结论，遗留事项有负责人和验证安排"],
  },
  {
    code: "evt", title: "EVT 工程验证", purpose: "用工程样机验证核心功能与技术方案。",
    steps: [
      { title: "登记试制批次与样机", owner: "研发负责人", record: "实际批次数量、样机编号、BOM/硬件/固件配置及用途", tab: "quality" },
      { title: "执行测试并核对报告", owner: "测试执行人，品质复核", record: "原始读数、测试日期、判据、结果和来源；导入后先核对再确认", tab: "quality" },
      { title: "处理失败与复测", owner: "问题负责人整改，指定验证人复核", record: "失败问题、原因、措施、受影响版本及复测证据", tab: "work-items" },
    ],
    review: ["已完成试制并有可追溯样机和本阶段审核报告", "失败、阻塞项与样机会签按 Gate 就绪检查处理", "测试覆盖和未测项逐项核对，不用上传文件代替测试完成"],
  },
  {
    code: "dvt", title: "DVT 设计验证", purpose: "验证拟定型设计对完整规格与可靠性要求的符合情况。",
    steps: [
      { title: "冻结本轮验证对象与清单", owner: "研发与品质负责人", record: "本轮样机配置、完整规格及功能/可靠性/适用认证验证清单", tab: "quality" },
      { title: "完成验证与差异处置", owner: "品质组织测试，研发解决问题", record: "整机与可靠性报告、缺项、不适用理由、失败问题和复测结果", tab: "quality" },
      { title: "确认定型及试产输入", owner: "产品、研发与品质共同评审", record: "设计定型版本、变更决策和试产前必须完成的事项", tab: "decisions" },
    ],
    review: ["验证结果对应拟定型版本，范围与证据已核对", "本阶段 Build、样机、审核报告与适用认证满足 Gate 要求", "遗留问题的处置不会绕过已有硬性阻塞"],
  },
  {
    code: "pvt", title: "PVT 试产验证", purpose: "验证设计能否稳定制造、检验并交付。",
    steps: [
      { title: "核对试产准备", owner: "项目负责人组织制造、研发与品质", record: "冻结 BOM、SOP/治具/检验文件引用、物料与试产计划", tab: "documents" },
      { title: "记录试产结果并闭环问题", owner: "制造执行，品质统计，研发配合", record: "实际投入/产出、不良与原因、工艺调整和再验证记录", tab: "quality" },
      { title: "完成转产交接评审", owner: "项目负责人组织各接收方", record: "交接清单、接收人、版本、认证状态和遗留任务；ERP 交接引用", tab: "gates" },
    ],
    review: ["试产结论有实际数据及证据，项目约定的目标经过评审", "制造、品质及研发的转产交接项有接收结论", "条件放行事项明确负责人、期限和关闭证据，硬性阻塞未被跳过"],
  },
  {
    code: "mp", title: "量产稳定与移交", purpose: "跟踪量产初期表现，并把持续维护责任交给接收方。",
    steps: [
      { title: "跟踪量产初期质量", owner: "制造与品质负责人", record: "量产批次引用、质量反馈、异常处置和趋势记录", tab: "quality" },
      { title: "核对遗留任务与客户反馈", owner: "项目负责人协调对应责任人", record: "未结问题的负责人、期限、后续接收方及客户承诺", tab: "work-items" },
      { title: "完成项目移交与复盘", owner: "项目负责人及接收方", record: "最终版本与资料索引、维护责任、交接结论和可复用经验草稿", tab: "documents" },
    ],
    review: ["稳定观察的范围和结论有记录，持续维护责任已接收", "完成移交评审后再处理项目完成状态，关闭结论可追溯"],
  },
];

export function processRule(workflow: { code: string; version: number }, stageCode: string) {
  if (workflow.code.toLowerCase().split("-")[0] !== "npd" || workflow.version !== 1) return undefined;
  return NPD_PROCESS_RULES.find((stage) => stage.code === stageCode);
}
