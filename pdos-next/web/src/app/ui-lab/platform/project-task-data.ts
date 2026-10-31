export const statuses = ["待开始", "进行中", "受阻", "已完成"] as const;
export const priorities = ["高", "中", "低"] as const;
export type TaskStatus = (typeof statuses)[number];
export type NpiTaskTemplate = {
  key: string;
  projectType: string;
  phase: string;
  phaseCode: string;
  taskId: string;
  title: string;
  originalTitle: string;
  description: string;
  deliverables: string[];
  requirements: string[];
  isGate: boolean;
};
export type ProjectTask = {
  id: string;
  project: string;
  title: string;
  owner: string;
  status: TaskStatus;
  priority: (typeof priorities)[number];
  due: string;
  description: string;
  origin: "npi" | "extra";
  phase: string;
  template?: NpiTaskTemplate;
  related?: string;
};
export const taskProfiles: Record<
  string,
  { type: string; currentPhase: string }
> = {
  P1: { type: "npd", currentPhase: "EVT 工程验证" },
  S2: { type: "derivative", currentPhase: "设计" },
  D3: { type: "npd", currentPhase: "PVT 试产验证" },
};
// Names, phases and outputs come from the guide. People, progress and dates below
// are synthetic preview instances, never inferred evidence of NPI approval.
const evt: Record<
  string,
  { owner: string; status: TaskStatus; due: string; related?: string }
> = {
  e1: { owner: "吴敏", status: "进行中", due: "2026-10-26", related: "PR-004" },
  e2: { owner: "许澄", status: "进行中", due: "2026-10-28" },
  e3: { owner: "许澄", status: "受阻", due: "2026-11-06", related: "PM-016" },
  e4: { owner: "陈舟", status: "进行中", due: "2026-10-28" },
  e5: { owner: "陈舟", status: "进行中", due: "2026-10-30", related: "EN-032" },
  e6: { owner: "陈舟", status: "待开始", due: "2026-11-02" },
  e7: { owner: "周宁", status: "待开始", due: "2026-11-06" },
};
export function seedProjectTasks(catalog: NpiTaskTemplate[]): ProjectTask[] {
  const tasks = Object.entries(taskProfiles).flatMap(([project, profile]) => {
    const templates = catalog.filter(
      (template) => template.projectType === profile.type,
    );
    const phases = [...new Set(templates.map((template) => template.phase))];
    const current = phases.indexOf(profile.currentPhase);
    return templates.map((template, i): ProjectTask => {
      const phaseIndex = phases.indexOf(template.phase);
      const active = phaseIndex === current;
      const instance =
        project === "P1" && active ? evt[template.taskId] : undefined;
      return {
        id: `${project}-${String(i + 1).padStart(3, "0")}`,
        project,
        title: template.title,
        description: template.description,
        origin: "npi",
        phase: template.phase,
        template,
        owner:
          instance?.owner ??
          (active ? (project === "S2" ? "陈舟" : "高远") : "待分配"),
        status:
          instance?.status ??
          (phaseIndex < current
            ? "已完成"
            : active && !template.isGate
              ? "进行中"
              : "待开始"),
        priority: "中",
        due: instance?.due ?? "",
        related: instance?.related,
      };
    });
  });
  return [
    ...tasks,
    {
      id: "P1-X01",
      project: "P1",
      title: "追加噪声复测",
      owner: "许澄",
      status: "受阻",
      priority: "高",
      due: "2026-11-06",
      description: "因本轮噪声结果新增的专项复测，补充到 EVT 性能验证。",
      origin: "extra",
      phase: "EVT 工程验证",
      related: "PM-016",
    },
    {
      id: "P1-X02",
      project: "P1",
      title: "补充第二批电机到样确认",
      owner: "沈禾",
      status: "进行中",
      priority: "中",
      due: "2026-10-26",
      description: "项目执行中额外创建，确认供应商承诺与实际到样。",
      origin: "extra",
      phase: "EVT 工程验证",
      related: "SU-007",
    },
  ];
}
