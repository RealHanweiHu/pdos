import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ProjectWorkSections, type ProjectWorkSection } from "./project-work-sections";

const sections = (): ProjectWorkSection[] => [
  { id: "primary", title: "当前计划", children: <p>正式计划内容</p> },
  {
    id: "resources",
    title: "资源预约",
    description: "按需办理设备和人员预约。",
    queryKeys: ["reservation_id"],
    hashPrefixes: ["#reservation-"],
    children: <label>办理说明<input defaultValue="" /></label>,
  },
];
const disclosure = (title: string) => screen.getByText(title).closest("details")!;

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/projects");
});

describe("项目工作分组", () => {
  it("opens the first work group by default and respects explicit defaults", () => {
    const view = render(<ProjectWorkSections label="计划办理" sections={sections()} />);
    expect(disclosure("当前计划").open).toBe(true);
    expect(disclosure("资源预约").open).toBe(false);
    view.unmount();
    render(<ProjectWorkSections label="计划办理" sections={sections()} defaultOpen={["resources"]} />);
    expect(disclosure("当前计划").open).toBe(false);
    expect(disclosure("资源预约").open).toBe(true);
  });

  it("opens receipt query groups even when a selector value is empty", () => {
    window.history.replaceState(null, "", "/projects?reservation_id=");
    render(<ProjectWorkSections label="计划办理" sections={sections()} />);
    expect(disclosure("资源预约").open).toBe(true);
    expect(disclosure("当前计划").open).toBe(true);
  });

  it("keeps mounted form values and a manual collapse across content refreshes", () => {
    window.history.replaceState(null, "", "/projects?reservation_id=original");
    const view = render(<ProjectWorkSections label="计划办理" sections={sections()} />);
    const field = screen.getByLabelText("办理说明") as HTMLInputElement;
    field.value = "尚未提交的办理说明";
    disclosure("资源预约").open = false;
    view.rerender(<ProjectWorkSections label="计划办理" sections={sections()} />);
    expect(disclosure("资源预约").open).toBe(false);
    expect(screen.getByLabelText("办理说明")).toBe(field);
    expect(field.value).toBe("尚未提交的办理说明");
    disclosure("资源预约").open = true;
    expect(field).toBeVisible();
  });

  it("responds to browser history and fragment navigation without rewriting the link", () => {
    render(<ProjectWorkSections label="计划办理" sections={sections()} />);
    window.history.replaceState(null, "", "/projects?reservation_id=original#unchanged");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(disclosure("资源预约").open).toBe(true);
    expect(window.location.search).toBe("?reservation_id=original");
    expect(window.location.hash).toBe("#unchanged");
    disclosure("资源预约").open = false;
    window.history.replaceState(null, "", "/projects#reservation-original");
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(disclosure("资源预约").open).toBe(true);
  });

  it("reveals a deferred receipt target and its nested disclosures", async () => {
    window.history.replaceState(null, "", "/projects#%E5%8E%9F%E5%9B%9E%E6%89%A7");
    const view = render(<ProjectWorkSections label="专业工作" sections={sections()} />);
    const revised = sections();
    revised[1].children = <details><summary>原记录</summary><p id="原回执">实际办理结果</p></details>;
    view.rerender(<ProjectWorkSections label="专业工作" sections={revised} />);
    await waitFor(() => {
      expect(disclosure("资源预约").open).toBe(true);
      expect(screen.getByText("原记录").closest("details")!.open).toBe(true);
      expect(screen.getByText("实际办理结果")).toBeVisible();
    });
  });

  it("does not expand a group for an anchor outside the workspace", () => {
    window.history.replaceState(null, "", "/projects#outside-receipt");
    render(<><p id="outside-receipt">其他工作区</p><ProjectWorkSections label="计划办理" sections={sections()} /></>);
    expect(disclosure("资源预约").open).toBe(false);
  });
});
