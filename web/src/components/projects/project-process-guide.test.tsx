import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Project } from "./project-types";
import { ProjectProcessGuide } from "./project-process-guide";
import { NPD_PROCESS_RULES } from "./project-process-rules";

const project = (code = "evt", workflow = "npd-project", version = 1) => ({
  workflow: { code: workflow, version }, current_stage: { code },
}) as Project;
afterEach(cleanup);

describe("NPD management process", () => {
  it.each(NPD_PROCESS_RULES)("shows current $code responsibilities and routes to actual work surfaces", (stage) => {
    const open = vi.fn();
    render(<ProjectProcessGuide project={project(stage.code)} onOpen={open} />);
    expect(screen.getByRole("heading", { name: `现在做什么 · ${stage.title}` })).toBeInTheDocument();
    expect(screen.getByText(stage.purpose)).toBeInTheDocument();
    const buttons = screen.getAllByRole("button");
    stage.steps.forEach((step, index) => {
      expect(screen.getByText(`职责：${step.owner}`)).toBeInTheDocument();
      expect(screen.getByText(`应形成的记录：${step.record}`)).toBeInTheDocument();
      fireEvent.click(buttons[index]);
      expect(open).toHaveBeenLastCalledWith(step.tab);
    });
    fireEvent.click(screen.getByRole("button", { name: "查看阶段评审与阻塞项" }));
    expect(open).toHaveBeenLastCalledWith("gates");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
  it.each([["evt", "obt", 1], ["unknown", "npd", 1], ["evt", "npd", 2]] as const)("does not apply NPD v1 to %s/%s/v%s", (stage, workflow, version) => {
    render(<ProjectProcessGuide project={project(stage, workflow, version)} onOpen={vi.fn()} />);
    expect(screen.queryByRole("region", { name: "项目管理流程" })).not.toBeInTheDocument();
  });
  it("changes instructions when the current stage changes", () => {
    const open = vi.fn();
    const { rerender } = render(<ProjectProcessGuide project={project("planning")} onOpen={open} />);
    expect(screen.getByText("应形成的记录：规格版本、参数与单位、客户要求、验证方法及待澄清项")).toBeInTheDocument();
    rerender(<ProjectProcessGuide project={project("evt")} onOpen={open} />);
    expect(screen.queryByText("应形成的记录：规格版本、参数与单位、客户要求、验证方法及待澄清项")).not.toBeInTheDocument();
    expect(screen.getByText("应形成的记录：实际批次数量、样机编号、BOM/硬件/固件配置及用途")).toBeInTheDocument();
  });
});
