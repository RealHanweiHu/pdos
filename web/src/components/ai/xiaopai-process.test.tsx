import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { XiaopaiProcess, type ReplyProcess } from "./xiaopai-process";

afterEach(() => { cleanup(); vi.useRealTimers(); });
const process: ReplyProcess = { state: "running", elapsed_ms: 0, steps: [{ key: "think", label: "正在思考", detail: "先比较证据，再说明未知项。", state: "running", at_ms: 0 }] };

it("updates elapsed time while work runs and freezes the stopped server duration", () => {
  vi.useFakeTimers();
  const view = render(<XiaopaiProcess process={process} live/>);
  expect(screen.getByText("进行中 · 0 秒")).toBeVisible();
  act(() => vi.advanceTimersByTime(3000));
  expect(screen.getByText("进行中 · 3 秒")).toBeVisible();
  view.rerender(<XiaopaiProcess process={{ ...process, state: "stopped", elapsed_ms: 2100, steps: [{ ...process.steps[0], state: "stopped" }] }}/>);
  act(() => vi.advanceTimersByTime(5000));
  expect(screen.getByText("已停止 · 2 秒")).toBeVisible();
});

it("keeps interrupted live work pending rather than claiming completion", () => {
  render(<XiaopaiProcess process={process}/>);
  expect(screen.getByText("等待核对 · 0 秒")).toBeVisible();
  expect(screen.queryByText(/已完成/)).not.toBeInTheDocument();
});

it("explains when a long research process displays only recent steps", () => {
  render(<XiaopaiProcess process={{ ...process, earlier_steps_omitted: 14 }} live/>);
  expect(screen.getByText(/较早的 14 步已收起/)).toBeVisible();
  expect(screen.getByText("正在思考")).toBeVisible();
});
