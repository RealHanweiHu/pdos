import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import template from "./npd-disciplinary-task-template.json";
import { ProjectDisciplinaryGuide } from "./project-disciplinary-guide";

afterEach(cleanup);

function ancestors(code: string, visited = new Set<string>()): Set<string> {
  const task = template.tasks.find((item) => item.code === code);
  if (!task) throw new Error(`Missing task ${code}`);
  if (visited.has(code)) throw new Error(`Dependency cycle at ${code}`);
  const next = new Set([...visited, code]);
  return new Set(task.depends_on.flatMap((dependency) => [dependency, ...ancestors(dependency, next)]));
}

describe("four-discipline dependency baseline", () => {
  it("requires ID planning at initiation but keeps later ID freezing separate", () => {
    render(<ProjectDisciplinaryGuide stageCode="concept" />);
    expect(screen.getByText("立项先确认 ID 专项计划")).toBeInTheDocument();
    const current = screen.getByText("查看本阶段任务依赖基线（2 项）").closest("details")!;
    expect(within(current).getByText("ID-PLAN · 确认 ID 专项计划")).toBeInTheDocument();
    expect(within(current).queryByText("ID-FREEZE · 确认外观样并冻结 ID")).not.toBeInTheDocument();
    expect(screen.getByText(/这是任务拆分基线，尚未自动创建本项目任务/)).toBeInTheDocument();
  });
  it("uses a complete acyclic dependency graph with explicit outputs and recipients", () => {
    const codes = template.tasks.map((task) => task.code);
    expect(new Set(codes).size).toBe(codes.length);
    const stages = ["concept", "planning", "design", "evt", "dvt", "pvt", "mp"];
    for (const task of template.tasks) {
      expect(task.output.length).toBeGreaterThan(0);
      expect(task.receiver.length).toBeGreaterThan(0);
      expect(ancestors(task.code).has(task.code)).toBe(false);
      for (const code of task.depends_on) {
        const dependency = template.tasks.find((item) => item.code === code)!;
        expect(stages.indexOf(dependency.stage)).toBeLessThanOrEqual(stages.indexOf(task.stage));
      }
    }
  });
  it("allows pre-research and firmware development while ID is still running", () => {
    for (const code of ["MD-PRE", "EE-PRE", "FW-PRE", "ARCH"]) {
      expect(ancestors(code).has("ID-FREEZE")).toBe(false);
      expect(ancestors(code).has("ID-CONCEPT")).toBe(false);
    }
    expect(ancestors("FW-BASE").has("ID-FREEZE")).toBe(false);
    expect(ancestors("FW-BASE").has("EE-PCB")).toBe(false);
  });
  it("requires frozen geometry for PCB and both board and firmware for bring-up", () => {
    expect(ancestors("EE-PCB").has("ID-FREEZE")).toBe(true);
    expect(ancestors("EE-PCB").has("MD-ENVELOPE")).toBe(true);
    expect(ancestors("EE-PCB").has("MD-DETAIL")).toBe(false);
    for (const code of ["EE-PCB", "FW-BASE"]) expect(ancestors("FW-BRINGUP").has(code)).toBe(true);
    for (const code of ["ID-FREEZE", "MD-DETAIL", "EE-PCB", "FW-BRINGUP"]) expect(ancestors("EVT-BUILD").has(code)).toBe(true);
  });
});
