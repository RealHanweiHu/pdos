import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ProjectTestTemplate, TestCoverageView } from "./project-test-template";

const { fetchTemplates, saveTemplate } = vi.hoisted(() => ({ fetchTemplates: vi.fn(), saveTemplate: vi.fn() }));
vi.mock("./project-npi-api", () => ({ fetchTestTemplates: fetchTemplates, saveTestTemplate: saveTemplate }));

const template = {
  id: "bicycle", version: 1, product_type: "锂电自行车泵", name: "自行车模板",
  items: [
    { key: "pressure", title: "气压", required: true, method: "测气压", acceptance_criteria: "按规格" },
    { key: "light", title: "照明", required: true, method: "开关", acceptance_criteria: "按规格" },
  ],
};

describe("test template configuration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchTemplates.mockResolvedValue({ templates: [template], stages: [{ id: "stage", code: "evt", name: "EVT" }] });
    saveTemplate.mockResolvedValue({});
  });

  it("shows unknown coverage without a template, never zero missing or 100 percent", () => {
    render(<TestCoverageView />);
    expect(screen.getByText("尚未选择测试模板，无法判断必测覆盖。")).toBeInTheDocument();
    expect(screen.queryByText(/100%/)).not.toBeInTheDocument();
  });

  it("requires an exclusion reason and saves the explicit type and version", async () => {
    const onSaved = vi.fn().mockResolvedValue(undefined);
    render(<ProjectTestTemplate projectId="project" planId="plan" onSaved={onSaved} />);
    fireEvent.click(screen.getByRole("button", { name: "选择测试模板" }));
    fireEvent.change(await screen.findByLabelText("产品类型与模板版本"), { target: { value: "bicycle:1" } });
    fireEvent.click(screen.getByLabelText("照明不适用于本项目"));
    const confirm = screen.getByRole("button", { name: "确认模板与项目差异" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("不适用理由（照明）"), { target: { value: "本项目没有照明功能" } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    await waitFor(() => expect(saveTemplate).toHaveBeenCalledWith("project", {
      template_id: "bicycle", version: 1, product_type: "锂电自行车泵",
      exclusions: [{ key: "light", reason: "本项目没有照明功能" }],
    }, { planId: "plan" }));
    expect(onSaved).toHaveBeenCalled();
  });

  it("keeps failure separate from passed coverage and shows the exclusion reason", () => {
    render(<TestCoverageView coverage={{ status: "configured", template_name: "自行车", version: 1,
      required: 29, covered: 1, passed: 0, failed: 1, missing: 28, not_applicable: 1,
      coverage_percent: 3.4, items: [{ key: "light", title: "照明", state: "not_applicable", reason: "不带照明灯" }],
    }} />);
    expect(screen.getByText(/通过 0 项 · 失败 1 项/)).toBeInTheDocument();
    expect(screen.getByText("照明：不适用；不带照明灯")).toBeInTheDocument();
  });
});
