import template from "./npd-disciplinary-task-template.json";

export function ProjectDisciplinaryGuide({ stageCode }: { stageCode: string }) {
  const byCode = new Map(template.tasks.map((task) => [task.code, task]));
  const current = template.tasks.filter((task) => task.stage === stageCode);
  function rows(tasks: typeof template.tasks) {
    return tasks.map((task) => (
      <li key={task.code} className="space-y-1 border-t py-3 first:border-t-0">
        <p className="text-sm font-medium">{task.code} · {task.title}</p>
        <p className="text-xs text-muted-foreground">负责专业：{task.discipline}</p>
        <p className="text-sm">前置：{task.depends_on.length ? task.depends_on.map((code) => `${code} ${byCode.get(code)?.title ?? code}`).join("；") : "无任务前置，从已登记的需求开始"}</p>
        <p className="text-sm">交付：{task.output}</p>
        <p className="text-xs text-muted-foreground">接收：{task.receiver}</p>
      </li>
    ));
  }
  return (
    <section aria-label="四专业任务依赖" className="space-y-3 border-t pt-3">
      <h3 className="text-sm font-medium">ID · 结构 · 硬件 · 嵌入式</h3>
      {["concept", "planning", "design"].includes(stageCode) ? (
        <div className="space-y-2">
          <p className="text-sm font-medium">立项先确认 ID 专项计划</p>
          <ul className="list-disc space-y-1 pl-5 text-sm">{template.initiation_checks.map((item) => <li key={item}>{item}</li>)}</ul>
          <p className="text-xs text-muted-foreground">立项确认 ID 的计划与决策人，后续再完成方案冻结。ID 周期单列，冻结延期时重新评估结构、PCB 和样机日期，保留原计划。</p>
        </div>
      ) : null}
      <p className="text-sm">结构、电路和固件预研可并行；结构板框发布后，结构细化与 PCB 可并行。固件基础开发按接口开展，目标板联调等待硬件样板和固件就绪。</p>
      <details>
        <summary className="cursor-pointer py-2 text-sm font-medium">查看本阶段任务依赖基线（{current.length} 项）</summary>
        <ul>{rows(current)}</ul>
      </details>
      <details>
        <summary className="cursor-pointer py-2 text-sm font-medium">查看完整任务依赖基线（{template.tasks.length} 项）</summary>
        <ul>{rows(template.tasks)}</ul>
      </details>
      <p className="text-xs text-muted-foreground">这是任务拆分基线，尚未自动创建本项目任务。项目负责人需在工作项中落实具名负责人、日期、前置任务和版本交接；ID 计划核对目前由立项评审人执行。</p>
    </section>
  );
}
