"use client";

import { Button } from "@/components/ui/button";
import type { Project } from "./project-types";
import { ProjectDisciplinaryGuide } from "./project-disciplinary-guide";
import { NPD_PROCESS_RULES, NPD_PROCESS_VERSION, processRule, type ProcessTab } from "./project-process-rules";

const TAB_LABELS: Record<ProcessTab, string> = {
  "work-items": "工作项", engineering: "工程·变更", quality: "试制·测试·质量",
  gates: "Gate·交付物", documents: "文档·知识", decisions: "例会·决策",
};

export function ProjectProcessGuide({ project, onOpen }: { project: Project; onOpen: (tab: ProcessTab) => void }) {
  const rule = processRule(project.workflow, project.current_stage.code);
  if (!rule) return null;
  return (
    <section aria-label="项目管理流程" className="space-y-4 rounded-lg border bg-card p-4">
      <div>
        <p className="text-xs text-muted-foreground">{NPD_PROCESS_VERSION} · 多人协作</p>
        <h2 className="mt-1 font-semibold">现在做什么 · {rule.title}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{rule.purpose}</p>
      </div>
      <ol className="space-y-3">
        {rule.steps.map((step, index) => (
          <li key={step.title} className="rounded-lg border p-3">
            <p className="text-sm font-medium">{index + 1}. {step.title}</p>
            <p className="mt-1 text-xs text-muted-foreground">职责：{step.owner}</p>
            <p className="mt-2 text-sm">应形成的记录：{step.record}</p>
            <Button type="button" variant="outline" size="sm" className="mt-2" onClick={() => onOpen(step.tab)}>前往{TAB_LABELS[step.tab]}</Button>
          </li>
        ))}
      </ol>
      <div className="space-y-2 border-t pt-3">
        <h3 className="text-sm font-medium">提交阶段评审前，由负责人核对</h3>
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {rule.review.map((item) => <li key={item}>{item}</li>)}
        </ul>
        <p className="text-xs text-muted-foreground">以上是操作清单，不代表已经完成。实际阻塞项和签核状态请在阶段评审中查看；当前 Gate 批准后才能进入下一阶段。</p>
        <Button type="button" size="sm" onClick={() => onOpen("gates")}>查看阶段评审与阻塞项</Button>
      </div>
      <ProjectDisciplinaryGuide stageCode={rule.code} />
      <details className="border-t pt-3">
        <summary className="cursor-pointer text-sm font-medium">查看完整流程与协作规则</summary>
        <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm">
          {NPD_PROCESS_RULES.map((stage) => <li key={stage.code}><strong>{stage.title}</strong>：{stage.purpose}</li>)}
        </ol>
        <p className="mt-3 text-sm">项目负责人协调推进；每个任务有唯一负责人，研发提供设计与整改证据，品质组织验证。流程按实际业务人员分工，系统开发者不自动承担这些职责。</p>
        <p className="mt-2 text-sm">自行车泵、汽车泵、帐篷泵使用各自的项目测试模板。新增功能和客户特殊要求先形成差异建议，再经相关负责人确认；AI 不代替评审或生成实测结论。</p>
        <p className="mt-2 text-sm">每天从“我的工作”处理待办、阻塞和待验证事项；固定节奏检查延期、风险和阶段准备。需求或设计变化通过变更记录处理，保留旧版本。</p>
      </details>
    </section>
  );
}
